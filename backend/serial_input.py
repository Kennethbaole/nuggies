"""Read the Nano test sketch's CSV stream; values remain raw ADC counts."""

import time
from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass


@dataclass(frozen=True)
class ADCSample:
    horizontal: int
    vertical: int
    timestamp_ms: int  # Host receipt time, not the MCU sampling time.
    source: str = "nano_r4"
    units: str = "adc_counts"
    sequence: int | None = None
    device_timestamp_us: int | None = None


def parse_adc_line(line: bytes) -> ADCSample | None:
    """Ignore headers, corrupt lines, and values outside the 14-bit range."""
    try:
        fields = line.decode("ascii").strip().split(",")
        if len(fields) not in (2,4) or not all(field.strip().isdigit() for field in fields):
            return None
        values=list(map(int,fields))
        sequence,device_us=(values[0],values[1]) if len(values)==4 else (None,None)
        horizontal,vertical=values[-2:]
        if sequence is not None and not(0<=sequence<=0xffffffff and 0<=device_us<=0xffffffff):return None
    except (UnicodeDecodeError, ValueError):
        return None
    if not (0 <= horizontal <= 16383 and 0 <= vertical <= 16383):
        return None
    return ADCSample(horizontal, vertical, time.time_ns() // 1_000_000,sequence=sequence,device_timestamp_us=device_us)


class SerialADCSource:
    """Accumulate partial lines across serial timeouts without unbounded buffers."""

    def __init__(self, connection):
        self.connection = connection
        self.pending = b""
        self.discarding = False
        self.ignored_lines = 0
        self.metadata={};self.previous_device=None;self.dropped_samples=0
        self.duplicate_samples=0;self.device_resets=0;self.intervals=deque(maxlen=500)

    def snapshot(self):
        return dict(metadata=dict(self.metadata),ignored_lines=self.ignored_lines,
                    dropped_samples=self.dropped_samples,duplicate_samples=self.duplicate_samples,
                    device_resets=self.device_resets,
                    received_rate_hz=1_000_000*len(self.intervals)/sum(self.intervals) if self.intervals else None)

    def _observe(self,sample):
        if sample.sequence is None:return
        if self.previous_device is not None:
            seq,us=self.previous_device
            delta=(sample.sequence-seq)&0xffffffff
            elapsed=(sample.device_timestamp_us-us)&0xffffffff
            if delta==0:self.duplicate_samples+=1
            elif delta>1_000_000 or not 0<elapsed<10_000_000:
                self.device_resets+=1;self.intervals.clear()
            else:
                self.dropped_samples+=delta-1;self.intervals.append(elapsed)
        self.previous_device=(sample.sequence,sample.device_timestamp_us)


    def read_sample(self, timeout: float = 5.0) -> ADCSample:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = self.connection.read_until(b"\n", size=128)
            if not chunk:
                continue
            self.pending += chunk
            if len(self.pending) > 128:
                self.pending = b""
                self.discarding = True
            if not chunk.endswith(b"\n"):
                continue
            line, self.pending = self.pending, b""
            if self.discarding:
                self.discarding = False
                self.ignored_lines += 1
                continue
            if line.startswith(b'#nuggies-eog-v2,'):
                try:
                    fields=line.decode('ascii').strip().split(',')
                    self.metadata=dict(field.split('=',1) for field in fields[1:])
                    self.metadata['protocol']='nuggies-eog-v2'
                except (UnicodeDecodeError,ValueError):self.ignored_lines+=1
                continue
            sample = parse_adc_line(line)
            if sample is not None:
                self._observe(sample)
                return sample
            self.ignored_lines += 1
        raise TimeoutError("No valid samples for 5 seconds. Check the sketch, port, and Serial Monitor.")


def print_serial_samples(port: str, count: int | None = None, record_path: str | None = None) -> None:
    try:
        import serial
    except ImportError as error:
        raise ValueError("Serial mode needs pyserial: install requirements.txt in .venv.") from error
    try:
        with ExitStack() as stack:
            connection = stack.enter_context(serial.Serial(port, 115200, timeout=0.5, exclusive=True))
            recorder = None
            if record_path:
                from .recording import ADCRecorder

                # Refuse accidental replacement of an earlier recording.
                stream = stack.enter_context(open(record_path, "x", newline="", encoding="utf-8"))
                recorder = ADCRecorder(stream)
            source = SerialADCSource(connection)
            print("timestamp_ms,horizontal_adc,vertical_adc", flush=True)
            received = 0
            while count is None or received < count:
                sample = source.read_sample()
                if recorder is not None:
                    recorder.write(sample)
                print(f"{sample.timestamp_ms},{sample.horizontal},{sample.vertical}", flush=True)
                received += 1
    except serial.SerialException as error:
        raise ValueError(f"Cannot read {port}: {error}. Close Serial Monitor and check USB.") from error
