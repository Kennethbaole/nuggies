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
