import unittest
from backend.blink_shape import blink_shape


class BlinkShapeTests(unittest.TestCase):
    def wave(self, peaks):
        vertical = [0.] * 50
        for center in peaks:
            for delta, amplitude in [(-2, 800), (-1, 2000), (0, 3000), (1, 2000), (2, 800)]:
                vertical[center + delta] = amplitude
        return [(0., value) for value in vertical]

    def test_two_separated_lobes_have_timing_evidence(self):
        result = blink_shape(self.wave([10, 25]))
        self.assertEqual(result['blink_pair_valid'], 1)
        self.assertEqual(result['blink_pair_gap_ms'], 300)

    def test_single_lobe_and_long_gap_are_not_pairs(self):
        self.assertEqual(blink_shape(self.wave([10]))['blink_pair_valid'], 0)
        self.assertEqual(blink_shape(self.wave([5, 40]))['blink_pair_valid'], 0)

    def test_sustained_upward_shift_is_not_pair(self):
        self.assertEqual(blink_shape([(0, 3000)] * 50)['blink_pair_valid'], 0)

    def test_invalid_frames_rejected(self):
        with self.assertRaises(ValueError):
            blink_shape([(0, float('nan'))] * 50)
