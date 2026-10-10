import unittest
from backend.vertical_features import waveform_features
from backend.guided import GuidedTrial, protocol


class VerticalFeatureTests(unittest.TestCase):
    def test_balanced_pair_reports_ratio_order_and_delay(self):
        v=[8192]*100
        v[10:20]=[10192]*10
        v[60:70]=[6192]*10
        f=waveform_features([8192]*100,v,8192,8192,100)
        self.assertEqual(f['negative_positive_ratio'],1)
        self.assertEqual(f['signed_peak_gap_s'],.5)
        self.assertEqual(f['positive_half_height_width_s'],.1)
        self.assertEqual(f['horizontal_vertical_ratio'],0)

    def test_asymmetric_rebound_and_double_peaks_are_descriptive(self):
        v=[8192]*200
        v[10:20]=[11192]*10;v[30:40]=[7592]*10
        v[80:90]=[11192]*10
        f=waveform_features([8192]*200,v,8192,8192,100)
        self.assertEqual(f['negative_positive_ratio'],.2)
        self.assertEqual(len(f['positive_peaks_over_1500']),2)
        self.assertNotIn('action',f)

    def test_constant_channel_and_invalid_windows(self):
        f=waveform_features([8192]*10,[8192]*10,8192,8192)
        self.assertIsNone(f['negative_positive_ratio'])
        self.assertEqual(f['positive_half_height_width_s'],0)
        with self.assertRaises(ValueError): waveform_features([],[],8192,8192)
        with self.assertRaises(ValueError): waveform_features([8192],[],8192,8192)

    def test_vertical_protocol_has_balanced_classes_and_unique_ids(self):
        steps=protocol('vertical')
        self.assertEqual(sum(s[0] for s in steps),225)
        for label in ('up','down','blink','double_blink'):
            self.assertEqual(sum(s[1]==label for s in steps),5)
        self.assertEqual(len({s[2] for s in steps if s[3]=='movement'}),20)
        trial=GuidedTrial();trial.start(10,'vertical')
        self.assertEqual(trial.snapshot(10)['protocol'],'vertical')
        with self.assertRaises(ValueError): protocol('unknown')
