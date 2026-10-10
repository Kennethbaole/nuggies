"""Opt-in supervised four-direction wheel test; experimental, no speech output."""
from .events import Action
from .paired_glance import PairedGlanceConfig, PairedGlanceDetector


class LiveWheelTest:
    def __init__(self):
        self.reset()

    def reset(self):
        self.horizontal = PairedGlanceDetector(source='eye-wheel-test')
        self.vertical = PairedGlanceDetector(PairedGlanceConfig(threshold=1500, pulse_min_s=.08), source='eye-wheel-test')
        self.message = 'Look straight ahead for a second, then glance and return.'

    def process(self, horizontal, vertical):
        if horizontal <= 5 or horizontal >= 16378 or vertical <= 5 or vertical >= 16378:
            self.reset()
            self.message = 'Signal clipped. Rest at center before trying again.'
            return None
        h = self.horizontal.process(horizontal)
        v = self.vertical.process(vertical)
        if h and v:
            self.reset()
            self.message = 'Both directions triggered together; no command applied.'
            return None
        action = None
        if h:
            action = 'right' if h[0].action == Action.NEXT else 'left'
        elif v:
            action = 'select' if v[0].action == Action.NEXT else 'back'
        if action:
            self.reset()  # settle/warm up both channels before another command
            self.message = {'right': 'Right → next slot', 'left': 'Left → previous slot',
                            'select': 'Up → select', 'back': 'Down → back'}[action]
        return action
