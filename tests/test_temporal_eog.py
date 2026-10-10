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
