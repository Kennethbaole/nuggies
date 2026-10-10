"""Direction events shared by simulated and future classified sensor input."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Direction(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    CENTER = "CENTER"


@dataclass(frozen=True)
class DirectionEvent:
    direction: Direction
    timestamp_ms: int
    source: str


@dataclass(frozen=True)
class EOGSample:
    """Two channels in normalized simulation units, not volts or ADC counts."""

    horizontal: float
    vertical: float
    timestamp_ms: int
    source: str = "synthetic"


class SampleSource(Protocol):
    def read_sample(self) -> EOGSample | None:
        """Return the next sample, or None when acquisition is closed."""
        ...


class DirectionSource(Protocol):
    """Future sensor adapters classify digitized samples before returning events."""

    def read_event(self) -> DirectionEvent | None:
        """Return the next event, or None when the source is closed."""
        ...
