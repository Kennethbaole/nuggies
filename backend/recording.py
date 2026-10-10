"""Lossless CSV storage of raw samples; no classification or scaling."""

import csv
import time

from .serial_input import ADCSample


FIELDS = ("timestamp_ms", "horizontal_adc", "vertical_adc", "source", "units")


DEVICE_FIELDS=("sequence","device_timestamp_us")


class ADCRecorder:
    def __init__(self, stream, include_device_metadata=False):
        self.include_device_metadata=include_device_metadata
        self.stream = stream
        self.writer = csv.writer(stream)
        self.writer.writerow(FIELDS+DEVICE_FIELDS if include_device_metadata else FIELDS)
        self.stream.flush()

    def write(self, sample: ADCSample) -> None:
        row=(sample.timestamp_ms,sample.horizontal,sample.vertical,sample.source,sample.units)
        if self.include_device_metadata:row+=(sample.sequence,sample.device_timestamp_us)
        self.writer.writerow(row)
        self.stream.flush()


class CSVReplaySource:
    """Preserve original receipt timestamps; optionally pace by their deltas."""

    def __init__(self, stream, realtime: bool = False):
        self.reader = csv.DictReader(stream)
        if self.reader.fieldnames not in (list(FIELDS),list(FIELDS+DEVICE_FIELDS)):
            raise ValueError("Recording must have timestamp_ms,horizontal_adc,vertical_adc,source,units columns")
        self.realtime = realtime
        self.first_timestamp = None
        self.previous_timestamp = None
        self.started = None

    def read_sample(self) -> ADCSample | None:
        row = next(self.reader, None)
        if row is None:
            return None
        try:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("wrong column count")
            sequence=device_us=None
            if 'sequence' in row and (row['sequence'] or row['device_timestamp_us']):
                sequence=int(row['sequence']);device_us=int(row['device_timestamp_us'])
                if not(0<=sequence<=0xffffffff and 0<=device_us<=0xffffffff):raise ValueError('Invalid device metadata')
            timestamp = int(row["timestamp_ms"])
            horizontal = int(row["horizontal_adc"])
            vertical = int(row["vertical_adc"])
            if timestamp < 0 or not (0 <= horizontal <= 16383 and 0 <= vertical <= 16383):
                raise ValueError("invalid timestamp or ADC counts")
            if row["units"] != "adc_counts" or not row["source"]:
                raise ValueError("invalid units or source")
            if self.previous_timestamp is not None and timestamp < self.previous_timestamp:
                raise ValueError("timestamps must not go backwards")
        except (ValueError, TypeError) as error:
            raise ValueError(f"Invalid recording at CSV line {self.reader.line_num}: {error}") from error
        if self.first_timestamp is None:
            self.first_timestamp = timestamp
            self.started = time.monotonic()
        if self.realtime:
            target = self.started + (timestamp - self.first_timestamp) / 1000
            # Short waits keep Ctrl-C responsive even for long recording gaps.
            while (remaining := target - time.monotonic()) > 0:
                time.sleep(min(remaining, 0.1))
        self.previous_timestamp = timestamp
        return ADCSample(horizontal, vertical, timestamp, row["source"], row["units"],sequence,device_us)


def print_replay(path: str, realtime: bool = False, count: int | None = None) -> None:
    with open(path, newline="", encoding="utf-8") as stream:
        source = CSVReplaySource(stream, realtime)
        print("timestamp_ms,horizontal_adc,vertical_adc", flush=True)
        received = 0
        while count is None or received < count:
            sample = source.read_sample()
            if sample is None:
                break
            print(f"{sample.timestamp_ms},{sample.horizontal},{sample.vertical}", flush=True)
            received += 1
