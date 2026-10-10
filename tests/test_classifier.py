import unittest
from unittest.mock import patch

from backend.classifier import ClassifiedDirectionSource, ThresholdClassifier
from backend.models import Direction, EOGSample
from backend.simulator import KEY_DIRECTIONS, KeyboardSampleSource, simulate_sample


class ClassifierTests(unittest.TestCase):
    def test_all_keyboard_inputs_travel_through_samples(self):
        classifier = ThresholdClassifier()
        for key, expected in KEY_DIRECTIONS.items():
            with self.subTest(key=key):
                sample = simulate_sample(key)
                event = classifier.classify(sample)
                self.assertEqual(event.direction, expected)
                self.assertEqual(event.timestamp_ms, sample.timestamp_ms)
                self.assertEqual(event.source, "synthetic")
        self.assertIsNone(simulate_sample("x"))
        self.assertEqual(classifier.classify(simulate_sample("W")).direction, Direction.UP)

    def test_threshold_and_dominant_axis(self):
        classifier = ThresholdClassifier()
        for horizontal, vertical, expected in [
            (0.49, -0.49, Direction.CENTER),
            (0.5, 0, Direction.RIGHT),
            (-0.5, 0, Direction.LEFT),
            (0, 0.5, Direction.UP),
            (0, -0.5, Direction.DOWN),
            (0.8, -0.9, Direction.DOWN),
            (-0.9, 0.8, Direction.LEFT),
            (1, -1, Direction.CENTER),
        ]:
            with self.subTest(horizontal=horizontal, vertical=vertical):
                self.assertEqual(
                    classifier.classify(EOGSample(horizontal, vertical, 123)).direction,
                    expected,
                )

    def test_polarity(self):
        classifier = ThresholdClassifier(horizontal_polarity=-1, vertical_polarity=-1)
        self.assertEqual(classifier.classify(simulate_sample("d")).direction, Direction.LEFT)
        self.assertEqual(classifier.classify(simulate_sample("w")).direction, Direction.DOWN)

    def test_invalid_configuration_and_samples(self):
        for threshold in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ThresholdClassifier(threshold)
        for kwargs in ({"horizontal_polarity": 0}, {"vertical_polarity": 2}):
            with self.assertRaises(ValueError):
                ThresholdClassifier(**kwargs)
        for horizontal, vertical in ((float("nan"), 0), (0, float("inf"))):
            with self.assertRaises(ValueError):
                ThresholdClassifier().classify(EOGSample(horizontal, vertical, 123))

    def test_source_ignores_unknown_keys_repeats_and_closes(self):
        source = KeyboardSampleSource()
        classified = ClassifiedDirectionSource(source, ThresholdClassifier())
        with patch.object(source, "_read_key", side_effect=["x", "w", "w", "c", "q"]):
            self.assertEqual(classified.read_event().direction, Direction.UP)
            self.assertEqual(classified.read_event().direction, Direction.UP)
            self.assertEqual(classified.read_event().direction, Direction.CENTER)
            self.assertIsNone(classified.read_event())
        for closing_key in ("", "\x04"):
            with patch.object(source, "_read_key", return_value=closing_key):
                self.assertIsNone(classified.read_event())


if __name__ == "__main__":
    unittest.main()
