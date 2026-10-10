"""Read the Nano test sketch's CSV stream; values remain raw ADC counts."""

import time
from contextlib import ExitStack
from dataclasses import dataclass


@dataclass(frozen=True)
class ADCSample:
    horizontal: int
    vertical: int
    timestamp_ms: int  # Host receipt time, not the MCU sampling time.
    source: str = "nano_r4"
    units: str = "adc_counts"


def parse_adc_line(line: bytes) -> ADCSample | None:
    """Ignore headers, corrupt lines, and values outside the 14-bit range."""
    try:
        fields = line.decode("ascii").strip().split(",")
        if len(fields) != 2 or not all(field.strip().isdigit() for field in fields):
            return None
        horizontal, vertical = map(int, fields)
    except (UnicodeDecodeError, ValueError):
        return None
    if not (0 <= horizontal <= 16383 and 0 <= vertical <= 16383):
        return None
    return ADCSample(horizontal, vertical, time.time_ns() // 1_000_000)


class SerialADCSource:
    """Accumulate partial lines across serial timeouts without unbounded buffers."""

    def __init__(self, connection):
        self.connection = connection
        self.pending = b""
        self.discarding = False
        self.ignored_lines = 0

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
            sample = parse_adc_line(line)
            if sample is not None:
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
