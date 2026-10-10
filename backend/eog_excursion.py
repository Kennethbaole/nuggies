"""Remember a directional excursion and reserve its opposite pulse as a return.

This is a navigation veto, not a direction classifier or confirmation signal.
Quiet alone never clears an outbound excursion on AC-coupled EOG.
"""
from collections import deque
import math

AXES = {'right': (0, 1), 'left': (0, -1), 'up': (1, 1), 'down': (1, -1)}
OPPOSITE = {'right': 'left', 'left': 'right', 'up': 'down', 'down': 'up'}


class ExcursionGuard:
    def __init__(self, thresholds=(800., 800.)):
        self.thresholds = tuple(thresholds)
        self.reset()

    def reset(self):
        self.history = deque(maxlen=300)
        self.completed = deque(maxlen=8)
        self.owner = None
        self.previous_index = None
        self.horizontal_seed = None
        self.horizontal_run = 0

    def observe(self, h, v, sample_index, *, allow_new=True):
        if not all(math.isfinite(x) for x in (h, v)):
            self.reset()
            return
        if self.previous_index is not None and sample_index-self.previous_index != 5:
            self.reset()
        self.previous_index = sample_index
        self.history.append((sample_index, h, v))
        if self.owner is None and allow_new:
            sign = 1 if h > 0 else -1
            active = abs(h) >= max(800, self.thresholds[0]) and abs(h) >= .2*abs(v)
            self.horizontal_run = self.horizontal_run+1 if active and sign == self.horizontal_seed else 1 if active else 0
            self.horizontal_seed = sign if active else None
            if self.horizontal_run >= 3:
                self.horizontal_run = 0
                self.claim('right' if sign > 0 else 'left', sample_index-10)
                return
        self._advance(sample_index, h, v)

    def claim(self, direction, onset_sample):
        """Called for both accepted and rejected directional waveform candidates."""
        if direction not in AXES:
            return
        if self.owner is not None:
            return  # Quiet or a classifier retry cannot overwrite an open excursion.
        axis, sign = AXES[direction]
        frames = [row for row in self.history if row[0] >= onset_sample-15]
        if not any(sign*row[axis+1] >= self.thresholds[axis] for row in frames):
            return  # Do not reserve a direction absent from its observed waveform.
        self.owner = dict(direction=direction, onset_sample=onset_sample, peak=0.,
                          outbound=False, opposite_frames=0, return_onset=None,
                          first_opposite=None, quiet_frames=0)
        for index, h, v in frames:
            if self.owner is None:
                break
            self._advance(index, h, v)

    def _advance(self, index, h, v):
        owner = self.owner
        if owner is None:
            return
        axis, sign = AXES[owner['direction']]
        values = (h, v)
        projection = sign*values[axis]
        if not owner['outbound']:
            if projection < self.thresholds[axis]:
                return
            owner['outbound'] = True
        owner['peak'] = max(owner['peak'], projection)
        opposite = (projection <= -max(self.thresholds[axis], .25*owner['peak'])
                    and abs(values[axis]) >= 1.2*abs(values[1-axis]))
        if owner['return_onset'] is None:
            if opposite:
                if not owner['opposite_frames']:
                    owner['first_opposite'] = index
                owner['opposite_frames'] += 1
                if owner['opposite_frames'] >= 3:
                    owner['return_onset'] = owner['first_opposite']
            else:
                owner['opposite_frames'] = 0
            return
        owner['quiet_frames'] = owner['quiet_frames']+1 if max(abs(h), abs(v)) <= 400 else 0
        if owner['quiet_frames'] >= 13:
            self.completed.append(dict(direction=owner['direction'],
                onset_sample=owner['onset_sample'], return_onset=owner['return_onset'],
                end_sample=index))
            self.owner = None

    def return_context(self, direction, onset_sample):
        """Return ownership metadata when a candidate is a reserved opposite pulse.

        Completed intervals survive quiet so a delayed one-second classification
        of the return is still vetoed, while a later, fresh opposite gaze is allowed.
        """
        if direction not in AXES:
            return None
        owner = self.owner
        if (owner and direction == OPPOSITE[owner['direction']]
                and onset_sample >= owner['onset_sample']-15):
            return dict(owner)
        for completed in reversed(self.completed):
            if (direction == OPPOSITE[completed['direction']]
                    and completed['return_onset']-15 <= onset_sample <= completed['end_sample']):
                return dict(completed)
        return None
