"""Synthetic replay checks; no wearer data or private profile is embedded here."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app import Application
from backend.eog_diagnostics import DiagnosticLog
from backend.recording import ADCRecorder
from backend.serial_input import ADCSample
from scripts.eog_exact_replay import replay
from test_guided_eog import fixture_profile


class ExactReplayTests(unittest.TestCase):
    def make_session(self,directory):
        root=Path(directory);profile=root/'profile.json';profile.write_text(json.dumps(fixture_profile()))
        with patch('backend.app.load_env'),patch('backend.speech.load_env'),patch('backend.suggestions.load_env'):
            app=Application(source='serial',eog_profile=profile)
        csv_path=root/'synthetic.csv';log_path=root/'synthetic.events.jsonl'
        # Nonzero application coordinate exercises reconnect/CSV-origin mapping.
        app.received_samples=700
        app.eog_log=DiagnosticLog(log_path,app.wheel_detector)
        app.eog_log.recording('recording_start',700)
        with csv_path.open('w',newline='') as stream:
            recorder=ADCRecorder(stream)
            for index in range(2900):
                h=8192+(2000 if 1200<=index<1300 else -1300 if 1400<=index<1480 else 0)
                v=8192
                if index==2200:v=16383
                sample=ADCSample(h,v,1000+index*4+(600 if index>=2400 else 0))
                recorder.write(sample);app.ingest(sample)
                if index in (10,20):app.command(dict(action='wheel_test',value=True,event_id=f'on{index}'))
                if index==2000:
                    with patch('backend.app.time.monotonic',return_value=app.last_received+2):app.state()
                if index==2500:app.command(dict(action='wheel_test',value=False,event_id='off'))
                if index==2550:app.command(dict(action='wheel_test',value=True,event_id='resume'))
        app.eog_log.close()
        return csv_path,log_path,profile

    def test_exact_decisions_resets_disabled_periods_and_polling_faults(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path,log_path,profile=self.make_session(directory)
            result=replay(csv_path,log_path,profile)
            self.assertTrue(result['identical']);self.assertGreater(result['decisions'],0)
            rows=[json.loads(line) for line in log_path.read_text().splitlines()]
            causes=[row['cause'] for row in rows if row['kind']=='reset']
            for cause in ('wheel_test_on','wheel_test_off','fault:no_samples','fault:clipping','fault:timestamp_gap'):
                self.assertIn(cause,causes)
            self.assertEqual(causes.count('wheel_test_on'),3)
            decision=next(row for row in rows if row['kind']=='decision')
            diagnostic=decision['classification']
            self.assertEqual(len(diagnostic['window']),50)
            self.assertEqual(set(diagnostic['best_distances']),set(fixture_profile()['labels']))
            self.assertIn('baseline',diagnostic['onset_context'])
            self.assertIn('rest_offset',diagnostic['onset_context'])
            self.assertEqual(len(decision['profile_sha256']),64)
            # Corrupt one logged decision: replay must fail rather than merely
            # report counts or trust the logged classification.
            decision['event']['label']='corrupted'
            log_path.write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
            with self.assertRaises(AssertionError):replay(csv_path,log_path,profile)

    def test_historical_or_wrong_profile_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path,log_path,profile=self.make_session(directory)
            old=Path(directory)/'old.jsonl';old.write_text('{"kind":"session"}\n')
            with self.assertRaisesRegex(ValueError,'historical'):replay(csv_path,old,profile)
            data=json.loads(profile.read_text());data['threshold_h']=801;profile.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'digest'):replay(csv_path,log_path,profile)
