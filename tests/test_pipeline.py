import unittest

from backend.calibration import Calibration, ExponentialSmoother
from backend.scenarios import samples
from backend.serial_input import ADCSample
from backend.state_machine import DoubleBlinkGate, GestureGate


class PipelineTests(unittest.TestCase):
    def test_explicit_normalization_and_polarity(self):
        calibration = Calibration(8000, 9000, 1000, 500, -1, 1)
        sample = calibration.normalize(ADCSample(9000, 8500, 123))
        self.assertEqual((sample.horizontal, sample.vertical), (-1, -1))
        self.assertEqual(sample.timestamp_ms, 123)
        self.assertEqual(sample.source, "nano_r4")
        for kwargs in ({"horizontal_scale": 0}, {"vertical_polarity": 0}, {"threshold": float("nan")}):
            values = dict(horizontal_baseline=0, vertical_baseline=0, horizontal_scale=1, vertical_scale=1)
            values.update(kwargs)
            with self.assertRaises(ValueError):
                Calibration(**values)

    def test_smoothing_and_nyquist_validation(self):
        smoother = ExponentialSmoother(100, 8)
        calibration = Calibration(0, 0, 1, 1)
        smoother.apply(calibration.normalize(ADCSample(0, 0, 0)))
        output = smoother.apply(calibration.normalize(ADCSample(100, 100, 10)))
        self.assertTrue(0 < output.horizontal < 100)
        with self.assertRaises(ValueError):
            ExponentialSmoother(10, 8)

    def test_held_glance_only_advances_once_until_neutral(self):
        gate = GestureGate()
        self.assertIsNone(gate.update("RIGHT", 0))
        self.assertEqual(gate.update("RIGHT", 100), "right")
        for tick in (200, 300, 400, 500):
            self.assertIsNone(gate.update("RIGHT", tick))
        gate.update("CENTER", 600)
        gate.update("LEFT", 700)
        self.assertEqual(gate.update("LEFT", 800), "left")

    def test_stale_input_needs_observed_neutral(self):
        gate = GestureGate()
        gate.update("RIGHT", 0)
        self.assertIsNone(gate.update("RIGHT", 2000))
        self.assertIsNone(gate.update("RIGHT", 2200))
        gate.update("CENTER", 2300)
        gate.update("RIGHT", 2400)
        self.assertEqual(gate.update("RIGHT", 2500), "right")

    def test_discrete_double_blink_timing_and_cooldown(self):
        gate = DoubleBlinkGate()
        self.assertIsNone(gate.update(0))
        self.assertIsNone(gate.update(20))
        self.assertEqual(gate.update(200), "select")
        self.assertIsNone(gate.update(300))
        self.assertIsNone(gate.update(1200))
        self.assertEqual(gate.update(1400), "select")

    def test_scenario_reproducibility_and_labels(self):
        a, b = list(samples(seed=7, rate=10)), list(samples(seed=7, rate=10))
        self.assertEqual(a, b)
        self.assertEqual(len(a), 110)
        self.assertNotEqual(a, list(samples(seed=8, rate=10)))
        self.assertIn("blink_like", {label for _, label in a})
        self.assertTrue(all(0 <= s.horizontal <= 16383 and s.units == "adc_counts" for s, _ in a))
        self.assertEqual(a[1][0].timestamp_ms - a[0][0].timestamp_ms, 100)
