"""Streaming glance/blink event detection on raw two-channel ADC samples.

Detects *events* (a quick glance and back, a deliberate blink pattern) rather
than classifying held eye position, because EOG baselines drift over seconds
while events are short and large.

    glance right  -> NEXT      (horizontal rises above baseline, then returns)
    glance left   -> PREV      (horizontal falls below baseline, then returns)
    double blink  -> SELECT    (two short vertical bumps close together)
    long blink    -> BACK      (one vertical bump held longer than long_blink_s)
    single blink  -> nothing   (natural blinks are ignored)

Pipeline per sample: 100 ms moving average (removes noise and cancels 60 Hz
hum at 250 Hz) -> deviation from a slow baseline (EMA, frozen during events)
-> per-channel state machines.

All thresholds are in raw ADC counts and are PLACEHOLDERS chosen for the
synthetic scenarios. Replace them with values measured from real recordings
(see `calibrate_from_neutral`). Time is sample_index / fs, not host receipt
time, because USB delivers samples in bursts.

Known limitation: looking up also raises the vertical channel and can look
like a long blink. Keep gaze level during use, or require the user to return
to center first; validate with real recordings.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    NEXT = "NEXT"
    PREV = "PREV"
    SELECT = "SELECT"
    BACK = "BACK"


@dataclass(frozen=True)
class EyeEvent:
    action: Action
    sample_index: int
    time_s: float
    source: str


@dataclass(frozen=True)
class DetectorConfig:
    fs: int = 250
    smoothing_s: float = 0.1          # moving-average window
    baseline_tau_s: float = 1.0       # baseline follows slow drift
    warmup_s: float = 1.0             # no events while the baseline settles
    glance_threshold: float = 600.0   # counts away from baseline
    glance_release: float = 0.4       # fraction of threshold to count as "back"
    glance_release_hold_s: float = 0.05
    blink_threshold: float = 1000.0   # counts above vertical baseline
    blink_release: float = 0.5
    short_blink_min_s: float = 0.04
    short_blink_max_s: float = 0.6
    double_blink_window_s: float = 0.6  # gap from end of blink 1 to start of blink 2
    long_blink_s: float = 0.8
    max_glance_s: float = 2.0         # longer means held gaze or drift: re-center
    max_vertical_s: float = 3.0       # longer than any blink: re-center
    horizontal_polarity: int = 1      # +1: higher counts mean looking right
    vertical_polarity: int = 1        # +1: blinks raise the vertical counts

    def __post_init__(self):
        if self.fs <= 0:
            raise ValueError("fs must be positive")
        for name in ("glance_threshold", "blink_threshold", "smoothing_s", "baseline_tau_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.horizontal_polarity not in (-1, 1) or self.vertical_polarity not in (-1, 1):
            raise ValueError("polarities must be +1 or -1")
        if self.short_blink_max_s >= self.long_blink_s:
            raise ValueError("short_blink_max_s must be below long_blink_s")


class _MovingAverage:
    def __init__(self, size: int):
        self.size = max(1, size)
        self.values: deque[float] = deque()
        self.total = 0.0

    def push(self, value: float) -> float | None:
        self.values.append(value)
        self.total += value
        if len(self.values) > self.size:
            self.total -= self.values.popleft()
        return self.total / len(self.values) if len(self.values) == self.size else None


class EOGEventDetector:
    """Feed raw samples one at a time with `process`; it returns new events."""

    def __init__(self, config: DetectorConfig = DetectorConfig(), source: str = "unknown"):
        self.config = config
        self.source = source
        window = round(config.smoothing_s * config.fs)
        self._ma_h = _MovingAverage(window)
        self._ma_v = _MovingAverage(window)
        self._alpha = 1.0 / (config.baseline_tau_s * config.fs)
        self._warmup = round(config.warmup_s * config.fs)
        self._release_hold = max(1, round(config.glance_release_hold_s * config.fs))
        self.index = -1
        self.base_h: float | None = None
        self.base_v: float | None = None
        # Horizontal state
        self._h_active = False
        self._h_quiet = 0
        self._h_start = 0
        self._last_sh = 0.0
        self._last_sv = 0.0
        # Vertical state
        self._v_active = False
        self._v_start = 0
        self._v_long_fired = False
        self._pending_blink_end: int | None = None
        # Most recent deviations, useful for plotting/debugging
        self.last_dev_h = 0.0
        self.last_dev_v = 0.0

    def _event(self, action: Action) -> EyeEvent:
        return EyeEvent(action, self.index, self.index / self.config.fs, self.source)

    def process(self, horizontal: int | float, vertical: int | float) -> list[EyeEvent]:
        c = self.config
        self.index += 1
        sh = self._ma_h.push(float(horizontal))
        sv = self._ma_v.push(float(vertical))
        if sh is None or sv is None:
            return []
        if self.base_h is None:
            self.base_h, self.base_v = sh, sv

        dev_h = (sh - self.base_h) * c.horizontal_polarity
        dev_v = (sv - self.base_v) * c.vertical_polarity
        self.last_dev_h, self.last_dev_v = dev_h, dev_v

        # Baseline follows slow drift whenever no event is in progress, and
        # freezes during events so a held glance or blink is not absorbed.
        if not self._h_active and not self._v_active:
            self.base_h += self._alpha * (sh - self.base_h)
        if not self._v_active:
            self.base_v += self._alpha * (sv - self.base_v)
        self._last_sh, self._last_sv = sh, sv

        if self.index < self._warmup:
            return []

        events: list[EyeEvent] = []
        events += self._update_vertical(dev_v)
        events += self._update_horizontal(dev_h)
        return events

    def _update_vertical(self, dev_v: float) -> list[EyeEvent]:
        c = self.config
        fs = c.fs
        if not self._v_active:
            if dev_v > c.blink_threshold:
                self._v_active = True
                self._v_start = self.index
                self._v_long_fired = False
                # A blink in progress cancels any half-detected glance.
                self._h_active = False
            return []

        duration = (self.index - self._v_start) / fs
        if duration >= c.max_vertical_s:
            # Not a blink (looking up, or drift): accept the new level.
            self._v_active = False
            self.base_v = self._last_sv
            self._pending_blink_end = None
            return []
        if not self._v_long_fired and duration >= c.long_blink_s:
            self._v_long_fired = True
            self._pending_blink_end = None
            return [self._event(Action.BACK)]

        if dev_v >= c.blink_release * c.blink_threshold:
            return []

        # Blink ended.
        self._v_active = False
        if self._v_long_fired:
            return []
        if not (c.short_blink_min_s <= duration <= c.short_blink_max_s):
            self._pending_blink_end = None
            return []
        start = self._v_start
        pending = self._pending_blink_end
        if pending is not None and (start - pending) / fs <= c.double_blink_window_s:
            self._pending_blink_end = None
            return [self._event(Action.SELECT)]
        self._pending_blink_end = self.index
        return []

    def _update_horizontal(self, dev_h: float) -> list[EyeEvent]:
        c = self.config
        if self._v_active:
            return []  # blink crosstalk must not become a glance
        if not self._h_active:
            if dev_h > c.glance_threshold:
                self._h_active, self._h_quiet, self._h_start = True, 0, self.index
                return [self._event(Action.NEXT)]
            if dev_h < -c.glance_threshold:
                self._h_active, self._h_quiet, self._h_start = True, 0, self.index
                return [self._event(Action.PREV)]
            return []
        # Wait for the eyes to come back to center before allowing another glance.
        if (self.index - self._h_start) / c.fs >= c.max_glance_s:
            # Held gaze or drift: accept the new level as center.
            self._h_active = False
            self.base_h = self._last_sh
            return []
        if abs(dev_h) < c.glance_release * c.glance_threshold:
            self._h_quiet += 1
            if self._h_quiet >= self._release_hold:
                self._h_active = False
        else:
            self._h_quiet = 0
        return []


def detect_samples(samples, config: DetectorConfig = DetectorConfig(), source: str = "unknown") -> list[EyeEvent]:
    """Run the detector over a whole list of (horizontal, vertical) samples."""
    detector = EOGEventDetector(config, source)
    events: list[EyeEvent] = []
    for h, v in samples:
        events += detector.process(h, v)
    return events


def calibrate_from_neutral(samples, fs: int = 250, k: float = 6.0) -> dict:
    """Summarize a neutral recording (eyes still, no blinks if possible).

    Returns per-channel smoothed noise (standard deviation) and suggested
    minimum thresholds of k * noise. Real thresholds should also be checked
    against labeled glance/blink trials: the threshold must sit well below the
    smallest deliberate event and well above the neutral noise.
    """
    window = max(1, round(0.1 * fs))
    out = {}
    for name, column in (("horizontal", 0), ("vertical", 1)):
        ma = _MovingAverage(window)
        smoothed = [s for s in (ma.push(float(row[column])) for row in samples) if s is not None]
        if len(smoothed) < 2:
            raise ValueError("need at least a few hundred milliseconds of samples")
        mean = sum(smoothed) / len(smoothed)
        sd = math.sqrt(sum((x - mean) ** 2 for x in smoothed) / (len(smoothed) - 1))
        out[name] = {"mean": mean, "noise_sd": sd, "suggested_min_threshold": k * sd}
    return out


def match_events(events: list[EyeEvent], labels: list[dict], window_s: float = 2.0) -> dict:
    """Compare detected events with intended labels.

    A label with an expected action is a hit if an event of that action occurs
    within [time_s, time_s + window_s] and has not been used by another label.
    Labels with expected None (e.g. natural blinks) must produce no event.
    Unmatched events are false activations.
    """
    used: set[int] = set()
    hits, misses = [], []
    for label in sorted(labels, key=lambda item: item["time_s"]):
        expected = label.get("expected")
        if expected is None:
            continue
        match = None
        for i, event in enumerate(events):
            if i in used or event.action.value != expected:
                continue
            if label["time_s"] <= event.time_s <= label["time_s"] + window_s:
                match = i
                break
        if match is None:
            misses.append(label)
        else:
            used.add(match)
            hits.append((label, events[match]))
    false_events = [event for i, event in enumerate(events) if i not in used]
    return {"hits": hits, "misses": misses, "false_events": false_events}
