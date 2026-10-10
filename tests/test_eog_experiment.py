import csv
import json
from pathlib import Path
import tempfile
import unittest

from scripts.eog_experiment import load_trials, metrics, trial_fold


class EOGExperimentTests(unittest.TestCase):
    def fixture(self, root):
        path = root/'trial.csv'
        with path.open('w') as raw, path.with_suffix('.trials.csv').open('w') as meta:
            writer=csv.writer(raw);writer.writerow(['timestamp_ms','horizontal_adc','vertical_adc','source','units'])
            labels=csv.writer(meta);labels.writerow(['timestamp_ms','intended_label','trial_id','phase','run_id'])
            for i in range(200):
                writer.writerow([i*100,8192,8192,'fixture','adc_counts'])
                # A skipped class and unreviewed run must never enter training.
                label='up' if i<50 else 'double_blink' if i<100 else 'right'
                phase='prepare' if i<10 else 'movement'
                trial='up-1' if i<50 else 'double-blink-1' if i<100 else 'right-1'
                labels.writerow([i*100,label,trial,phase,'valid' if i<100 else 'invalid'])
        manifest=root/'manifest.json';manifest.write_text(json.dumps([dict(recording=str(path),run_id='valid',labels=['up'])]))
        return path,manifest

    def test_reviewed_run_and_class_allowlist_excludes_skips(self):
        with tempfile.TemporaryDirectory() as folder:
            _,manifest=self.fixture(Path(folder))
            trials=load_trials(manifest,fs=10)
            self.assertEqual(len(trials),1)
            self.assertEqual(trials[0]['label'],'up')
            self.assertEqual(len(trials[0]['samples']),30)
            self.assertEqual(trials[0]['fold'],1)

    def test_rejects_misaligned_labels_and_duplicate_trials(self):
        with tempfile.TemporaryDirectory() as folder:
            path,manifest=self.fixture(Path(folder))
            manifest.write_text(json.dumps(json.loads(manifest.read_text())*2))
            with self.assertRaisesRegex(ValueError,'Duplicate'):load_trials(manifest,fs=10)
            side=path.with_suffix('.trials.csv');side.write_text(side.read_text().replace('100,up','101,up',1))
            with self.assertRaisesRegex(ValueError,'aligned'):load_trials(manifest,fs=10)

    def test_fold_assignment_and_confusion_include_wrong_predictions(self):
        self.assertEqual(trial_fold('double-blink-5'),5)
        with self.assertRaises(ValueError):trial_fold('up-6')
        report=metrics(['up','blink'],['blink','blink'],['up','blink'])
        self.assertEqual(report['accuracy'],.5)
        self.assertEqual(report['confusion'],[[0,1],[0,1]])
