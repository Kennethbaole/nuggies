import io
import unittest
from unittest.mock import patch

from backend.recording import ADCRecorder, CSVReplaySource, FIELDS
from backend.serial_input import ADCSample


class RecordingTests(unittest.TestCase):
    def test_roundtrip_preserves_samples(self):
        samples = [ADCSample(0, 10350, 1000), ADCSample(16383, 2, 1100),
                   ADCSample(10, 11, 1100, "bench")]
        stream = io.StringIO()
        recorder = ADCRecorder(stream)
        for sample in samples:
            recorder.write(sample)
        stream.seek(0)
        replay = CSVReplaySource(stream)
        self.assertEqual([replay.read_sample() for _ in samples], samples)
        self.assertIsNone(replay.read_sample())

    def test_realtime_uses_timestamp_deltas(self):
        stream = io.StringIO(",".join(FIELDS) + "\n1000,0,1,nano_r4,adc_counts\n1100,0,2,nano_r4,adc_counts\n")
        with patch("backend.recording.time.monotonic", side_effect=[5.0, 5.0, 5.0, 5.1]), \
             patch("backend.recording.time.sleep") as sleep:
            replay = CSVReplaySource(stream, realtime=True)
            replay.read_sample()
            replay.read_sample()
            self.assertAlmostEqual(sleep.call_args.args[0], 0.1)

    def test_rejects_invalid_rows_with_line_number(self):
        for row in ("1,0,16384,nano_r4,adc_counts", "1,0,1,nano_r4,volts",
                    "1,0,1,,adc_counts", "1,0", "1,0,1,nano_r4,adc_counts,extra"):
            with self.subTest(row=row):
                replay = CSVReplaySource(io.StringIO(",".join(FIELDS) + "\n" + row + "\n"))
                with self.assertRaisesRegex(ValueError, "CSV line 2"):
                    replay.read_sample()

    def test_header_and_timestamp_order(self):
        with self.assertRaises(ValueError):
            CSVReplaySource(io.StringIO("horizontal,vertical\n"))
        replay = CSVReplaySource(io.StringIO(",".join(FIELDS) +
                                 "\n2,0,0,nano_r4,adc_counts\n1,0,0,nano_r4,adc_counts\n"))
        replay.read_sample()
        with self.assertRaisesRegex(ValueError, "go backwards"):
            replay.read_sample()

    def test_device_metadata_roundtrip_and_blank_legacy_metadata(self):
        samples=[ADCSample(10,20,1000,sequence=42,device_timestamp_us=123456),ADCSample(30,40,1004)]
        stream=io.StringIO();recorder=ADCRecorder(stream,include_device_metadata=True)
        for sample in samples:recorder.write(sample)
        stream.seek(0);source=CSVReplaySource(stream)
        self.assertEqual([source.read_sample(),source.read_sample()],samples)
