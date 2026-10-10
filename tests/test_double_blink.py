import unittest
from backend.double_blink import DoubleBlinkConfig, DoubleBlinkDetector
from backend.events import Action


class DoubleBlinkTests(unittest.TestCase):
    def signal(self, blocks, polarity=1):
        detector = DoubleBlinkDetector(DoubleBlinkConfig(fs=100, smoothing_s=.01, vertical_polarity=polarity))
        events = []
        for duration, dh, dv in [(2, 0, 0)] + blocks:
            for _ in range(round(duration * 100)):
                events.extend(detector.process(8192 + dh, 8192 + dv * polarity))
        return events

    def pair(self):
        return [(.08, 0, 4000), (.12, 0, -400), (.08, 0, 2000), (.1, 0, -700), (1.2, 0, 0)]

    def test_pair_emits_once_after_second_pulse_and_recovery(self):
        events = self.signal(self.pair())
        self.assertEqual([e.action for e in events], [Action.SELECT])
        self.assertGreater(events[0].time_s, 2.38)

    def test_single_and_slow_pair_do_not_select(self):
        self.assertEqual(self.signal([(.08,0,4000),(2,0,0)]), [])
        self.assertEqual(self.signal([(.08,0,4000),(.8,0,0),(.08,0,3000),(2,0,0)]), [])

    def test_continuous_two_maxima_without_release_is_rejected(self):
        self.assertEqual(self.signal([(.08,0,4000),(.1,0,1500),(.08,0,2200),(2,0,0)]), [])

    def test_horizontal_activity_and_short_noise_rejected(self):
        self.assertEqual(self.signal([(.08,2500,4000),(.12,0,0),(.08,0,2000),(2,0,0)]), [])
        self.assertEqual(self.signal([(.01,0,4000),(.2,0,0),(.01,0,2000),(2,0,0)]), [])

    def test_polarity_configuration_and_two_separate_pairs(self):
        self.assertEqual(len(self.signal(self.pair(), -1)), 1)
        self.assertEqual(len(self.signal(self.pair() + self.pair())), 2)

    def test_extra_pulse_before_recovery_cancels_candidate(self):
        self.assertEqual(self.signal([(.08,0,4000),(.12,0,0),(.08,0,2000),(.02,0,0),(.08,0,3000),(2,0,0)]), [])

    def test_invalid_config_and_counts(self):
        for threshold in (0,float('nan'),float('inf')):
            with self.assertRaises(ValueError): DoubleBlinkConfig(threshold=threshold)
        with self.assertRaises(ValueError): DoubleBlinkConfig(min_gap_s=1,max_gap_s=.5)
        detector=DoubleBlinkDetector()
        for value in (-1,16384,float('nan')):
            with self.assertRaises(ValueError): detector.process(8192,value)

    def test_evaluation_reports_misses_duplicates_false_and_unknown(self):
        from backend.review_blinks import score_windows
        report=dict(samples=100,config={'fs':100},events=[{'sample_index':i} for i in (10,20,70,95)])
        windows=[dict(start_sample=0,end_sample=30,expected='SELECT'),dict(start_sample=30,end_sample=60,expected='SELECT'),dict(start_sample=60,end_sample=90,expected=None)]
        score=score_windows(report,windows)
        self.assertEqual((score['hit_windows'],score['missed_windows'],score['duplicates'],score['false_candidates'],score['unscored_candidates']),(1,1,1,1,1))
        with self.assertRaises(ValueError):score_windows(report,[dict(start_sample=0,end_sample=40),dict(start_sample=30,end_sample=50)])

    def test_clipping_cancels_a_pending_pair(self):
        self.assertEqual(self.signal([(.08,0,4000),(.01,0,8191),(.12,0,0),(.08,0,2000),(2,0,0)]), [])
