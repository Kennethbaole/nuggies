import unittest
from backend.events import Action
from backend.paired_glance import PairedGlanceConfig, PairedGlanceDetector


class PairedGlanceTests(unittest.TestCase):
    def run_signal(self, blocks, **kwargs):
        detector = PairedGlanceDetector(PairedGlanceConfig(fs=100, smoothing_s=.01, **kwargs))
        events = []
        for duration, value in [(2, 8192)] + blocks:
            for _ in range(round(duration * 100)):
                events.extend(detector.process(value))
        return events

    def test_one_command_after_return_and_settling_each_direction(self):
        for sign, action in [(-1, Action.PREV), (1, Action.NEXT)]:
            events = self.run_signal([(.3, 8192 + sign*2500), (1.7, 8192),
                                      (.3, 8192 - sign*2500), (2, 8192)])
            self.assertEqual([e.action for e in events], [action])
            self.assertGreaterEqual(events[0].time_s, 4.3)

    def test_isolated_spike_or_missing_return_never_commands(self):
        self.assertEqual(self.run_signal([(.3, 11000), (6, 8192)]), [])
        self.assertEqual(self.run_signal([(.03, 11000), (2, 8192), (.3, 5500), (2, 8192)]), [])

    def test_fast_biphasic_blink_like_pulse_is_rejected(self):
        self.assertEqual(self.run_signal([(.2, 11000), (.2, 5500), (2, 8192)]), [])

    def test_two_separate_pairs_produce_two_commands(self):
        one = [(.3, 5500), (1.7, 8192), (.3, 11000), (1, 8192)]
        self.assertEqual(len(self.run_signal(one + one)), 2)

    def test_invalid_config_and_counts_fail(self):
        for threshold in (0, float('nan'), float('inf')):
            with self.assertRaises(ValueError): PairedGlanceConfig(threshold=threshold)
        d = PairedGlanceDetector()
        for value in (-1, 16384, float('nan')):
            with self.assertRaises(ValueError): d.process(value)
