import csv
import tempfile
import unittest
from pathlib import Path

from backend.recording import ADCRecorder
from backend.scenarios import samples
from scripts.fit_calibration import fit


class CalibrationFitTests(unittest.TestCase):
    def test_labeled_fit_recovers_engineering_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, labels = Path(directory) / "raw.csv", Path(directory) / "labels.csv"
            with raw.open("w", newline="") as stream, labels.open("w", newline="") as label_stream:
                recorder = ADCRecorder(stream)
                writer = csv.writer(label_stream); writer.writerow(("timestamp_ms", "intended_label"))
                for sample, label in samples(rate=20, noise=0, drift=0):
                    recorder.write(sample); writer.writerow((sample.timestamp_ms, label))
            calibration = fit(raw, labels)
            self.assertEqual(calibration.horizontal_baseline, 8192)
            self.assertEqual(calibration.horizontal_scale, 1200)
            self.assertEqual(calibration.vertical_scale, 1200)
            self.assertEqual(calibration.sample_rate_hz, 20)

    def test_bench_data_cannot_guess_a_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            labels = Path(directory) / "labels.csv"
            labels.write_text("timestamp_ms,intended_label\n0,neutral\n")
            with self.assertRaisesRegex(ValueError, "five samples"):
                fit("examples/nano_r4_bench.csv", labels)
