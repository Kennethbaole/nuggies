"""Synthetic regressions for the historical late-window failure.

These waveforms are analytic examples, not recorded participant data.
"""
import math
import unittest

from backend.blink_shape import blink_shape
from backend.eog_waveform import WaveformProfile
from backend.temporal_eog import EventSegmenter, SegmentConfig
from scripts.eog_reset_search import matches


def synthetic_pair(index):
    """Two positive pulses followed by a shared negative recovery tail."""
    first = 4800*math.exp(-((index-4)/1.7)**2)
    second = 2800*math.exp(-((index-15)/1.7)**2)
    tail = -1900*math.exp(-(index-18)/10) if index >= 18 else 0
    return (0., first+second+tail)


class LateBlinkWindowTests(unittest.TestCase):
    def test_return_refractory_excludes_both_blink_peaks(self):
        detector = EventSegmenter(SegmentConfig(capture_s=1, refractory_s=.4))
        # A direction/return was just emitted at frame 0. Its 400 ms refractory
        # prevents an onset while the positive pulses occur at frames 4 and 15.
        detector.ready_at = 20
        result = None
        for index in range(100):
            candidate = detector.process(*synthetic_pair(index))
            if candidate:
                result = candidate
                break
        self.assertIsNotNone(result)
        self.assertEqual(result['onset'], 20)
        self.assertEqual(result['emitted'], 66)
        self.assertEqual(len(result['samples']), 50)
        window_start = result['emitted']-49
        self.assertGreater(window_start, 15)
        self.assertEqual(blink_shape([synthetic_pair(i) for i in range(50)])['blink_pulse_count'], 2)
        self.assertEqual(blink_shape(result['samples'])['blink_pulse_count'], 0)

    def test_similar_single_and_double_tails_cannot_prove_two_pulses(self):
        samples = [synthetic_pair(i) for i in range(17, 67)]
        normalized = [[h/3000, v/3000] for h, v in samples]
        # Single and double training labels can share the same recovery shape.
        # Tiny differences make a nearest-template result without two pulses.
        profile = WaveformProfile(dict(version=1, capture_s=1, threshold_h=800,
            threshold_v=800, scale=[3000, 3000],
            labels=['left','right','up','down','blink','double_blink'], waves=[
                [[-1,0]]*50, [[1,0]]*50, [[0,1]]*50, [[0,-1]]*50,
                [[h,v+.021] for h,v in normalized],
                [[h,v+.020] for h,v in normalized]]))
        result = profile.classify(samples)
        self.assertEqual(result['label'], 'double_blink')
        self.assertLess(result['distance'], .08)
        self.assertLess(result['other_label_margin'], 1.5)
        self.assertEqual(result['blink_pulse_count'], 0)

    def test_reproduction_requires_metric_match_not_only_event_timing(self):
        expected = dict(label='double_blink', reason='blink', emitted_sample=400,
                        onset_sample=170, distance=.005388, other_label_margin=1.218038)
        self.assertTrue(matches(dict(expected, blink_pulse_count=0), expected))
        self.assertFalse(matches(dict(expected, distance=.005368), expected))
        self.assertFalse(matches(dict(expected, onset_sample=171), expected))


if __name__ == '__main__':
    unittest.main()
