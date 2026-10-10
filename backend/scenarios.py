"""Repeatable timed engineering signals, not physiological EOG waveforms."""

import argparse
import csv
import random
from pathlib import Path

from .recording import ADCRecorder
from .serial_input import ADCSample

STAGES = [("neutral", 0, 0), ("right", 1200, 0), ("neutral", 0, 0),
          ("left", -1200, 0), ("neutral", 0, 0), ("up", 0, 1200),
          ("down", 0, -1200), ("diagonal", 1200, 1200),
          ("neutral", 0, 0), ("blink_like", 0, 2400), ("neutral", 0, 0)]


def samples(seed=7, rate=100, noise=25, drift=3):
    rng = random.Random(seed)
    if type(rate) is not int or not 1 <= rate <= 1000 or noise < 0 or drift < 0:
        raise ValueError("Rate must be 1–1000 Hz; noise/drift nonnegative")
    for index in range(len(STAGES) * rate):
        label, horizontal, vertical = STAGES[index // rate]
        # A short spike is only a detector test case, not a modeled biological blink.
        if label == "blink_like" and index % rate >= max(1, rate // 10):
            vertical = 0
        counts = [round(8192 + amplitude + drift * index / rate + rng.gauss(0, noise))
                  for amplitude in (horizontal, vertical)]
        yield ADCSample(*(max(0, min(16383, n)) for n in counts),
                        round(index * 1000 / rate), "synthetic_adc"), label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--rate", type=int, default=100)
    args = parser.parse_args()
    output = Path(args.output)
    labels = output.with_suffix(".labels.csv")
    if output.exists() or labels.exists():
        parser.error("Output or label file already exists; choose new filenames")
    with output.open("x", newline="") as stream, labels.open("x", newline="") as label_stream:
        recorder = ADCRecorder(stream)
        writer = csv.writer(label_stream)
        writer.writerow(("timestamp_ms", "intended_label"))
        for sample, label in samples(args.seed, args.rate):
            recorder.write(sample)
            writer.writerow((sample.timestamp_ms, label))


if __name__ == "__main__":
    main()
