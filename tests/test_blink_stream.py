import unittest
from backend.blink_stream import BlinkPulseStream


def run(values, gap_at=None):
    stream = BlinkPulseStream()
    events = []
    for i, (h, v) in enumerate(values):
        if gap_at == i: stream.reset()
        event = stream.process(h, v, i*5, (20, 20))
        if event: events.append(event)
    return events


def pulses(centers, size=140, horizontal=0):
    values = [(0., 0.) for _ in range(size)]
    for center in centers:
        for delta, v in [(-3, 0), (-2, 1000), (-1, 2500), (0, 4000),
                         (1, 2800), (2, 1000), (3, -400), (4, -800), (5, -300)]:
            values[center+delta] = (horizontal, v)
    return values


class BlinkPulseTests(unittest.TestCase):
    def test_independent_pair_survives_gaze_segmenter_cooldown(self):
        result = run(pulses([20, 31]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['pulse_pair']['gap_ms'], 220)
        self.assertEqual(result[0]['onset_sample'], 17*5)

    def test_single_and_widely_spaced_blinks_never_pair(self):
        self.assertEqual(run(pulses([20])), [])
        self.assertEqual(run(pulses([20, 80])), [])

    def test_triple_rejects_entire_cluster(self):
        self.assertEqual(run(pulses([20, 31, 45])), [])

    def test_slow_up_and_opposite_return_not_double(self):
        values = [(0, 4000 * .93**i) for i in range(55)]
        values += [(0, -4000 * .93**i) for i in range(55)]
        self.assertEqual(run([(0, 0)]*20 + values), [])

    def test_horizontal_motion_rejects_pair(self):
        self.assertEqual(run(pulses([20, 31], horizontal=3500)), [])

    def test_fault_reset_and_nonfinite_break_pair(self):
        self.assertEqual(run(pulses([20, 31]), gap_at=27), [])
        values = pulses([20, 31]); values[27] = (0, float('nan'))
        self.assertEqual(run(values), [])

    def test_adaptive_noise_floor_rejects_low_snr(self):
        stream = BlinkPulseStream(); events = []
        for i, (h, v) in enumerate(pulses([20, 31])):
            event = stream.process(h, v, i*5, (500, 1000))
            if event: events.append(event)
        self.assertEqual(events, [])

class PulseConfirmationSafetyTests(unittest.TestCase):
    def setUp(self):
        from backend.eog_communication import EOGConfirmation
        from backend.ring import RingState
        from types import SimpleNamespace
        self.gate=EOGConfirmation(pulse_mode=True)
        self.ring=RingState();self.ring.cardinal_layout=True;self.ring.selected=6  # left = first reply
        self.detector=SimpleNamespace(phase='ready',raw_index=1000)

    def arm(self):
        self.gate.focus(self.ring,1000)
        self.gate.update(self.ring,self.detector)
        self.detector.raw_index=1400

    def event(self,onset=1100):
        return dict(label='double_blink',reason='blink',source='pulse_stream',
                    pulse_pair_valid=True,waveform_label='double_blink',distance=.02,
                    direction_margin=5,horizontal_fraction=.02,onset_sample=onset)

    def test_no_choice_early_and_legacy_window_cannot_select(self):
        self.assertFalse(self.gate.update(self.ring,self.detector,self.event()))
        self.arm()
        legacy=self.event();legacy.pop('source')
        self.assertFalse(self.gate.update(self.ring,self.detector,legacy))
        self.assertFalse(self.gate.update(self.ring,self.detector,self.event(900)))
        self.assertEqual(self.ring.selection_id,0)

    def test_pair_during_return_cannot_select(self):
        self.gate.focus(self.ring,1000);self.detector.phase='recovery'
        self.assertFalse(self.gate.update(self.ring,self.detector,self.event()))

    def test_one_confirmation_per_gaze(self):
        self.arm();self.assertTrue(self.gate.update(self.ring,self.detector,self.event()))
        self.assertFalse(self.gate.update(self.ring,self.detector,self.event()))
        self.assertEqual(self.ring.selection_id,1)

    def test_expiry_changed_content_and_fault(self):
        for mode in ('expiry','content','fault'):
            self.setUp();self.arm()
            if mode=='expiry':self.detector.raw_index=4000
            if mode=='content':self.ring.action('focus','manual',2)
            if mode=='fault':self.detector.phase='signal_lost'
            self.assertFalse(self.gate.update(self.ring,self.detector,self.event()))
            self.assertEqual(self.ring.selection_id,0)

    def test_shape_alone_and_up_overlap_do_not_confirm(self):
        for patch in (dict(distance=.12),dict(direction_margin=1.35),dict(pulse_pair_valid=False)):
            self.setUp();self.arm();event=self.event();event.update(patch)
            self.assertFalse(self.gate.update(self.ring,self.detector,event))

    def test_uncertain_pair_can_retry_without_new_gaze_or_extended_expiry(self):
        self.arm();event=self.event();event['direction_margin']=1.3
        self.assertFalse(self.gate.update(self.ring,self.detector,event))
        self.assertIsNotNone(self.gate.target)
        self.assertEqual(self.gate.target[1],1000)
        self.gate.update(self.ring,self.detector)
        self.assertIn('again',self.gate.message)
        self.assertTrue(self.gate.update(self.ring,self.detector,self.event()))
        self.assertEqual(self.ring.selection_id,1)
