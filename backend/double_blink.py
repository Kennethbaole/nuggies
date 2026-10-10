"""Experimental two-channel double-blink candidates. Not wired to live SELECT."""
from collections import deque
from dataclasses import dataclass
import math

from .events import Action, EyeEvent


@dataclass(frozen=True)
class DoubleBlinkConfig:
    fs: int = 250
    threshold: float = 1200
    first_peak_min: float = 2200
    smoothing_s: float = .02
    min_width_s: float = .025
    max_width_s: float = .25
    min_gap_s: float = .12
    max_gap_s: float = .65
    min_peak_ratio: float = .25
    max_peak_ratio: float = 1.5
    max_horizontal_ratio: float = .35
    settle_s: float = .08
    cooldown_s: float = 1.0
    vertical_polarity: int = 1

    def __post_init__(self):
        if self.fs <= 0 or self.vertical_polarity not in (-1, 1):
            raise ValueError('Invalid sampling rate or polarity')
        for name, value in vars(self).items():
            if name not in ('fs', 'vertical_polarity') and (not math.isfinite(value) or value <= 0):
                raise ValueError(f'{name} must be positive and finite')
        if (self.min_width_s >= self.max_width_s or self.min_gap_s >= self.max_gap_s
                or self.min_peak_ratio >= self.max_peak_ratio):
            raise ValueError('Invalid interval bounds')


class DoubleBlinkDetector:
    """Requires distinct positive pulses, compatible shapes, then quiet recovery.

    Baselines freeze during pulses/pending pairs. One continuous broad waveform
    is never split into two blinks merely because it contains two local maxima.
    """
    def __init__(self, config=DoubleBlinkConfig(), source='offline'):
        self.config, self.source = config, source
        self.index = -1
        self.window = deque()
        self.total_h = self.total_v = 0.0
        self.base_h = self.base_v = None
        self.pulse = None
        self.pending = None
        self.pair = None
        self.quiet = 0
        self.cooldown_until = 0
        self.last_diagnostic = 'warming up'
        self.last_pair_features = {}

    def _valid_pulse(self, pulse):
        c = self.config
        peak = pulse['peak']
        width = sum(x >= peak / 2 for x in pulse['values']) / c.fs
        return (c.min_width_s <= width <= c.max_width_s
                and pulse['horizontal'] / peak <= c.max_horizontal_ratio)

    def _finish_pulse(self, pulse):
        c = self.config
        if not self._valid_pulse(pulse):
            self.pending = None
            self.last_diagnostic = 'pulse shape or horizontal activity rejected'
            return
        if self.pending is not None:
            first = self.pending
            gap = (pulse['peak_index'] - first['peak_index']) / c.fs
            ratio = pulse['peak'] / first['peak']
            if (c.min_gap_s <= gap <= c.max_gap_s
                    and c.min_peak_ratio <= ratio <= c.max_peak_ratio):
                self.last_pair_features = dict(first_peak_s=round(first['peak_index']/c.fs,3), second_peak_s=round(pulse['peak_index']/c.fs,3), first_peak=round(first['peak'],1), second_peak=round(pulse['peak'],1), peak_gap_s=round(gap,3), peak_ratio=round(ratio,3), first_horizontal=round(first['horizontal'],1), second_horizontal=round(pulse['horizontal'],1))
                self.pair = self.index
                self.pending = None
                self.quiet = 0
                self.last_diagnostic = 'pair awaiting recovery'
                return
        self.pending = pulse if pulse['peak'] >= c.first_peak_min else None
        self.last_diagnostic = 'first pulse pending' if self.pending else 'weak isolated pulse'

    def process(self, horizontal, vertical):
        c = self.config
        if any(not math.isfinite(float(x)) or not 0 <= float(x) <= 16383 for x in (horizontal, vertical)):
            raise ValueError('ADC values must be finite and within 0–16383')
        self.index += 1
        if any(float(x) <= 5 or float(x) >= 16378 for x in (horizontal, vertical)):
            self.pulse = self.pending = self.pair = None
            self.cooldown_until = self.index + round(c.cooldown_s * c.fs)
            self.last_diagnostic = 'clipping rejected'
            return []
        h, v = float(horizontal), float(vertical)
        self.window.append((h, v)); self.total_h += h; self.total_v += v
        size = max(1, round(c.smoothing_s * c.fs))
        if len(self.window) > size:
            old_h, old_v = self.window.popleft()
            self.total_h -= old_h; self.total_v -= old_v
        if len(self.window) < size:
            return []
        h, v = self.total_h / size, self.total_v / size
        if self.base_v is None:
            self.base_h, self.base_v = h, v
        dh = h - self.base_h
        dv = (v - self.base_v) * c.vertical_polarity
        if self.pulse is None and self.pending is None and self.pair is None:
            self.base_h += dh / (2 * c.fs)
            self.base_v += (v - self.base_v) / (2 * c.fs)
        if self.index < c.fs or self.index < self.cooldown_until:
            return []
        if self.pair is not None:
            # Extra positive activity or prolonged failure to recover is ambiguous.
            if dv >= c.threshold or (self.index - self.pair) / c.fs > 1:
                self.pair = None
                self.cooldown_until = self.index + round(c.cooldown_s * c.fs)
                self.last_diagnostic = 'ambiguous recovery rejected'
                return []
            self.quiet = self.quiet + 1 if abs(dv) < c.threshold * .4 and abs(dh) < c.threshold * .4 else 0
            if self.quiet >= round(c.settle_s * c.fs):
                self.pair = None
                self.cooldown_until = self.index + round(c.cooldown_s * c.fs)
                self.last_diagnostic = 'SELECT candidate'
                return [EyeEvent(Action.SELECT, self.index, self.index / c.fs, self.source)]
            return []
        if self.pending and self.pulse is None and (self.index - self.pending['peak_index']) / c.fs > c.max_gap_s:
            self.pending = None
            self.last_diagnostic = 'single pulse expired'
        if self.pulse is None:
            if dv >= c.threshold:
                self.pulse = dict(start=self.index, peak=dv, peak_index=self.index,
                                  horizontal=abs(dh), values=[dv])
            return []
        pulse = self.pulse
        pulse['values'].append(dv)
        pulse['horizontal'] = max(pulse['horizontal'], abs(dh))
        if dv > pulse['peak']:
            pulse['peak'], pulse['peak_index'] = dv, self.index
        if (self.index - pulse['start']) / c.fs > .6:
            self.pulse = self.pending = None
            self.cooldown_until = self.index + round(c.cooldown_s * c.fs)
            self.last_diagnostic = 'long pulse rejected'
        elif dv < c.threshold * .3:
            self.pulse = None
            self._finish_pulse(pulse)
        return []
