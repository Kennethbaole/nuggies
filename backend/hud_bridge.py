"""Drive the ESP32 ring HUD from eye events, and speak what gets selected.

    eye events (live Nano, replay, scenario, or keyboard)
        -> NEXT / PREV / SELECT / BACK
        -> HUD commands over USB serial: n, p, s, H:4
    ESP32 reports "SELECTED:<slot>:<label>" -> phrase from config/hud_phrases.json -> speech

Examples (find ports with: .venv/bin/python -m serial.tools.list_ports):

    # Arrow keys stand in for the eyes: left/right move, space/up select, down = back
    .venv/bin/python -m backend.hud_bridge --hud-port /dev/cu.usbserial-0001 --keyboard

    # A synthetic 30 s session plays on the HUD in real time
    .venv/bin/python -m backend.hud_bridge --hud-port /dev/cu.usbserial-0001 --scenario demo

    # Live eyes: Nano (250 Hz sketch) + ESP32 both plugged into a laptop ON BATTERY
    .venv/bin/python -m backend.hud_bridge --hud-port /dev/cu.usbserial-0001 \
        --eog-port /dev/cu.usbmodem1101 --record session.csv

Speech uses macOS `say` or Linux `espeak` if present; otherwise the phrase is
printed. Add --no-speech to just print.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
from contextlib import ExitStack

from .events import Action, DetectorConfig, EOGEventDetector

HUD_BAUD = 115200
BACK_SLOT = 4
DEFAULT_PHRASES = os.path.join(os.path.dirname(__file__), "..", "config", "hud_phrases.json")


def action_to_commands(action: Action) -> list[str]:
    """HUD commands for one eye event. BACK highlights the Back slot and selects it."""
    if action is Action.NEXT:
        return ["n"]
    if action is Action.PREV:
        return ["p"]
    if action is Action.SELECT:
        return ["s"]
    if action is Action.BACK:
        return [f"H:{BACK_SLOT}", "s"]
    raise ValueError(f"unknown action {action}")


def parse_selected(line: str) -> tuple[int, str] | None:
    """'SELECTED:2:Listen' -> (2, 'Listen'); anything else -> None."""
    if not line.startswith("SELECTED:"):
        return None
    parts = line.strip().split(":", 2)
    if len(parts) != 3 or not parts[1].lstrip("-").isdigit():
        return None
    return int(parts[1]), parts[2]


def load_phrases(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {}
    labels = data.get("labels", data) if isinstance(data, dict) else {}
    return {str(k): str(v) for k, v in labels.items() if isinstance(v, str)}


class Speaker:
    def __init__(self, enabled: bool = True):
        self.command = None
        if enabled:
            if shutil.which("say"):
                self.command = ["say"]
            elif shutil.which("espeak"):
                self.command = ["espeak"]

    def speak(self, text: str) -> None:
        print(f"  speaking: {text}", flush=True)
        if self.command:
            # Non-blocking so eye events keep flowing while it talks.
            subprocess.Popen(self.command + [text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class HUD:
    """Writes commands to the ESP32 and handles what it reports back."""

    def __init__(self, connection, phrases: dict, speaker: Speaker):
        self.connection = connection
        self.phrases = phrases
        self.speaker = speaker
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)

    def start(self) -> None:
        self._reader.start()

    def stop(self) -> None:
        self._stop.set()

    def send(self, command: str) -> None:
        self.connection.write((command + "\n").encode("ascii", errors="replace"))
        self.connection.flush()

    def set_options(self, labels: list[str]) -> None:
        self.send("O:" + ",".join(labels))

    def handle_event(self, action: Action, when: str = "") -> None:
        print(f"{when}{action.value}", flush=True)
        for command in action_to_commands(action):
            self.send(command)
            time.sleep(0.03)  # let the ESP32 finish one line before the next

    def handle_line(self, line: str) -> None:
        selected = parse_selected(line)
        if selected is None:
            return
        slot, label = selected
        print(f"  HUD selected slot {slot}: {label}", flush=True)
        if slot == BACK_SLOT:
            return
        self.speaker.speak(self.phrases.get(label, label))

    def _read_loop(self) -> None:
        pending = b""
        while not self._stop.is_set():
            try:
                chunk = self.connection.read(64)
            except Exception:
                return
            if not chunk:
                continue
            pending += chunk
            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                self.handle_line(raw.decode("ascii", errors="replace").strip())


def run_keyboard(hud: HUD) -> None:
    from .models import Direction
    from .simulator import KeyboardDirectionSource, keyboard_input

    mapping = {
        Direction.LEFT: Action.PREV,
        Direction.RIGHT: Action.NEXT,
        Direction.CENTER: Action.SELECT,  # space
        Direction.UP: Action.SELECT,
        Direction.DOWN: Action.BACK,
    }
    print("Left/right: move | Space or Up: select | Down: back | Q: quit", flush=True)
    with keyboard_input() as stream:
        source = KeyboardDirectionSource(stream)
        while (event := source.read_event()) is not None:
            hud.handle_event(mapping[event.direction], "[keyboard] ")


def run_samples(hud: HUD, samples, config: DetectorConfig, realtime: bool) -> None:
    detector = EOGEventDetector(config, "replay")
    started = time.monotonic()
    for i, (h, v) in enumerate(samples):
        if realtime and i % 25 == 0:
            target = started + i / config.fs
            if (wait := target - time.monotonic()) > 0:
                time.sleep(wait)
        for event in detector.process(h, v):
            hud.handle_event(event.action, f"[{event.time_s:6.2f} s] ")
    time.sleep(2.0)  # let the last selection be reported and spoken


def run_live(hud: HUD, eog_port: str, config: DetectorConfig, record_path: str | None, stack: ExitStack) -> None:
    import serial

    from .serial_input import SerialADCSource

    nano = stack.enter_context(serial.Serial(eog_port, 115200, timeout=0.5, exclusive=True))
    recorder = None
    if record_path:
        from .recording import ADCRecorder

        recorder = ADCRecorder(stack.enter_context(open(record_path, "x", newline="", encoding="utf-8")))
    source = SerialADCSource(nano)
    detector = EOGEventDetector(config, "nano_r4")
    print(f"Reading eyes from {eog_port}. Keep eyes still for {config.warmup_s:.0f} s.", flush=True)
    while True:
        sample = source.read_sample()
        if recorder is not None:
            recorder.write(sample)
        for event in detector.process(sample.horizontal, sample.vertical):
            hud.handle_event(event.action, f"[{event.time_s:6.2f} s] ")


def _replay_samples(path: str):
    from .recording import CSVReplaySource

    with open(path, newline="", encoding="utf-8") as stream:
        source = CSVReplaySource(stream)
        while (sample := source.read_sample()) is not None:
            yield sample.horizontal, sample.vertical


def main() -> None:
    parser = argparse.ArgumentParser(description="Drive the ESP32 ring HUD from eye events.")
    parser.add_argument("--hud-port", required=True, help="ESP32 serial port, e.g. /dev/cu.usbserial-0001")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--keyboard", action="store_true", help="Arrow keys stand in for eye events")
    inputs.add_argument("--scenario", help="Synthetic scenario name (see backend.eog_scenarios --list)")
    inputs.add_argument("--replay", help="Raw ADC recording CSV")
    inputs.add_argument("--eog-port", help="Live Nano running nano_r4_eog_250hz")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fast", action="store_true", help="Scenario/replay as fast as possible instead of real time")
    parser.add_argument("--record", help="With --eog-port, also save raw samples to a new CSV")
    parser.add_argument("--options", help="Comma-separated ring labels to load first (up to 7)")
    parser.add_argument("--phrases", default=DEFAULT_PHRASES, help="JSON mapping label -> sentence")
    parser.add_argument("--no-speech", action="store_true")
    parser.add_argument("--glance-threshold", type=float, default=DetectorConfig.glance_threshold)
    parser.add_argument("--blink-threshold", type=float, default=DetectorConfig.blink_threshold)
    parser.add_argument("--horizontal-polarity", type=int, choices=(-1, 1), default=1)
    parser.add_argument("--vertical-polarity", type=int, choices=(-1, 1), default=1)
    args = parser.parse_args()
    if args.record and not args.eog_port:
        parser.error("--record requires --eog-port")
    try:
        config = DetectorConfig(glance_threshold=args.glance_threshold, blink_threshold=args.blink_threshold,
                                horizontal_polarity=args.horizontal_polarity, vertical_polarity=args.vertical_polarity)
    except ValueError as error:
        parser.error(str(error))

    try:
        import serial
    except ImportError:
        raise SystemExit("Needs pyserial: .venv/bin/python -m pip install -r requirements.txt")

    phrases = load_phrases(args.phrases)
    try:
        with ExitStack() as stack:
            connection = stack.enter_context(serial.Serial(args.hud_port, HUD_BAUD, timeout=0.2, exclusive=True))
            time.sleep(2.0)  # opening the port resets many ESP32 boards; wait for it to boot
            hud = HUD(connection, phrases, Speaker(not args.no_speech))
            hud.start()
            stack.callback(hud.stop)
            if args.options:
                hud.set_options([label.strip() for label in args.options.split(",") if label.strip()])
            if args.keyboard:
                run_keyboard(hud)
            elif args.scenario:
                from .eog_scenarios import generate

                samples, _ = generate(args.scenario, args.seed)
                run_samples(hud, samples, config, realtime=not args.fast)
            elif args.replay:
                run_samples(hud, _replay_samples(args.replay), config, realtime=not args.fast)
            else:
                run_live(hud, args.eog_port, config, args.record, stack)
    except KeyboardInterrupt:
        pass
    except serial.SerialException as error:
        raise SystemExit(f"Serial error: {error}. Close the Arduino Serial Monitor and check ports.") from error
    except (ValueError, TimeoutError, OSError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
