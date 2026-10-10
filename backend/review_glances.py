"""Offline paired-glance replay: python -m backend.review_glances recording.csv.

Optional per-sample .trials.csv is used only to report events, never to gate them.
"""
import argparse
import csv
import json
from pathlib import Path
from .paired_glance import PairedGlanceConfig, PairedGlanceDetector
from .recording import CSVReplaySource


def review(path, config):
    path = Path(path)
    sidecar = path.with_suffix('.trials.csv')
    detector = PairedGlanceDetector(config)
    events = []
    with path.open() as stream:
        source = CSVReplaySource(stream)
        labels = []
        if sidecar.exists():
            with sidecar.open() as label_stream: labels = list(csv.DictReader(label_stream))
        count = 0
        while (sample := source.read_sample()) is not None:
            if labels and (count >= len(labels) or labels[count]['timestamp_ms'] != str(sample.timestamp_ms)):
                raise ValueError('Trial metadata is not aligned with raw samples')
            for event in detector.process(sample.horizontal):
                row = dict(sample_index=count, time_s=event.time_s, action=event.action.value)
                if labels:
                    row.update(trial_id=labels[count]['trial_id'], phase=labels[count]['phase'])
                events.append(row)
            count += 1
        if labels and count != len(labels): raise ValueError('Trial metadata has extra rows')
    return dict(samples=count, fs=config.fs, threshold=config.threshold, events=events,
                experimental=True, note='A0 only. Cue labels are not measured event onsets. Validate on independent data before control.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording')
    parser.add_argument('--fs', type=int, default=250)
    parser.add_argument('--threshold', type=float, default=1500)
    parser.add_argument('--polarity', type=int, choices=(-1, 1), default=1)
    args = parser.parse_args()
    try:
        print(json.dumps(review(args.recording, PairedGlanceConfig(fs=args.fs, threshold=args.threshold, polarity=args.polarity)), indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__': main()
