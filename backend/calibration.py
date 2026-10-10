"""Explicit raw-count normalization. No automatically guessed hardware polarity."""

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import EOGSample
from .serial_input import ADCSample


@dataclass(frozen=True)
class Calibration:
    horizontal_baseline: float
    vertical_baseline: float
    horizontal_scale: float
    vertical_scale: float
    horizontal_polarity: int = 1
    vertical_polarity: int = 1
    threshold: float = 0.5
    sample_rate_hz: float = 100.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if min(self.horizontal_scale, self.vertical_scale, self.threshold, self.sample_rate_hz) <= 0:
            raise ValueError("Scales, threshold, and sample rate must be positive")
        if self.horizontal_polarity not in (-1, 1) or self.vertical_polarity not in (-1, 1):
            raise ValueError("Polarity must be +1 or -1")

    def normalize(self, sample: ADCSample) -> EOGSample:
        return EOGSample((sample.horizontal - self.horizontal_baseline) / self.horizontal_scale * self.horizontal_polarity,
                         (sample.vertical - self.vertical_baseline) / self.vertical_scale * self.vertical_polarity,
                         sample.timestamp_ms, sample.source)

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text()))

    def save(self, path):
        with open(path, "x", encoding="utf-8") as stream:
            json.dump(asdict(self), stream, indent=2)
            stream.write("\n")


class ExponentialSmoother:
    """Optional causal low-pass; coefficients derived from documented rate/cutoff."""

    def __init__(self, sample_rate_hz, cutoff_hz=8.0):
        if not 0 < cutoff_hz < sample_rate_hz / 2:
            raise ValueError("Cutoff must be below half the sample rate")
        self.alpha = 1 - math.exp(-2 * math.pi * cutoff_hz / sample_rate_hz)
        self.values = None

    def apply(self, sample):
        if self.values is None:
            self.values = (sample.horizontal, sample.vertical)
        else:
            self.values = tuple(old + self.alpha * (new - old) for old, new in
                                zip(self.values, (sample.horizontal, sample.vertical)))
        return EOGSample(*self.values, sample.timestamp_ms, sample.source)
