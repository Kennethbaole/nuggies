import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.eog_waveform import WaveformProfile, haar
from backend.guided_eog import GuidedConfig, GuidedEOGTest
from backend.eog_diagnostics import DiagnosticLog
from backend.app import Application
from backend.serial_input import ADCSample
from scripts.eog_hud_bridge import status_text


def fixture_profile():
    labels=['left','right','up','down','blink','double_blink']
    waves=[]
    for label in labels:
        waves.append([[-1 if label=='left' else 1 if label=='right' else 0,
                       1 if label=='up' else -1 if label=='down' else
                       (1 if i<10 else -1 if i<20 else 0) if label=='blink' else
                       (1 if i%25<8 else -1 if i%25<16 else 0) if label=='double_blink' else 0]
                       for i in range(50)])
    return dict(version=1,capture_s=1,threshold_h=800,threshold_v=800,
                scale=[1500,1500],labels=labels,waves=waves)


class GuidedEOGTests(unittest.TestCase):
    def detector(self,**kwargs):
        return GuidedEOGTest(WaveformProfile(fixture_profile()),GuidedConfig(**kwargs))

    def feed(self,d,n=1100,h=8192,v=8192):
        events=[]
        for _ in range(n):
            event=d.process(h,v)
            if event is not None:events.append(event)
        return events

    def result(self,label='left',distance=.01,blink_margin=3,direction_margin=3):
        return dict(label=label,distance=distance,blink_margin=blink_margin,direction_margin=direction_margin,horizontal_fraction=.5)

    def candidate(self,d,result):
        segment=dict(samples=[(0,0)]*50,onset=0,emitted=46)
        with patch.object(d.detector,'process',return_value=segment),patch.object(d.profile,'classify',return_value=result):
            return self.feed(d,5)

    def test_profile_matches_all_labels_without_numpy(self):
        p=fixture_profile();model=WaveformProfile(p)
        for label,wave in zip(p['labels'],p['waves']):
            raw=[[value*1500 for value in frame] for frame in wave]
            result=model.classify(raw)
            self.assertEqual(result['label'],label)
            self.assertEqual(result['distance'],0)
        self.assertEqual(haar([0]*10+[1]*10)[-1],1)
        with self.assertRaises(ValueError):model.classify([(math.nan,0)]*50)

    def test_invalid_profile_fails_closed(self):
        for key,value in [('version',2),('scale',[0,1]),('labels',['up']),('waves',[[[0,0]]]),('threshold_h',math.nan)]:
            profile=fixture_profile();profile[key]=value
            with self.assertRaises(ValueError):WaveformProfile(profile)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.json';path.write_text(json.dumps(fixture_profile()))
            self.assertEqual(len(WaveformProfile.load(path).labels),6)

    def test_guided_center_masks_activity_and_requires_clean_samples(self):
        d=self.detector();self.feed(d,500)
        self.assertEqual(d.phase,'centering')
        self.feed(d,30,v=11000);self.feed(d,30,v=7000)
        self.assertEqual(d.phase,'centering')
        self.feed(d,2000)
        self.assertEqual(d.phase,'ready')
        self.assertIsNone(d.slot)
        self.assertTrue(all(math.isfinite(x) for x in d.noise))

    def test_accepts_cardinals_and_blocks_return(self):
        for label,slot in [('up',0),('right',2),('down',4),('left',6)]:
            d=self.detector();self.feed(d)
            self.assertEqual(self.candidate(d,self.result(label)),[slot])
            self.assertEqual(d.phase,'recovery')
            opposite={'up':'down','down':'up','left':'right','right':'left'}[label]
            self.assertEqual(self.candidate(d,self.result(opposite)),[])
            self.assertEqual(d.last_result['label'],'return')
            self.feed(d,500)
            self.assertEqual(d.phase,'ready')
            self.assertEqual(d.totals['accepted'],1)

    def test_retry_blocks_all_directions_then_rearms(self):
        d=self.detector();self.feed(d)
        self.assertFalse(self.candidate(d,self.result(distance=.2)))
        self.assertEqual(d.phase,'retry')
        self.assertIn('Retry',d.message)
        self.assertFalse(self.candidate(d,self.result('right')))
        self.feed(d,800)
        self.assertEqual(d.phase,'retry')
        self.feed(d,600)
        self.assertEqual(d.phase,'ready')
        self.assertEqual(d.totals['accepted'],0)

    def test_blinks_are_silent_but_bad_blink_match_requires_retry(self):
        d=self.detector();self.feed(d)
        self.assertFalse(self.candidate(d,self.result('blink')))
        self.assertEqual(d.phase,'ready')
        self.assertEqual(d.totals['blinks'],1)
        normal=self.result('blink',distance=.2);normal['horizontal_fraction']=.01
        self.assertFalse(self.candidate(d,normal))
        self.assertEqual(d.phase,'ready')
        self.assertFalse(self.candidate(d,self.result('blink',distance=.2)))
        self.assertEqual(d.phase,'retry')
        self.assertEqual(d.reason,'unrecognized_waveform')

    def test_clipping_gap_and_stale_fault_require_new_center(self):
        d=self.detector();self.feed(d)
        d.process(16383,8192)
        self.assertEqual(d.phase,'signal_lost')
        self.feed(d,20)
        self.assertEqual(d.phase,'centering')
        self.feed(d)
        d.process(8192,8192,1000);d.process(8192,8192,2000)
        self.assertEqual(d.phase,'centering')
        self.assertEqual(d.totals['faults'],2)
        d.fault('no_samples');d.fault('no_samples')
        self.assertEqual(d.totals['faults'],3)
        self.assertTrue(d.snapshot()['needs_retry'])

    def test_bad_settings_and_prolonged_unstable_rest(self):
        for kwargs in [dict(retry_s=0),dict(direction_margin=math.nan),dict(haar_weight=-1)]:
            with self.assertRaises(ValueError):GuidedConfig(**kwargs)
        d=self.detector()
        for i in range(4500):d.process(8000+(i%100)*40,8192)
        self.assertTrue(d.snapshot()['waiting_too_long'])
        self.assertIn('electrode',d.message)

    def test_application_opt_in_and_recenter_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.json';path.write_text(json.dumps(fixture_profile()))
            with patch('backend.app.load_env'),patch('backend.speech.load_env'),patch('backend.suggestions.load_env'):
                app=Application(source='serial',eog_profile=path)
                with self.assertRaises(ValueError):Application(eog_profile=path)
                with self.assertRaises(ValueError):Application(source='serial',eog_profile=path,sensor_actions=True)
            app.ingest(ADCSample(8192,8192,1000))
            app.command(dict(action='wheel_test',value=True,event_id='start'))
            for i in range(1100):app.ingest(ADCSample(8192,8192,1004+i*4))
            self.assertEqual(app.state()['gaze_hover']['phase'],'ready')
            self.assertEqual(app.state()['eog_engine'],'waveform')
            self.assertEqual(app.ring.selection_id,0)
            app.command(dict(action='eog_recenter',event_id='center'))
            self.assertEqual(app.state()['gaze_hover']['phase'],'centering')
            with patch('backend.app.time.monotonic',return_value=app.last_received+2):
                self.assertEqual(app.state()['gaze_hover']['phase'],'signal_lost')
            app.command(dict(action='wheel_test',value=False,event_id='stop'))
            with self.assertRaises(ValueError):app.command(dict(action='eog_recenter',event_id='stopped'))

    def test_oled_adapter_sends_status_only(self):
        base=dict(wheel_test=True,connected=True)
        for phase in ('centering','ready','retry','signal_lost','recovery'):
            text=status_text(dict(base,gaze_hover=dict(phase=phase,direction='left')))
            self.assertLessEqual(len(text),23)
            self.assertNotIn('\n',text)
        self.assertIn('Retry',status_text(dict(base,gaze_hover=dict(phase='retry'))))
        self.assertEqual(status_text(dict(base,connected=False)),'! Signal paused')

    def test_private_log_preserves_prior_runs_and_maps_recording_indices(self):
        d=self.detector();self.feed(d)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.jsonl'
            log=DiagnosticLog(path,d)
            log.record(d,2000,8000)
            log.record(d,2001,8004) # unchanged state does not duplicate transitions
            self.candidate(d,self.result('left'))
            log.record(d,2005,8020)
            log.close()
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows),3)
            self.assertEqual(rows[-1]['event']['emitted_sample'],2005)
            self.assertEqual(rows[-1]['event']['label'],'left')
            with self.assertRaises(FileExistsError):DiagnosticLog(path,d)

    def test_diagnostic_cues_require_ready_and_do_not_drive_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.json';path.write_text(json.dumps(fixture_profile()))
            with patch('backend.app.load_env'),patch('backend.speech.load_env'),patch('backend.suggestions.load_env'):
                app=Application(source='serial',eog_profile=path)
            app.ingest(ADCSample(8192,8192,1000));app.recording=True
            with self.assertRaises(ValueError):app.command(dict(action='guided_start',value='diagnostic',event_id='early'))
            app.command(dict(action='wheel_test',value=True,event_id='start'))
            for i in range(1100):app.ingest(ADCSample(8192,8192,1004+i*4))
            app.command(dict(action='guided_start',value='diagnostic',event_id='check'))
            started=app.guided.started
            with patch('backend.app.time.monotonic',return_value=started+15):
                app.wheel_detector._retry('blink_overlap',None,self.result('up'))
                app.ingest(ADCSample(8192,8192,5404))
                self.assertTrue(app.guided.snapshot(started+30)['paused'])
                self.assertEqual(app.wheel_detector.phase,'retry')
                self.assertEqual(app.ring.selection_id,0)
            app.command(dict(action='eog_recenter',event_id='reset'))
            self.assertEqual(app.guided.status,'stopped')

    def test_launcher_port_selection_does_not_choose_a_random_usb_device(self):
        from types import SimpleNamespace
        from scripts.start_eog_test import choose_port
        def port(device,description='',manufacturer=''):
            return SimpleNamespace(device=device,description=description,manufacturer=manufacturer)
        nano=port('/dev/nano','Arduino Nano R4','Arduino')
        esp=port('/dev/esp','CP210x','Silicon Labs')
        self.assertEqual(choose_port([esp,nano]),'/dev/nano')
        for ports in ([esp],[nano,port('/dev/other','Nano')],[]):
            with self.assertRaises(ValueError):choose_port(ports)

    def test_speed_check_waits_for_center_and_separates_reaction_from_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.json';path.write_text(json.dumps(fixture_profile()))
            with patch('backend.app.load_env'),patch('backend.speech.load_env'),patch('backend.suggestions.load_env'):
                app=Application(source='serial',eog_profile=path)
            app.ingest(ADCSample(8192,8192,1000));app.recording=True
            app.command(dict(action='speed_test',event_id='speed'))
            self.assertEqual(app.pending_eog_check,'speed')
            for i in range(1100):app.ingest(ADCSample(8192,8192,1004+i*4))
            self.assertIsNone(app.pending_eog_check)
            self.assertEqual(app.guided.mode,'speed')
            start=app.guided.started
            app.wheel_detector.last_result=dict(label='up',emitted_sample=100,onset_sample=-130)
            with patch('backend.app.time.monotonic',return_value=start+13.2),patch.object(app.wheel_detector,'process',return_value=0):
                app.ingest(ADCSample(8192,8192,5404))
            result=app.speed_attempts['up-1']
            self.assertTrue(result['correct'])
            self.assertEqual(result['cue_to_detection_ms'],1200)
            self.assertEqual(result['candidate_to_detection_ms'],920)
            self.assertFalse(result['early_candidate'])
            self.assertEqual(app.ring.selection_id,0)
            app.command(dict(action='wheel_test',value=False,event_id='stop-speed'))
            self.assertEqual(app.guided.status,'stopped')
