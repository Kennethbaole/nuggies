import unittest
from unittest.mock import patch
from backend.guided import GuidedTrial, protocol


class GuidedTrialTests(unittest.TestCase):
    def test_phase_boundaries_separate_movement_and_return(self):
        trial = GuidedTrial(); trial.start(100)
        self.assertEqual(trial.snapshot(124.999)['trial_id'], 'baseline')
        self.assertEqual(trial.snapshot(125)['phase'], 'prepare')
        self.assertEqual(trial.snapshot(128)['label'], 'left')
        self.assertEqual(trial.snapshot(128)['trial_id'], 'left-1')
        self.assertEqual(trial.snapshot(130)['phase'], 'return')
        self.assertEqual(trial.snapshot(130)['label'], 'neutral')
        self.assertEqual(trial.snapshot(134)['trial_id'], 'right-1')

    def test_complete_stop_restart_and_trial_counts(self):
        steps = protocol()
        for label in ('left', 'right', 'blink'):
            self.assertEqual(sum(s[1] == label for s in steps), 5)
        trial = GuidedTrial(); trial.start(0)
        with self.assertRaises(ValueError): trial.start(1)
        self.assertEqual(trial.snapshot(sum(s[0] for s in steps))['status'], 'complete')
        self.assertEqual(trial.snapshot(999)['label'], 'unlabeled')
        first_id = trial.run_id
        trial.start(1000)
        self.assertNotEqual(trial.run_id, first_id)
        trial.stop()
        self.assertEqual(trial.snapshot(1001)['status'], 'stopped')

    def test_app_requires_recording_and_blocks_manual_labels(self):
        from backend.app import Application
        with patch('backend.app.load_env'), patch('backend.speech.load_env'), patch('backend.suggestions.load_env'):
            app = Application(source='serial')
        with self.assertRaises(ValueError):
            app.command(dict(action='guided_start', event_id='blocked'))
        app.recording = app.connected = True
        app.command(dict(action='guided_start', event_id='start'))
        with self.assertRaises(ValueError):
            app.command(dict(action='label', value='left', event_id='manual'))
        app.command(dict(action='guided_stop', event_id='stop'))
        self.assertEqual(app.trial_label, 'unlabeled')

    def test_guided_phase_is_written_to_both_sidecars(self):
        import csv
        import tempfile
        from pathlib import Path
        from backend.app import Application
        from backend.serial_input import ADCSample
        with patch('backend.app.load_env'), patch('backend.speech.load_env'), patch('backend.suggestions.load_env'):
            app = Application(source='serial')
        app.guided.start(100)
        def read_once():
            app.stop.set()
            return ADCSample(7000, 8000, 1234)
        with tempfile.TemporaryDirectory() as directory, patch('serial.Serial'), patch('backend.serial_input.SerialADCSource') as source, patch('backend.app.time.monotonic', return_value=128):
            source.return_value.read_sample.side_effect = read_once
            output = Path(directory) / 'guided.csv'
            app.run_serial('fake-port', output)
            self.assertEqual(app.error, '')
            with output.with_suffix('.labels.csv').open() as stream:
                labels = list(csv.DictReader(stream))
            with output.with_suffix('.trials.csv').open() as stream:
                trials = list(csv.DictReader(stream))
            self.assertEqual(labels[0]['intended_label'], 'left')
            self.assertEqual(trials[0]['trial_id'], 'left-1')
            self.assertEqual(trials[0]['phase'], 'movement')
            self.assertEqual(trials[0]['timestamp_ms'], labels[0]['timestamp_ms'])
            self.assertFalse(app.recording)
            self.assertEqual(app.guided.status, 'stopped')

    def test_short_diagnostic_check_has_all_movements_and_pauses_between_attempts(self):
        steps=protocol('diagnostic')
        for label in ('left','right','up','down','blink','double_blink'):
            self.assertEqual(sum(s[1]==label for s in steps),2)
        self.assertEqual(sum(s[0] for s in steps),157)
        trial=GuidedTrial();trial.start(100,'diagnostic')
        self.assertEqual(trial.snapshot(115)['phase'],'prepare')
        trial.pause(115,True)
        self.assertTrue(trial.snapshot(130)['paused'])
        self.assertEqual(trial.snapshot(130)['phase'],'prepare')
        trial.pause(130,False)
        self.assertEqual(trial.snapshot(133)['label'],'left')
        trial.stop();self.assertFalse(trial.snapshot(134)['paused'])
