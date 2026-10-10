"""Experimental horizontal-only glance/return detector. Offline use only.

Does not infer absolute eye position. One event requires two opposite excursions
separated in time and a quiet finish. Defaults are exploratory, not calibration.
"""
from collections import deque
from dataclasses import dataclass
import math
from .events import Action, EyeEvent


@dataclass(frozen=True)
class PairedGlanceConfig:
    fs: int = 250
    threshold: float = 1500
    smoothing_s: float = 0.1
    pulse_min_s: float = 0.12
    return_min_s: float = 0.8
    timeout_s: float = 5.0
    settle_s: float = 0.2
    cooldown_s: float = 0.5
    release_fraction: float = 0.35
    polarity: int = 1  # positive is right

    def __post_init__(self):
        if self.fs <= 0 or self.polarity not in (-1, 1):
            raise ValueError('Invalid sampling rate or polarity')
        for name in ('threshold', 'smoothing_s', 'pulse_min_s', 'return_min_s', 'timeout_s', 'settle_s', 'cooldown_s', 'release_fraction'):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive and finite')
        if self.return_min_s >= self.timeout_s or self.release_fraction >= 1:
            raise ValueError('Invalid return interval or release fraction')


class PairedGlanceDetector:
    def __init__(self, config=PairedGlanceConfig(), source='offline'):
        self.config, self.source = config, source
        self.index = -1
        self.window = deque()
        self.total = 0
        self.baseline = None
        self.phase = 'idle'
        self.sign = 0
        self.started = 0
        self.count = self.quiet = 0
        self.cooldown_until = 0

    def reset(self):
        self.phase = 'idle'
        self.count = self.quiet = 0
        self.cooldown_until = self.index + round(self.config.cooldown_s * self.config.fs)

    def process(self, horizontal):
        c = self.config
        value = float(horizontal)
        if not math.isfinite(value) or not 0 <= value <= 16383:
            raise ValueError('Horizontal ADC count must be finite and within 0–16383')
        self.index += 1
        self.window.append(value); self.total += value
        size = max(1, round(c.smoothing_s * c.fs))
        if len(self.window) > size: self.total -= self.window.popleft()
        if len(self.window) < size: return []
        mean = self.total / size
        if self.baseline is None: self.baseline = mean
        dev = (mean - self.baseline) * c.polarity
        if self.phase == 'idle':
            self.baseline += (mean - self.baseline) / (2 * c.fs)
            if self.index < c.fs or self.index < self.cooldown_until: return []
            if abs(dev) >= c.threshold:
                self.phase = 'outbound'; self.sign = 1 if dev > 0 else -1
                self.started = self.index; self.count = 1
            return []
        age = (self.index - self.started) / c.fs
        if age > c.timeout_s:
            self.reset(); return []
        opposite = -dev * self.sign >= c.threshold
        if self.phase == 'outbound':
            if dev * self.sign >= c.threshold:
                self.count += 1
            else:
                if self.count < round(c.pulse_min_s * c.fs):
                    self.reset(); return []
                self.phase = 'waiting_return'; self.count = 0
        if self.phase == 'waiting_return' and opposite:
            if age < c.return_min_s:
                self.reset(); return []
            self.phase = 'return'; self.count = 1
            return []
        if self.phase == 'return':
            if opposite:
                self.count += 1
            elif abs(dev) < c.release_fraction * c.threshold:
                if self.count < round(c.pulse_min_s * c.fs):
                    self.reset(); return []
                self.phase = 'settling'; self.quiet = 1
        elif self.phase == 'settling':
            if abs(dev) < c.release_fraction * c.threshold:
                self.quiet += 1
                if self.quiet >= round(c.settle_s * c.fs):
                    action = Action.NEXT if self.sign > 0 else Action.PREV
                    event = EyeEvent(action, self.index, self.index / c.fs, self.source)
                    self.reset()
                    return [event]
            else:
                self.quiet = 0
        return []
