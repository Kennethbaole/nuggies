import unittest

from backend.serial_input import SerialADCSource, parse_adc_line


class FakeConnection:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def read_until(self, expected, size):
        return next(self.chunks)


class SerialInputTests(unittest.TestCase):
    def test_valid_counts_and_metadata(self):
        sample = parse_adc_line(b" 0,16383\r\n")
        self.assertEqual((sample.horizontal, sample.vertical), (0, 16383))
        self.assertEqual(sample.units, "adc_counts")
        self.assertEqual(sample.source, "nano_r4")
        self.assertGreater(sample.timestamp_ms, 0)

    def test_invalid_rows(self):
        for line in (b"horizontal,vertical\n", b"", b"1", b"1,2,3", b"-1,2",
                     b"16384,0", b"1.0,2", b"\xff,2", b"nan,0"):
            with self.subTest(line=line):
                self.assertIsNone(parse_adc_line(line))

    def test_partial_lines_headers_and_overlong_rows(self):
        connection = FakeConnection([
            b"horizontal,vertical\n", b"10", b"350,", b"7\r\n",
            b"9" * 128, b"9\n", b"0,10350\n",
        ])
        source = SerialADCSource(connection)
        first = source.read_sample()
        self.assertEqual((first.horizontal, first.vertical), (10350, 7))
        second = source.read_sample()
        self.assertEqual((second.horizontal, second.vertical), (0, 10350))
        self.assertEqual(source.ignored_lines, 2)

    def test_timeout_is_not_end_of_stream(self):
        source = SerialADCSource(FakeConnection([b"", b"1,2\n"]))
        self.assertEqual(source.read_sample().vertical, 2)
        with self.assertRaises(TimeoutError):
            source.read_sample(timeout=0)
