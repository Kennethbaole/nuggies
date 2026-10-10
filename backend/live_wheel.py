"""Experimental pulse-based radial hover, assuming 250 Hz and verified polarity.

AC-coupled EOG does not measure absolute gaze. Hold the first direction until an
opposite return pulse, timeout, clipping, or reset. Never activate a wheel item.
"""
from collections import deque
import math

DIRECTIONS = ('Up', 'Up-right', 'Right', 'Down-right', 'Down', 'Down-left', 'Left', 'Up-left')


class LiveWheelTest:
    def __init__(self):
        self.reset()

    def reset(self):
        self.window = deque(maxlen=15)
        self.baseline = None
        self.age = self.count = self.quiet = 0
        self.slot = None
        self.vector = (0, 0)
        self.phase = 'warmup'
        self.horizontal = self.vertical = 0
        self.message = 'Rest at center for one second, then look toward a wheel item.'

    def snapshot(self):
        return dict(slot=self.slot, direction=DIRECTIONS[self.slot] if self.slot is not None else None,
                    horizontal=round(self.horizontal), vertical=round(self.vertical), phase=self.phase)

    def process(self, horizontal, vertical):
        if not all(math.isfinite(x) and 5 < x < 16378 for x in (horizontal, vertical)):
            self.reset()
            self.message = 'Signal clipped. Rest at center before trying again.'
            return None
        self.window.append((horizontal, vertical))
        means = tuple(sum(v[i] for v in self.window) / len(self.window) for i in (0, 1))
        if self.baseline is None:
            self.baseline = means
        self.horizontal, self.vertical = (means[i] - self.baseline[i] for i in (0, 1))
        h, v = self.horizontal, self.vertical
        self.age += 1
        if self.phase == 'warmup':
            self.baseline = tuple(self.baseline[i] + .03 * (means[i] - self.baseline[i]) for i in (0, 1))
            if self.age >= 250:
                self.phase = 'idle'
                self.message = 'Ready. Look toward a slot; return to center before the next direction.'
        elif self.phase == 'idle':
            if max(abs(h), abs(v)) >= 1500:
                self.count += 1
                if self.count >= 15:
                    # Require both axes to cross threshold for a diagonal.
                    self.vector = (h if abs(h) >= 1500 else 0, v if abs(v) >= 1500 else 0)
                    self.slot = round(math.atan2(self.vector[0], self.vector[1]) / (math.pi / 4)) % 8
                    self.phase, self.age = 'hover', 0
                    self.message = f'{DIRECTIONS[self.slot]} hover. Return to center to release.'
                    return self.slot
            else:
                self.count = 0
                self.baseline = tuple(self.baseline[i] + .002 * (means[i] - self.baseline[i]) for i in (0, 1))
        elif self.phase == 'hover':
            x, y = self.vector
            opposite = (h*x + v*y) / math.hypot(x, y) < -1000
            self.count = self.count + 1 if opposite else 0
            if self.count >= 10 or self.age >= 2000:
                self.slot = None
                self.phase, self.age, self.quiet = 'release', 0, 0
                self.message = 'Hover released. Rest at center.'
        elif self.phase == 'release':
            self.quiet = self.quiet + 1 if max(abs(h), abs(v)) < 600 else 0
            if self.quiet >= 100:
                self.reset()
        return None
