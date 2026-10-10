"""Keyboard direction simulator; uses only the Python standard library."""

import os
import select
import sys
import termios
import time
import tty
from contextlib import contextmanager
from typing import Iterator, TextIO

from .models import Direction, DirectionEvent, EOGSample


KEY_DIRECTIONS = {
    "w": Direction.UP,
    "s": Direction.DOWN,
    "a": Direction.LEFT,
    "d": Direction.RIGHT,
    " ": Direction.CENTER,
    "c": Direction.CENTER,
    "\x1b[A": Direction.UP,
    "\x1b[B": Direction.DOWN,
    "\x1b[C": Direction.RIGHT,
    "\x1b[D": Direction.LEFT,
    "\x1bOA": Direction.UP,
    "\x1bOB": Direction.DOWN,
    "\x1bOC": Direction.RIGHT,
    "\x1bOD": Direction.LEFT,
}


def simulate_direction(key: str) -> DirectionEvent | None:
    """Convert one keyboard input to an event; ignore unrecognized keys."""
    direction = KEY_DIRECTIONS.get(key.lower() if len(key) == 1 else key)
    if direction is None:
        return None
    return DirectionEvent(direction, time.time_ns() // 1_000_000, "keyboard")


SYNTHETIC_CHANNELS = {
    Direction.CENTER: (0.0, 0.0),
    Direction.LEFT: (-1.0, 0.0),
    Direction.RIGHT: (1.0, 0.0),
    Direction.UP: (0.0, 1.0),
    Direction.DOWN: (0.0, -1.0),
}


def simulate_sample(key: str) -> EOGSample | None:
    """Generate a clean channel pair; these are not biological waveforms."""
    direction = KEY_DIRECTIONS.get(key.lower() if len(key) == 1 else key)
    if direction is None:
        return None
    horizontal, vertical = SYNTHETIC_CHANNELS[direction]
    return EOGSample(horizontal, vertical, time.time_ns() // 1_000_000)


@contextmanager
def keyboard_input(stream: TextIO = sys.stdin) -> Iterator[TextIO]:
    """Enable immediate input on macOS/Linux and always restore the terminal."""
    if not stream.isatty():
        raise ValueError("Run the simulator in an interactive terminal.")
    descriptor = stream.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        yield stream
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


class KeyboardDirectionSource:
    """Replacement seam for a future sensor-backed DirectionSource.

    Emits one event per recognized keypress (including keyboard repeats).
    It does not simulate raw EOG waveforms or infer biological polarity.
    """

    def __init__(self, stream: TextIO = sys.stdin):
        self.stream = stream

    def _read_key(self) -> str:
        descriptor = self.stream.fileno()
        key = os.read(descriptor, 1).decode("ascii", errors="replace")
        if key == "\x1b":
            # Arrow keys arrive as short escape sequences. Bound the wait so
            # pressing Escape by itself does not stall input indefinitely.
            for _ in range(2):
                if not select.select([descriptor], [], [], 0.05)[0]:
                    break
                key += os.read(descriptor, 1).decode("ascii", errors="replace")
        return key

    def read_event(self) -> DirectionEvent | None:
        while True:
            key = self._read_key()
            if not key or key.lower() == "q" or key == "\x04":
                return None
            event = simulate_direction(key)
            if event is not None:
                return event


class KeyboardSampleSource(KeyboardDirectionSource):
    """One synthetic sample per keypress; key release does not emit CENTER."""

    def read_sample(self) -> EOGSample | None:
        while True:
            key = self._read_key()
            if not key or key.lower() == "q" or key == "\x04":
                return None
            sample = simulate_sample(key)
            if sample is not None:
                return sample
