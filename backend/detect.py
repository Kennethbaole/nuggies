"""Run glance/blink event detection on a recording, a live Nano, or a scenario.

Examples:
    # Synthetic scenario straight into the detector (no files, no hardware)
    python3 -m backend.detect --scenario demo

    # A recording (synthetic or real); labels are used automatically if
    # <file>.labels.json exists next to it
    python3 -m backend.detect --replay demo.csv

    # Live Nano at 250 Hz (needs pyserial and the nano_r4_eog_250hz sketch)
    .venv/bin/python -m backend.detect --serial-port /dev/cu.usbmodem1101 --record live.csv

    # Neutral recording -> noise levels and suggested minimum thresholds
    python3 -m backend.detect --replay neutral.csv --calibrate

Output: one line per event, e.g. "12.348 s  NEXT". Thresholds are raw ADC
counts; the defaults are placeholders until tuned on real recordings.
"""

from __future__ import annotations

import argparse
import json
import os
from contextlib import ExitStack

from .events import DetectorConfig, EOGEventDetector, calibrate_from_neutral, match_events


def _config(args) -> DetectorConfig:
    return DetectorConfig(
        fs=args.fs,
        glance_threshold=args.glance_threshold,
        blink_threshold=args.blink_threshold,
        horizontal_polarity=args.horizontal_polarity,
        vertical_polarity=args.vertical_polarity,
    )


def _print_event(event) -> None:
    print(f"{event.time_s:8.3f} s  {event.action.value}", flush=True)


def _report(events, labels) -> None:
    result = match_events(events, labels)
    expected = sum(1 for label in labels if label.get("expected"))
    print(f"\nIntended actions detected: {len(result['hits'])}/{expected}")
    for label in result["misses"]:
        print(f"  missed {label['expected']} ({label['kind']}) at {label['time_s']:.2f} s")
    print(f"False activations: {len(result['false_events'])}")
    for event in result["false_events"]:
        print(f"  unexpected {event.action.value} at {event.time_s:.2f} s")


def run_samples(samples, config: DetectorConfig, source: str, labels=None) -> list:
    detector = EOGEventDetector(config, source)
    events = []
    for h, v in samples:
        for event in detector.process(h, v):
            _print_event(event)
            events.append(event)
    if labels is not None:
        _report(events, labels)
    return events


def _replay_samples(path: str):
    from .recording import CSVReplaySource

    with open(path, newline="", encoding="utf-8") as stream:
        source = CSVReplaySource(stream)
        while (sample := source.read_sample()) is not None:
            yield sample.horizontal, sample.vertical


def run_serial(port: str, config: DetectorConfig, record_path: str | None) -> None:
    try:
        import serial
    except ImportError as error:
        raise ValueError("Serial mode needs pyserial: install requirements.txt in .venv.") from error
    from .serial_input import SerialADCSource

    try:
        with ExitStack() as stack:
            connection = stack.enter_context(serial.Serial(port, 115200, timeout=0.5, exclusive=True))
            recorder = None
            if record_path:
                from .recording import ADCRecorder

                stream = stack.enter_context(open(record_path, "x", newline="", encoding="utf-8"))
                recorder = ADCRecorder(stream)
            source = SerialADCSource(connection)
            detector = EOGEventDetector(config, "nano_r4")
            print(f"Listening on {port}. Keep eyes still for {config.warmup_s:.0f} s while the baseline settles.", flush=True)
            while True:
                sample = source.read_sample()
                if recorder is not None:
                    recorder.write(sample)
                for event in detector.process(sample.horizontal, sample.vertical):
                    _print_event(event)
    except serial.SerialException as error:
        raise ValueError(f"Cannot read {port}: {error}. Close Serial Monitor and check USB.") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect NEXT/PREV/SELECT/BACK eye events.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--scenario", help="Generate a synthetic scenario in memory (see backend.eog_scenarios --list)")
    modes.add_argument("--replay", help="Raw ADC recording CSV")
    modes.add_argument("--serial-port", help="Live Nano running nano_r4_eog_250hz")
    parser.add_argument("--seed", type=int, default=0, help="Scenario seed")
    parser.add_argument("--labels", help="Labels JSON (default: <replay>.labels.json if present)")
    parser.add_argument("--record", help="With --serial-port, also save raw samples to a new CSV")
    parser.add_argument("--calibrate", action="store_true", help="With --replay, print noise levels of a neutral recording")
    parser.add_argument("--fs", type=int, default=250)
    parser.add_argument("--glance-threshold", type=float, default=DetectorConfig.glance_threshold)
    parser.add_argument("--blink-threshold", type=float, default=DetectorConfig.blink_threshold)
    parser.add_argument("--horizontal-polarity", type=int, choices=(-1, 1), default=1)
    parser.add_argument("--vertical-polarity", type=int, choices=(-1, 1), default=1)
    args = parser.parse_args()
    if args.record and not args.serial_port:
        parser.error("--record requires --serial-port")
    if args.calibrate and not args.replay:
        parser.error("--calibrate requires --replay")
    try:
        config = _config(args)
    except ValueError as error:
        parser.error(str(error))

    try:
        if args.scenario:
            from .eog_scenarios import generate

            samples, labels = generate(args.scenario, args.seed, fs=args.fs)
            run_samples(samples, config, "synthetic_scenario", labels)
        elif args.replay:
            if args.calibrate:
                stats = calibrate_from_neutral(list(_replay_samples(args.replay)), args.fs)
                print(json.dumps(stats, indent=2))
                return
            labels_path = args.labels or args.replay + ".labels.json"
            labels = None
            if os.path.exists(labels_path):
                with open(labels_path, encoding="utf-8") as stream:
                    labels = json.load(stream)["labels"]
            elif args.labels:
                raise ValueError(f"labels file not found: {args.labels}")
            run_samples(_replay_samples(args.replay), config, "replay", labels)
        else:
            run_serial(args.serial_port, config, args.record)
    except KeyboardInterrupt:
        pass
    except (ValueError, TimeoutError, OSError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
