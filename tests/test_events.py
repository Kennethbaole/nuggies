import io
import json
import os
import tempfile
import unittest

from backend.events import Action, DetectorConfig, EOGEventDetector, calibrate_from_neutral, detect_samples, match_events
from backend.recording import CSVReplaySource
from backend.eog_scenarios import SCENARIOS, SignalParams, generate, labels_path_for, write_scenario_csv


class ScenarioTests(unittest.TestCase):
    def test_same_seed_is_reproducible(self):
        self.assertEqual(generate("demo", seed=3), generate("demo", seed=3))

    def test_different_seeds_differ(self):
        self.assertNotEqual(generate("demo", seed=1)[0], generate("demo", seed=2)[0])

    def test_length_and_range(self):
        samples, _ = generate("glances", seed=0)
        self.assertEqual(len(samples), int(SCENARIOS["glances"].duration_s * 250))
        for h, v in samples:
            self.assertTrue(0 <= h <= 16383 and 0 <= v <= 16383)

    def test_labels_are_separate_from_channels(self):
        _, labels = generate("blinks", seed=0)
        self.assertEqual([label["expected"] for label in labels],
                         [None, "SELECT", None, "BACK", "SELECT", None])

    def test_unknown_scenario(self):
        with self.assertRaises(ValueError):
            generate("nope")

    def test_csv_round_trips_through_replay(self):
        samples, _ = generate("glances", seed=0)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "g.csv")
            write_scenario_csv(path, samples)
            with open(path, newline="", encoding="utf-8") as stream:
                source = CSVReplaySource(stream)
                replayed = []
                while (sample := source.read_sample()) is not None:
                    replayed.append((sample.horizontal, sample.vertical))
                    self.assertEqual(sample.source, "synthetic_scenario")
            self.assertEqual(replayed, samples)
            with self.assertRaises(FileExistsError):
                write_scenario_csv(path, samples)


class DetectorTests(unittest.TestCase):
    def evaluate(self, name, seed=0, params=SignalParams(), config=DetectorConfig()):
        samples, labels = generate(name, seed, params)
        return labels, match_events(detect_samples(samples, config), labels)

    def test_neutral_produces_no_events(self):
        for seed in range(5):
            samples, _ = generate("neutral", seed)
            self.assertEqual(detect_samples(samples), [], f"seed {seed}")

    def test_every_scenario_and_seed(self):
        for name in SCENARIOS:
            for seed in range(5):
                labels, result = self.evaluate(name, seed)
                expected = sum(1 for label in labels if label["expected"])
                self.assertEqual(len(result["hits"]), expected, f"{name} seed {seed} misses {result['misses']}")
                self.assertEqual(result["false_events"], [], f"{name} seed {seed}")

    def test_glance_order(self):
        samples, _ = generate("glances", 0)
        actions = [event.action for event in detect_samples(samples)]
        self.assertEqual(actions, [Action.NEXT, Action.PREV, Action.NEXT, Action.NEXT, Action.PREV])

    def test_single_blinks_are_ignored(self):
        samples, _ = generate("blinks", 0)
        actions = [event.action for event in detect_samples(samples)]
        self.assertEqual(actions, [Action.SELECT, Action.BACK, Action.SELECT])

    def test_tolerates_double_drift_and_noise(self):
        for params in (SignalParams(noise_sd=80), SignalParams(drift_amplitude=600), SignalParams(hum_amplitude=90)):
            for name in SCENARIOS:
                labels, result = self.evaluate(name, 1, params)
                expected = sum(1 for label in labels if label["expected"])
                self.assertEqual(len(result["hits"]), expected, f"{params} {name}")
                self.assertEqual(result["false_events"], [], f"{params} {name}")

    def test_polarity_flip_swaps_glances(self):
        samples, _ = generate("glances", 0)
        flipped = detect_samples(samples, DetectorConfig(horizontal_polarity=-1))
        self.assertEqual([event.action for event in flipped][:2], [Action.PREV, Action.NEXT])

    def test_held_gaze_recenters_instead_of_sticking(self):
        detector = EOGEventDetector(DetectorConfig())
        events = []
        for _ in range(500):            # 2 s neutral
            events += detector.process(8192, 8192)
        for _ in range(1500):           # 6 s held far right
            events += detector.process(9692, 8192)
        for _ in range(500):            # back to center: a left move from the new center
            events += detector.process(8192, 8192)
        self.assertEqual([event.action for event in events], [Action.NEXT, Action.PREV])

    def test_no_events_during_warmup(self):
        detector = EOGEventDetector(DetectorConfig())
        events = []
        for _ in range(100):
            events += detector.process(12000, 12000)
        self.assertEqual(events, [])

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            DetectorConfig(glance_threshold=0)
        with self.assertRaises(ValueError):
            DetectorConfig(horizontal_polarity=2)
        with self.assertRaises(ValueError):
            DetectorConfig(short_blink_max_s=1.0, long_blink_s=0.8)

    def test_calibrate_from_neutral(self):
        samples, _ = generate("neutral", 0)
        stats = calibrate_from_neutral(samples)
        for channel in ("horizontal", "vertical"):
            self.assertGreater(stats[channel]["noise_sd"], 0)
            self.assertLess(stats[channel]["suggested_min_threshold"], DetectorConfig.glance_threshold * 3)


if __name__ == "__main__":
    unittest.main()
