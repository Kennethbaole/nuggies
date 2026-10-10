import math
import unittest
from scripts.eog_signal_comparison import Biquad, event_features, lda_scores, dtw_distance


class SignalComparisonTests(unittest.TestCase):
    def test_filter_preserves_constant_level(self):
        for kind in ('lowpass','notch'):
            filt=Biquad(15 if kind=='lowpass' else 60,kind)
            values=[filt.process(8192) for _ in range(1000)]
            self.assertLess(max(abs(x-8192) for x in values),1e-6)

    def test_features_are_finite_on_rest_and_lda_export_is_portable(self):
        features=event_features([(0.,0.)]*50)
        self.assertTrue(all(math.isfinite(x) for x in features))
        model=dict(feature_mean=[0]*len(features),feature_scale=[1]*len(features),
                   weights=[[1]*len(features),[0]*len(features)],intercepts=[0,2])
        self.assertEqual(lda_scores(features,model)[1],2)

    def test_dtw_identical_signal_zero(self):
        signal=[(0.,float(i)) for i in range(50)]
        self.assertEqual(dtw_distance(signal,signal),0)
