"""Mirror the website's wheel onto the ESP32 OLED.

    backend.app (/api/state) -> one "W:" frame per change -> ESP32 over USB

The website stays the only owner of the wheel. This adapter reads its state and
sends the display a complete picture each time: which slot is highlighted, the
eight labels and the centre text. It never sends actions back to the website.

Examples (start backend.app first; find ports with python -m scripts.doctor):

    # USB: ESP32 plugged into this machine
    .venv/bin/python -m backend.hud_sync --port /dev/cu.usbserial-0001

    # No hardware: print the frames the display would receive
    .venv/bin/python -m backend.hud_sync --print

Frame format, one line: W:<selected>|<8 labels>|<3 centre lines>
selected is -1 when nothing is highlighted; an empty label hides that slot.
A first centre line starting with "!" is an alert: the display drops the wheel
and shows it large, with the second line beneath. It is used for the moment a
double blink will be accepted, so the wearer does not blink too early.
USB only for now: the sketch's Wi-Fi mode expects a WebSocket server, which
does not exist yet.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from .envfile import load_env

HUD_BAUD = 115200
DEFAULT_URL = "http://127.0.0.1:8765"
SLOTS = 8
MAX_LABEL = 10  # Must match MAX_LABEL in firmware/esp32_hud.
# Characters that fit inside the ring's inner ellipse in the 4x6 font, by line count.
CENTER_LIMITS = {1: (14,), 2: (13, 13), 3: (10, 14, 10)}
HEARTBEAT_S = 1.0  # The sketch shows "No link" when frames stop for 4 s.
OFFLINE_TEXT = "Website offline"
MAX_CENTER = 14  # Must match MAX_CENTER in firmware/esp32_hud.
BLINK_ALERT = "!DOUBLE BLINK"

_ASCII = {"–": "-", "—": "-", "…": "..", "‘": "'", "’": "'", "“": '"', "”": '"'}


def ascii_text(text) -> str:
    """The OLED fonts are ASCII only, and '|' separates frame fields."""
    text = "".join(_ASCII.get(char, char) for char in str(text or ""))
    text = "".join(char if " " <= char <= "~" else " " for char in text).replace("|", "/")
    return " ".join(text.split())


def center_text(state: dict) -> str:
    """Same choice of centre text as frontend/hud.js, plus the eye-control reading pause."""
    hover = state.get("gaze_hover") or {}
    if state.get("eog_communication"):
        if state.get("eog_paused"):  # Glances do nothing until a double blink resumes.
            return "Paused. Double blink"
        if state.get("eog_choice_pending"):
            label = state["slots"][state["selected"]]["label"]
            return f"{label}. {'Double blink' if state.get('eog_confirmation_ready') else 'Return center'}"
        return "Choose a reply" if hover.get("phase") == "ready" else "Look center"
    if state.get("wheel_test"):
        return hover.get("message") or state.get("wheel_message") or "Eye test"
    if state.get("screen") == "spell":
        return state.get("draft") or "Choose letters"
    return state.get("confirmed") or "Ready"


def wrap_center(text: str) -> list[str]:
    """Up to three short lines; the last one ends in '..' when text is cut."""
    words = ascii_text(text).split()
    if not words:
        return []
    for count in (1, 2, 3):
        limits = CENTER_LIMITS[count]
        lines, rest = [], list(words)
        for limit in limits:
            line = ""
            while rest and len(line) + len(rest[0]) + bool(line) <= limit:
                line = (line + " " + rest.pop(0)).strip()
            if not line and rest:  # One word longer than the line.
                line, rest[0] = rest[0][:limit], rest[0][limit:]
                if not rest[0]:
                    rest.pop(0)
            lines.append(line)
        if not rest:
            return [line for line in lines if line]
    lines[-1] = lines[-1][:limits[-1] - 2].rstrip() + ".."
    return lines


def frame_for(state: dict) -> str:
    """One complete display frame for a website state snapshot."""
    slots = list(state.get("slots") or [])[:SLOTS]
    slots += [dict(label="", enabled=False)] * (SLOTS - len(slots))
    labels = [ascii_text(slot.get("label"))[:MAX_LABEL].rstrip() if slot.get("enabled") else "" for slot in slots]
    selected = state.get("selected", -1)
    # The website shows no highlight while the eyes drive the wheel.
    if state.get("wheel_test") or type(selected) is not int or not 0 <= selected < SLOTS or not labels[selected]:
        selected = -1
    if state.get("eog_communication") and state.get("eog_choice_pending") and state.get("eog_confirmation_ready"):
        lines = [BLINK_ALERT, ascii_text(slots[state["selected"]].get("label"))[:MAX_CENTER]]
    else:
        lines = wrap_center(center_text(state))
    return "W:" + "|".join([str(selected), *labels, *(lines + [""] * 3)[:3]])


def offline_frame() -> str:
    return "W:" + "|".join(["-1", *[""] * SLOTS, *(wrap_center(OFFLINE_TEXT) + [""] * 3)[:3]])


def fetch_state(url: str, token: str = "", timeout: float = 2.0) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urlopen(Request(url.rstrip("/") + "/api/state", headers=headers), timeout=timeout) as response:
        return json.load(response)


class SerialTarget:
    """ESP32 on a USB port."""

    def __init__(self, connection):
        self.connection = connection

    def send(self, frame: str) -> None:
        self.connection.write((frame + "\n").encode("ascii", errors="replace"))
        self.connection.flush()


class PrintTarget:
    def __init__(self):
        self.last = None

    def send(self, frame: str) -> None:
        if frame != self.last:  # Skip heartbeats.
            print(frame, flush=True)
            self.last = frame


class Mirror:
    """Sends a frame when the picture changes, and repeats it as a heartbeat."""

    def __init__(self, targets, heartbeat_s: float = HEARTBEAT_S):
        self.targets = targets
        self.heartbeat_s = heartbeat_s
        self.last_frame = None
        self.last_sent = 0.0

    def update(self, frame: str, now: float) -> bool:
        if frame == self.last_frame and now - self.last_sent < self.heartbeat_s:
            return False
        for target in self.targets:
            target.send(frame)
        self.last_frame, self.last_sent = frame, now
        return True


def run(url: str, token: str, targets, interval: float, stop: threading.Event) -> None:
    mirror = Mirror(targets)
    online = None
    while not stop.is_set():
        try:
            frame = frame_for(fetch_state(url, token))
            reachable = True
        except (URLError, OSError, ValueError, KeyError, TypeError):
            frame, reachable = offline_frame(), False
        if reachable != online:
            print(f"Website {'reachable' if reachable else 'unreachable'} at {url}", flush=True)
            online = reachable
        mirror.update(frame, time.monotonic())
        stop.wait(interval)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Mirror the website's wheel onto the ESP32 OLED.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Where backend.app is running")
    parser.add_argument("--port", help="ESP32 USB serial port, e.g. /dev/cu.usbserial-0001 (never the Nano's port)")
    parser.add_argument("--print", action="store_true", dest="show", help="Print each new frame")
    parser.add_argument("--interval", type=float, default=0.1, help="Seconds between website checks")
    args = parser.parse_args()
    if not (args.port or args.show):
        parser.error("choose at least one of --port or --print")

    targets = []
    connection = None
    try:
        if args.port:
            try:
                import serial
            except ImportError:
                raise SystemExit("Needs pyserial: .venv/bin/python -m pip install -r requirements.txt")
            try:
                connection = serial.Serial(args.port, HUD_BAUD, timeout=0.2, exclusive=True)
            except serial.SerialException as error:
                raise SystemExit(f"Serial error: {error}. Close the Arduino Serial Monitor and check the port.") from error
            time.sleep(2.0)  # Opening the port resets many ESP32 boards; wait for it to boot.
            targets.append(SerialTarget(connection))
        if args.show:
            targets.append(PrintTarget())
        run(args.url, os.environ.get("APP_TOKEN", ""), targets, args.interval, threading.Event())
    except KeyboardInterrupt:
        pass
    except OSError as error:
        raise SystemExit(f"Display link failed: {error}") from error
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
