"""Temporal input gates. Thresholds are engineering defaults, not EOG validation."""

from dataclasses import dataclass


@dataclass
class GestureGate:
    hold_ms: int = 100
    cooldown_ms: int = 350
    stale_ms: int = 600

    def __post_init__(self):
        self.candidate = "CENTER"
        self.since = 0
        self.armed = True
        self.last_action = -10**12
        self.last_sample = None

    def update(self, direction: str, timestamp_ms: int):
        if self.last_sample is not None and (timestamp_ms < self.last_sample or timestamp_ms - self.last_sample > self.stale_ms):
            self.candidate = "CENTER"
            self.armed = False  # Require observed neutral after a gap.
        self.last_sample = timestamp_ms
        if direction == "CENTER":
            self.armed = True
        if direction != self.candidate:
            self.candidate, self.since = direction, timestamp_ms
        if (direction in ("LEFT", "RIGHT") and self.armed
                and timestamp_ms - self.since >= self.hold_ms
                and timestamp_ms - self.last_action >= self.cooldown_ms):
            self.armed = False
            self.last_action = timestamp_ms
            return direction.lower()
        return None


class DoubleBlinkGate:
    """Pair discrete, already-detected blink events; this is not a blink detector."""

    def __init__(self, minimum_ms=120, maximum_ms=650, cooldown_ms=900):
        self.minimum_ms, self.maximum_ms, self.cooldown_ms = minimum_ms, maximum_ms, cooldown_ms
        self.first = None
        self.last_selection = -10**12

    def update(self, timestamp_ms):
        if timestamp_ms - self.last_selection < self.cooldown_ms:
            return None
        if self.first is not None:
            gap = timestamp_ms - self.first
            if self.minimum_ms <= gap <= self.maximum_ms:
                self.first = None
                self.last_selection = timestamp_ms
                return "select"
            if 0 <= gap < self.minimum_ms:
                return None
        self.first = timestamp_ms
        return None
