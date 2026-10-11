import json
import unittest
from unittest.mock import patch
from backend.eog_pipeline import EOGPipeline, validate_event
from backend.eog_waveform import WaveformProfile
from backend.guided_eog import GuidedConfig
from test_guided_eog import fixture_profile


class PipelineTests(unittest.TestCase):
    def pipeline(self):
        p=EOGPipeline(WaveformProfile(fixture_profile()),GuidedConfig(pulse_confirmation=True))
        p.set_choices({0:dict(id='hello-v1',label='Hello',enabled=True)},0)
        return p

    def test_contract_and_transport_free_selection(self):
        p=self.pipeline();d=p.detector
        def focus(*args):
            d.raw_index=100;d.phase='ready';d.last_result=dict(label='up',reason='accepted',onset_sample=80,emitted_sample=100)
            return 0
        with patch.object(d,'process',side_effect=focus):result=p.process(8192,8192,0,sample_index=700,communication=True)
        self.assertEqual(result['events'][0]['type'],'gaze_accepted')
        self.assertEqual(result['events'][0]['decision']['onset_sample'],680)
        def blink(*args):
            d.raw_index=400;d.last_blink_result=dict(label='double_blink',reason='blink',source='pulse_stream',pulse_pair_valid=True,waveform_label='double_blink',onset_sample=200,emitted_sample=400,distance=.02,direction_margin=4,horizontal_fraction=.01)
        with patch.object(d,'process',side_effect=blink):result=p.process(8192,8192,4,sample_index=1000,communication=True)
        selections=[e for e in result['events'] if e['type']=='selection']
        self.assertEqual(len(selections),1);self.assertEqual(selections[0]['choice_id'],'hello-v1')
        for event in result['events']:validate_event(event)
        json.dumps(result,allow_nan=False)
        with patch.object(d,'process',return_value=None):result=p.process(8192,8192,8,communication=True)
        self.assertFalse(any(e['type']=='selection' for e in result['events']))

    def test_context_change_cancels_pending(self):
        p=self.pipeline();p.confirmation.focus_choice('hello-v1',0)
        p.set_choices({0:dict(id='different-v2',label='Different',enabled=True)},0)
        self.assertIsNone(p.confirmation.target)

    def test_fault_cancels_choice_and_is_versioned(self):
        p=self.pipeline();p.confirmation.focus_choice('hello-v1',0);p.fault('no_samples')
        self.assertIsNone(p.confirmation.target)
        self.assertEqual(validate_event(p.pending_events[-1])['type'],'fault')
        with self.assertRaises(ValueError):validate_event(dict(schema_version=99,type='selection'))

    def pair(self,d,index):
        def blink(*args):
            d.raw_index=index;d.phase='ready'
            d.last_blink_result=dict(label='double_blink',reason='blink',source='pulse_stream',pulse_pair_valid=True,waveform_label='double_blink',onset_sample=index-200,emitted_sample=index,distance=.02,direction_margin=4,horizontal_fraction=.01)
        return patch.object(d,'process',side_effect=blink)

    def gaze(self,d,index):
        def focus(*args):
            d.raw_index=index;d.phase='ready';d.last_result=dict(label='up',reason='accepted',onset_sample=index-20,emitted_sample=index)
            return 0
        return patch.object(d,'process',side_effect=focus)

    def test_centred_double_blink_pauses_and_resumes_gaze_choices(self):
        p=self.pipeline();d=p.detector
        with self.pair(d,1000):result=p.process(8192,8192,0,communication=True)
        self.assertTrue(p.paused);self.assertTrue(result['state']['paused'])
        self.assertEqual([e['type'] for e in result['events']],['double_blink','pause'])
        for event in result['events']:validate_event(event)
        with self.gaze(d,1300):result=p.process(8192,8192,4,communication=True)
        self.assertFalse(any(e['type'] in ('gaze_accepted','selection') for e in result['events']))
        self.assertIsNone(p.confirmation.target)
        with self.pair(d,1400):p.process(8192,8192,8,communication=True)
        self.assertTrue(p.paused,'a repeat blink inside the two-second guard must not toggle')
        with self.pair(d,1700):result=p.process(8192,8192,12,communication=True)
        self.assertFalse(p.paused);self.assertFalse(any(e['type']=='selection' for e in result['events']))
        with self.gaze(d,2300):result=p.process(8192,8192,16,communication=True)
        self.assertEqual(result['events'][0]['type'],'gaze_accepted')

    def test_double_blink_with_pending_choice_selects_instead_of_pausing(self):
        p=self.pipeline();d=p.detector
        with self.gaze(d,100):p.process(8192,8192,0,communication=True)
        with self.pair(d,500):result=p.process(8192,8192,4,communication=True)
        self.assertEqual(sum(e['type']=='selection' for e in result['events']),1);self.assertFalse(p.paused)
        with self.pair(d,800):p.process(8192,8192,8,communication=True)
        self.assertFalse(p.paused,'blinking again right after a selection must not pause')

    def test_pause_needs_communication_and_clears_when_it_stops(self):
        p=self.pipeline();d=p.detector
        with self.pair(d,1000):p.process(8192,8192,0,communication=False)
        self.assertFalse(p.paused)
        with self.pair(d,2000):p.process(8192,8192,4,communication=True)
        self.assertTrue(p.paused)
        with patch.object(d,'process',return_value=None):p.process(8192,8192,8,communication=False)
        self.assertFalse(p.paused)

    def test_resume_accepts_window_double_blink_or_loose_pulse_pair_but_pause_stays_strict(self):
        p=self.pipeline();d=p.detector
        def window_double(index,distance=.04):
            def blink(*args):
                d.raw_index=index;d.phase='ready'
                d.last_result=dict(label='double_blink',reason='blink',onset_sample=index-250,emitted_sample=index,distance=distance,direction_margin=1.7,horizontal_fraction=.03)
            return patch.object(d,'process',side_effect=blink)
        with window_double(1000):p.process(8192,8192,0,communication=True)
        self.assertFalse(p.paused,'a window-only double blink must not pause')
        with self.pair(d,2000):p.process(8192,8192,4,communication=True)
        self.assertTrue(p.paused)
        with window_double(3000,distance=.3):p.process(8192,8192,8,communication=True)
        self.assertTrue(p.paused,'a poor window match must not resume')
        with window_double(3600):result=p.process(8192,8192,12,communication=True)
        self.assertFalse(p.paused);self.assertEqual(result['events'][-1]['type'],'pause')
        self.assertFalse(any(e['type']=='selection' for e in result['events']))
        with self.pair(d,5000):p.process(8192,8192,16,communication=True)
        self.assertTrue(p.paused)
        def loose_pair(*args):
            d.raw_index=6000;d.phase='recovery'
            d.last_blink_result=dict(label='double_blink',reason='blink',source='pulse_stream',pulse_pair_valid=True,waveform_label='up',onset_sample=5800,emitted_sample=6000,distance=.058,direction_margin=1.3,horizontal_fraction=.03)
        with patch.object(d,'process',side_effect=loose_pair):p.process(8192,8192,20,communication=True)
        self.assertFalse(p.paused,'a valid pulse pair below the selection margin still resumes')

