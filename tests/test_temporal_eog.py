import unittest
from backend.temporal_eog import CausalFilter, DecisionPolicy, EventSegmenter, SegmentConfig


class TemporalEOGTests(unittest.TestCase):
    def test_direction_consistency_and_bounded_rearm(self):
        d=EventSegmenter(SegmentConfig(rate=10,warmup_s=.1,capture_s=.6,refractory_s=.2))
        for _ in range(10):d.process(0,0)
        for i in range(10):self.assertIsNone(d.process(1000 if i%2 else -1000,0))
        events=[]
        for _ in range(30):
            result=d.process(1000,0)
            if result:events.append(result)
        self.assertGreaterEqual(len(events),2) # cannot wait forever against a frozen baseline
        self.assertTrue(all(len(e['samples'])==6 for e in events))

    def test_continuous_dc_recovery_and_clipping_reset(self):
        d=CausalFilter();values=[]
        for i in range(3000):
            value=d.process(8192 if i<300 else 10192,8192)
            if value is not None:values.append(value)
        self.assertGreater(max(x[0] for x in values),1000)
        self.assertLess(abs(values[-1][0]),1)
        self.assertIsNone(d.process(16383,8192))
        self.assertEqual(d.count,0)

    def test_return_suppression_expires_and_uncertain_events_are_rejected(self):
        p=DecisionPolicy(reject=True)
        self.assertEqual(p.apply('left',.001,3,100)[0],'left')
        self.assertEqual(p.apply('right',.001,3,150)[0],'return')
        self.assertEqual(p.apply('right',.001,3,350)[0],'right')
        self.assertEqual(p.apply('up',.2,3,400)[0],'unknown')
        self.assertEqual(p.apply('up',.001,1.1,400)[0],'unknown')
        self.assertLess(p.apply('blink',.001,3,410)[1],p.apply('left',.001,3,420)[1])
        p.reset()
        self.assertEqual(p.apply('left',.001,3,421)[0],'left')

    def test_paired_direction_requires_return_and_rejects_fast_blink(self):
        from backend.temporal_eog import PairedDirectionDetector
        for pause,expected in [(50,['up']),(0,[])]:
            d=PairedDirectionDetector();events=[]
            for n,v in [(60,0),(10,1500),(pause,0),(10,-1500),(30,0)]:
                for _ in range(n):
                    event=d.process(0,v)
                    if event:events.append(event['label'])
            self.assertEqual(events,expected)

    def test_continuous_scoring_counts_returns_and_excludes_other_folds(self):
        from scripts.eog_stream_experiment import score
        rows=[]
        def add(n,trial,phase,label):
            rows.extend(dict(run_id='valid',trial_id=trial,phase=phase,intended_label=label) for _ in range(n))
        add(6,'baseline','baseline','neutral')
        add(3,'up-1','prepare','neutral');add(2,'up-1','movement','up');add(4,'up-1','return','neutral')
        add(3,'blink-1','prepare','neutral');add(2,'blink-1','movement','blink');add(3,'blink-1','rest','neutral')
        add(2,'up-2','movement','up')
        events=[dict(onset=i,emitted=i+1,label=l) for i,l in [(9,'up'),(9,'down'),(10,'up'),(12,'down'),(18,'blink'),(25,'down')]]
        result=score(events,rows,dict(run_id='valid',labels=['neutral','up','blink']),1,fs=1)
        self.assertEqual((result['trials'],result['hits'],result['wrong'],result['duplicates'],result['false_directions']),(1,1,1,1,1))
        self.assertEqual(result['negative_seconds'],18)

    def test_rejected_excursion_return_is_not_a_command(self):
        p=DecisionPolicy(reject=True,track_rejected=True)
        self.assertEqual(p.apply('left',.17,3,100)[0],'unknown')
        self.assertEqual(p.apply('right',.02,3,200)[0],'return')
        # Recovery expires; it must not permanently disable opposite commands.
        self.assertEqual(p.apply('right',.02,3,301)[0],'right')
        p.reset()
        self.assertEqual(p.apply('right',.02,3,302)[0],'right')

    def test_stable_baseline_tracks_small_drift_but_freezes_during_excursions(self):
        from backend.temporal_eog import StableBaselineFilter
        d=StableBaselineFilter(3)
        for _ in range(800):d.process(8192,8192)
        for _ in range(1500):d.process(8292,8192)
        self.assertGreater(d.baseline[0],8250)
        before=d.baseline
        for _ in range(1500):d.process(10200,8192)
        self.assertEqual(d.baseline,before) # quiet off-center voltage cannot redefine center
        d.process(16383,8192)
        self.assertIsNone(d.baseline)
        self.assertFalse(d.clean)
        with self.assertRaises(ValueError):StableBaselineFilter(0)

    def test_shape_features_separate_equal_height_different_duration(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest('Optional EOG experiment dependencies are not installed')
        from scripts.eog_stream_experiment import features
        short=np.zeros((50,2));long=short.copy()
        short[5:10,1]=1;long[5:35,1]=1
        a=features(short,shape=True);b=features(long,shape=True)
        self.assertTrue(np.isfinite(a).all())
        self.assertEqual(len(a),23)
        self.assertNotEqual(a[17],b[17]) # vertical half-height occupancy

    def test_retry_waits_for_clean_readings_with_blinks_excluded(self):
        p=DecisionPolicy(reject=True,rate=10,retry_s=3)
        self.assertEqual(p.apply('left',.17,3,100)[0],'unknown')
        self.assertTrue(p.retry)
        self.assertEqual(p.apply('right',.01,3,120)[0],'retry')
        for _ in range(20):p.observe(0,0)
        for _ in range(4):p.observe(0,2000) # blink-like activity cannot establish baseline
        self.assertTrue(p.retry)
        for _ in range(12):p.observe(0,0)
        self.assertFalse(p.retry)
        self.assertEqual(p.apply('right',.01,3,200)[0],'right')
