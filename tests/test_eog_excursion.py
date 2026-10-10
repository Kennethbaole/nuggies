import unittest
from backend.eog_excursion import ExcursionGuard


class ExcursionGuardTests(unittest.TestCase):
    def feed(self, guard, start, values):
        for n, (h,v) in enumerate(values):guard.observe(h,v,start+5*n)
        return start+5*len(values)

    def test_rejected_outbound_survives_quiet_and_delayed_return(self):
        guard=ExcursionGuard()
        end=self.feed(guard,0,[(1800,0)]*4)
        guard.claim('right',0)
        end=self.feed(guard,end,[(0,0)]*400)
        self.assertIsNotNone(guard.return_context('left',end))
        self.assertIsNone(guard.return_context('right',end))
        end=self.feed(guard,end,[(-2000,0)]*5+[(0,0)]*13)
        self.assertIsNone(guard.owner)
        self.assertIsNotNone(guard.return_context('left',end-90))
        self.assertIsNone(guard.return_context('left',end+10))

    def test_return_already_inside_capture_is_still_reserved(self):
        guard=ExcursionGuard()
        self.feed(guard,0,[(2000,0)]*5+[(0,0)]*8+[(-2000,0)]*5+[(0,0)]*13)
        guard.claim('right',0)
        self.assertIsNone(guard.owner)
        self.assertIsNotNone(guard.return_context('left',65))
        self.assertIsNone(guard.return_context('left',200))

    def test_vertical_blink_cannot_release_horizontal_excursion(self):
        guard=ExcursionGuard();end=self.feed(guard,0,[(2000,0)]*4)
        guard.claim('right',0)
        self.feed(guard,end,[(0,3000)]*5+[(0,-2000)]*5+[(0,0)]*30)
        self.assertIsNotNone(guard.owner)
        self.assertIsNotNone(guard.return_context('left',200))

    def test_reset_or_gap_clears_old_ownership(self):
        for fault in ('reset','gap'):
            guard=ExcursionGuard();self.feed(guard,0,[(2000,0)]*4)
            guard.claim('right',0)
            if fault=='reset':guard.reset()
            else:guard.observe(0,0,300)
            self.assertIsNone(guard.return_context('left',400))

    def test_no_claim_without_observed_outbound(self):
        guard=ExcursionGuard();self.feed(guard,0,[(0,0)]*50)
        guard.claim('right',0)
        self.assertIsNone(guard.return_context('left',300))

    def test_recovery_rebound_cannot_start_a_fresh_excursion(self):
        guard=ExcursionGuard()
        for i in range(10):guard.observe(-1000,0,i*5,allow_new=False)
        self.assertIsNone(guard.owner)
        for i in range(10,15):guard.observe(2000,0,i*5,allow_new=True)
        self.assertEqual(guard.owner['direction'],'right')
