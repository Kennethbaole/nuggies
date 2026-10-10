import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.app import Application
from backend.eog_communication import EOGConfirmation
from backend.ring import RingState
from backend.serial_input import ADCSample
from test_guided_eog import fixture_profile


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.ring=RingState();self.ring.cardinal_layout=True
        self.gate=EOGConfirmation()
        self.detector=SimpleNamespace(phase='recovery',raw_index=1000)
        self.gate.focus(self.ring,1000)

    def ready(self):
        self.detector.phase='ready';self.detector.raw_index=1500
        self.gate.update(self.ring,self.detector)

    def event(self,**kwargs):
        return dict(label='double_blink',reason='blink',onset_sample=1600,
                    distance=.01,other_label_margin=3,horizontal_fraction=.01,**kwargs)

    def test_requires_center_recovery_and_fresh_double_then_consumes(self):
        self.assertFalse(self.gate.update(self.ring,self.detector,self.event()))
        self.ready();self.detector.raw_index=1850
        self.assertTrue(self.gate.update(self.ring,self.detector,self.event()))
        self.assertEqual(self.ring.selection_id,1)
        self.assertFalse(self.gate.update(self.ring,self.detector,self.event()))
        self.assertEqual(self.ring.selection_id,1)

    def test_natural_blink_does_not_select(self):
        self.ready();event=self.event();event['label']='blink'
        self.assertFalse(self.gate.update(self.ring,self.detector,event))
        self.assertIsNotNone(self.gate.target)

    def test_conflicting_or_early_blinks_clear_choice(self):
        for key,value in [('distance',.2),('other_label_margin',1.1),('horizontal_fraction',.8),('onset_sample',1400)]:
            with self.subTest(key=key):
                self.setUp();self.ready();event=self.event();event[key]=value
                self.assertFalse(self.gate.update(self.ring,self.detector,event))
                self.assertIsNone(self.gate.target)

    def test_retry_gap_expiry_or_content_change_invalidates(self):
        for change in ('retry','signal_lost','centering','expiry','suggestions','contact','manual_focus'):
            with self.subTest(change=change):
                self.setUp();self.ready()
                if change in ('retry','signal_lost','centering'):self.detector.phase=change
                elif change=='expiry':self.detector.raw_index=3501
                elif change=='suggestions':self.ring.set_suggestions([dict(id='new',label='New',text='Different reply')])
                elif change=='contact':self.ring.action('contact',value=self.ring.config['contacts'][1]['id'])
                else:self.ring.action('focus',value=2)
                self.assertFalse(self.gate.update(self.ring,self.detector,self.event()))
                self.assertIsNone(self.gate.target)

    def test_cardinal_paging_reaches_all_phrases_without_diagonals(self):
        labels=[]
        while True:
            slots=self.ring.slots()
            self.assertFalse(any(slots[i]['enabled'] for i in (1,3,5,7)))
            labels.extend(s['text'] for s in slots if s['action']=='phrase')
            if not slots[6]['enabled']:break
            self.ring.action('focus',value=6);self.ring.action('select')
        self.assertEqual(labels,[p['text'] for p in self.ring.config['phrases']])

    def test_application_ingest_dispatches_real_detector_event_only_in_opt_in_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.json';path.write_text(json.dumps(fixture_profile()))
            app=Application(source='serial',eog_profile=path)
            app.ingest(ADCSample(8192,8192,1000,'test'))
            app.command(dict(action='eog_communication',value=True,event_id='start'))
            d=app.wheel_detector
            def focus(*args):
                d.phase='recovery';d.raw_index=1000
                d.last_result=dict(label='up',reason='accepted')
                return 0
            with patch.object(d,'process',side_effect=focus):app.ingest(ADCSample(8192,8192,1004,'test'))
            def rest(*args):d.phase='ready';d.raw_index=1500
            with patch.object(d,'process',side_effect=rest):app.ingest(ADCSample(8192,8192,1008,'test'))
            def double(*args):d.raw_index=1850;d.last_result=self.event()
            with patch.object(d,'process',side_effect=double):app.ingest(ADCSample(8192,8192,1012,'test'))
            self.assertEqual(app.ring.selection_id,1)
            self.assertEqual(app.ring.last_source,'eog-communication')
            with patch.object(d,'process',return_value=None):app.ingest(ADCSample(8192,8192,1016,'test'))
            self.assertEqual(app.ring.selection_id,1)
            app.command(dict(action='wheel_test',value=False,event_id='stop'))
            self.assertFalse(app.eog_communication)
            self.assertFalse(app.ring.cardinal_layout)


if __name__=='__main__':unittest.main()
