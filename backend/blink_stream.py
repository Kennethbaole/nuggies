"""Causal blink pulse pairing on filtered 50 Hz samples, independent of gaze windows.

Emits evidence, never commands. Inputs are baseline-adjusted ADC counts with
positive blink polarity. Thresholds combine resting MAD noise with count floors.
"""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class BlinkStreamConfig:
    rate: int = 50
    amplitude_floor: float = 800
    velocity_floor: float = 5000  # ADC counts / second
    noise_multiple: float = 8
    min_width_s: float = .04
    max_width_s: float = .24
    max_duration_s: float = .4
    min_gap_s: float = .15
    max_gap_s: float = .65
    min_ratio: float = .25
    max_ratio: float = 2.5
    max_horizontal_fraction: float = .15
    min_symmetry: float = .3
    quiet_s: float = .08
    refractory_s: float = .5

    def __post_init__(self):
        if any(not math.isfinite(v) or v <= 0 for v in vars(self).values()):
            raise ValueError('Blink settings must be positive and finite')
        if self.rate != 50:
            raise ValueError('Current blink stream requires 50 Hz filtered frames')
        if self.min_gap_s >= self.max_gap_s or self.min_width_s >= self.max_width_s:
            raise ValueError('Invalid blink intervals')


class BlinkPulseStream:
    def __init__(self, config=BlinkStreamConfig()):
        self.config = config
        self.reset()

    def reset(self):
        self.previous = None
        self.active = None
        self.first = None
        self.pair = None
        self.valley = math.inf
        self.quiet = 0
        self.blocked_until = -1
        self.history = deque(maxlen=100)
        self.last_pulse = None
        self.last_rejection = None

    def _finish(self, pulse, index):
        c = self.config
        values = pulse['values']
        peak = pulse['peak']
        width = sum(v >= peak / 2 for _, _, v in values) / c.rate
        rise, fall = pulse['rise'], pulse['fall']
        symmetry = min(rise, fall) / max(rise, fall, 1)
        h_energy = sum(h*h for _, h, _ in values)
        v_energy = sum(v*v for _, _, v in values)
        fraction = h_energy / max(h_energy + v_energy, 1)
        duration = (index - pulse['onset_sample']) / 250
        valid = (c.min_width_s <= width <= c.max_width_s
                 and duration <= c.max_duration_s and symmetry >= c.min_symmetry
                 and rise >= pulse['velocity_threshold'] and fall >= pulse['velocity_threshold']
                 and fraction <= c.max_horizontal_fraction)
        result = dict(onset_sample=pulse['onset_sample'], peak_sample=pulse['peak_sample'],
                      end_sample=index, peak=peak, width_ms=width*1000,
                      duration_ms=duration*1000, rise_velocity=rise, fall_velocity=fall,
                      symmetry=symmetry, horizontal_fraction=fraction, valid=valid)
        self.last_pulse = result
        if not valid:
            self.first = self.pair = None
            self.last_rejection = 'pulse_shape'
            return
        if self.pair is not None:
            self.first = self.pair = None
            self.blocked_until = index + round(c.refractory_s * 250)
            self.last_rejection = 'third_pulse'
            return
        if self.first is not None:
            first = self.first
            gap = (result['peak_sample'] - first['peak_sample']) / 250
            ratio = peak / first['peak']
            valley_ratio = self.valley / min(peak, first['peak'])
            if c.min_gap_s <= gap <= c.max_gap_s and c.min_ratio <= ratio <= c.max_ratio and valley_ratio <= .25:
                self.pair = dict(first=first, second=result, gap_ms=gap*1000,
                                 ratio=ratio, valley_ratio=valley_ratio)
                self.first = None
                self.quiet = 0
                return
        self.first = result
        self.valley = math.inf

    def process(self, h, v, sample_index, noise=(0., 0.)):
        """Return zero/one completed pair; sample indices remain raw 250 Hz indices."""
        c = self.config
        if not all(math.isfinite(x) for x in (h, v, *noise)):
            self.reset()
            return None
        if self.previous is not None and sample_index - self.previous[0] != round(250/c.rate):
            self.reset()
        previous = self.previous
        velocity = (v - previous[2]) * c.rate if previous else 0.
        self.previous = (sample_index, h, v)
        self.history.append((sample_index, h, v))
        threshold = max(c.amplitude_floor, c.noise_multiple * noise[1])
        velocity_threshold = max(c.velocity_floor, c.noise_multiple * noise[1] * c.rate)
        if sample_index < self.blocked_until:
            return None
        if self.first is not None:
            self.valley = min(self.valley, v)
            if self.active is None and sample_index - self.first['peak_sample'] > c.max_gap_s*250:
                self.first = None
        if self.active is None:
            if v >= threshold and velocity >= velocity_threshold:
                if self.pair is not None:
                    # Suppress the entire cluster as soon as a third pulse starts.
                    self.pair = self.first = None
                    self.blocked_until = sample_index + round(c.refractory_s*250)
                    self.last_rejection = 'third_pulse'
                    return None
                self.active = dict(onset_sample=previous[0] if previous else sample_index,
                    peak=v, peak_sample=sample_index, rise=velocity, fall=0.,
                    velocity_threshold=velocity_threshold,
                    values=[previous] if previous else [])
        if self.active is not None:
            pulse = self.active
            pulse['values'].append((sample_index, h, v))
            pulse['rise'] = max(pulse['rise'], velocity)
            pulse['fall'] = max(pulse['fall'], -velocity)
            if v > pulse['peak']:
                pulse['peak'], pulse['peak_sample'] = v, sample_index
            if sample_index - pulse['onset_sample'] > c.max_duration_s*250:
                self.active = self.first = self.pair = None
                self.last_rejection = 'long_pulse'
            elif v <= .2 * pulse['peak'] and sample_index > pulse['peak_sample']:
                self.active = None
                self._finish(pulse, sample_index)
        if self.pair is None or self.active is not None:
            return None
        pair = self.pair
        quiet_bound = max(400., 6*noise[1], .25*pair['second']['peak'])
        quiet = abs(v) <= quiet_bound and abs(h) <= max(400., 6*noise[0]) and abs(velocity) <= velocity_threshold
        self.quiet = self.quiet + 1 if quiet else 0
        # Wait the complete pairing interval: a third blink cannot arrive after
        # an early emission and silently become an accidental confirmation.
        if (sample_index - pair['first']['onset_sample'] >= 230
                and sample_index - pair['second']['peak_sample'] >= c.max_gap_s*250
                and self.quiet >= math.ceil(c.quiet_s*c.rate)):
            event = dict(label='double_blink', reason='pulse_pair',
                         onset_sample=pair['first']['onset_sample'], emitted_sample=sample_index,
                         pulse_pair=pair, pulse_pair_valid=True)
            self.pair = self.first = None
            self.blocked_until = sample_index + round(c.refractory_s*250)
            return event
        if sample_index - pair['second']['end_sample'] > 250:
            self.pair = None
            self.last_rejection = 'unsettled_pair'
        return None
