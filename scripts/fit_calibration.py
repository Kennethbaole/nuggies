"""Fit an initial calibration from labeled trials, not a validated classifier."""

import argparse
import csv
import statistics

from backend.calibration import Calibration
from backend.recording import CSVReplaySource


def fit(recording, label_path):
    with open(label_path, newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["timestamp_ms", "intended_label"]:
            raise ValueError("Labels need timestamp_ms,intended_label columns")
        labels = {}
        for row in reader:
            tick = int(row["timestamp_ms"])
            if tick in labels:
                raise ValueError("Ambiguous duplicate timestamps in label file")
            labels[tick] = row["intended_label"].lower()
    groups = {label: [] for label in ("neutral", "left", "right", "up", "down")}
    timestamps = []
    with open(recording, newline="") as stream:
        source = CSVReplaySource(stream)
        while (sample := source.read_sample()) is not None:
            timestamps.append(sample.timestamp_ms)
            label = labels.get(sample.timestamp_ms)
            if label in groups:
                groups[label].append(sample)
    if any(len(samples) < 5 for samples in groups.values()):
        raise ValueError("Need at least five samples each for neutral/left/right/up/down")
    def median(label, channel):
        return statistics.median(getattr(sample, channel) for sample in groups[label])
    h0, v0 = median("neutral", "horizontal"), median("neutral", "vertical")
    delta_h = median("right", "horizontal") - median("left", "horizontal")
    delta_v = median("up", "vertical") - median("down", "vertical")
    if abs(delta_h) < 1 or abs(delta_v) < 1:
        raise ValueError("Directional channel separation is too small to fit")
    deltas = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    if not deltas:
        raise ValueError("Need positive timestamp intervals")
    return Calibration(h0, v0, abs(delta_h) / 2, abs(delta_v) / 2,
                       1 if delta_h > 0 else -1, 1 if delta_v > 0 else -1,
                       sample_rate_hz=1000 / statistics.median(deltas))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording")
    parser.add_argument("labels")
    parser.add_argument("output")
    parser.add_argument("--sample-rate", type=float, help="Actual MCU rate; overrides host-receipt estimate")
    args = parser.parse_args()
    try:
        calibration = fit(args.recording, args.labels)
        if args.sample_rate is not None:
            from dataclasses import asdict
            values = asdict(calibration)
            values["sample_rate_hz"] = args.sample_rate
            calibration = Calibration(**values)
        calibration.save(args.output)
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(str(error)) from error
    print("Saved initial median-based calibration. Evaluate on separate trials before enabling sensor actions.")


if __name__ == "__main__":
    main()
