"""Simple threshold classification of synthetic two-channel samples."""

import math

from .models import Direction, DirectionEvent, EOGSample, SampleSource


class ThresholdClassifier:
    def __init__(
        self,
        threshold: float = 0.5,
        horizontal_polarity: int = 1,
        vertical_polarity: int = 1,
    ):
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("threshold must be finite and positive")
        if horizontal_polarity not in (-1, 1) or vertical_polarity not in (-1, 1):
            raise ValueError("channel polarities must be +1 or -1")
        self.threshold = threshold
        self.horizontal_polarity = horizontal_polarity
        self.vertical_polarity = vertical_polarity

    def classify(self, sample: EOGSample) -> DirectionEvent:
        horizontal = sample.horizontal * self.horizontal_polarity
        vertical = sample.vertical * self.vertical_polarity
        if not math.isfinite(horizontal) or not math.isfinite(vertical):
            raise ValueError("sample channels must be finite")
        if max(abs(horizontal), abs(vertical)) < self.threshold:
            direction = Direction.CENTER
        elif abs(horizontal) == abs(vertical):
            # An equally strong diagonal is ambiguous for a four-way consumer.
            direction = Direction.CENTER
        elif abs(horizontal) > abs(vertical):
            direction = Direction.RIGHT if horizontal > 0 else Direction.LEFT
        else:
            direction = Direction.UP if vertical > 0 else Direction.DOWN
        return DirectionEvent(direction, sample.timestamp_ms, sample.source)


class ClassifiedDirectionSource:
    """Keep acquisition replaceable without changing the event consumer."""

    def __init__(self, source: SampleSource, classifier: ThresholdClassifier):
        self.source = source
        self.classifier = classifier

    def read_event(self) -> DirectionEvent | None:
        sample = self.source.read_sample()
        return None if sample is None else self.classifier.classify(sample)
