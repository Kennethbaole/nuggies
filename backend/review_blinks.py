"""Offline double-blink candidate replay; labels report context, never drive detection.

python -m backend.review_blinks recordings/trial.csv > recordings/blinks.json
"""
import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
from .double_blink import DoubleBlinkConfig, DoubleBlinkDetector
from .recording import CSVReplaySource


def review(path, config=DoubleBlinkConfig()):
    path = Path(path)
    metadata = None
    if path.with_suffix('.trials.csv').exists():
        with path.with_suffix('.trials.csv').open() as stream:
            metadata = list(csv.DictReader(stream))
        if any(not {'timestamp_ms', 'intended_label', 'trial_id', 'phase'}.issubset(row) for row in metadata):
            raise ValueError('Trial metadata lacks required columns')
    detector = DoubleBlinkDetector(config)
    events = []
    count = 0
    with path.open() as stream:
        source = CSVReplaySource(stream)
        while (sample := source.read_sample()) is not None:
            if metadata is not None and (count >= len(metadata) or metadata[count]['timestamp_ms'] != str(sample.timestamp_ms)):
                raise ValueError('Metadata does not align with raw samples')
            for event in detector.process(sample.horizontal, sample.vertical):
                item = dict(sample_index=count, time_s=event.time_s, action=event.action.value, features=dict(detector.last_pair_features))
                if metadata is not None:
                    item.update({key: metadata[count].get(key, '') for key in ('run_id', 'trial_id', 'phase', 'intended_label')})
                events.append(item)
            count += 1
    if metadata is not None and count != len(metadata):
        raise ValueError('Metadata contains extra rows')
    return dict(samples=count, config=asdict(config), events=events, experimental=True,
                note='SELECT candidates only; no live commands. Labels describe cues, not measured onsets or verified intent. Development recordings are not held-out validation.')


def score_windows(report, windows):
    """Score explicitly reviewed nonoverlapping intervals; everything else is unknown."""
    ordered = sorted(windows, key=lambda w: w['start_sample'])
    previous_end = 0
    for window in ordered:
        a, b = window['start_sample'], window['end_sample']
        if (type(a) is not int or type(b) is not int or a < previous_end or b <= a
                or b > report['samples'] or window.get('expected') not in (None, 'SELECT')):
            raise ValueError('Invalid or overlapping evaluation windows')
        previous_end = b
    scored = []
    scored_event_indices = set()
    for window in ordered:
        candidates = []
        for index, event in enumerate(report['events']):
            if window['start_sample'] <= event['sample_index'] < window['end_sample']:
                candidates.append(event)
                scored_event_indices.add(index)
        expected = window.get('expected') == 'SELECT'
        scored.append(dict(**window, candidate_count=len(candidates),
                           hit=expected and len(candidates) >= 1,
                           missed=expected and not candidates,
                           duplicates=max(0,len(candidates)-1) if expected else 0,
                           false_candidates=len(candidates) if not expected else 0))
    return dict(expected_pairs=sum(w.get('expected')=='SELECT' for w in ordered),
                hit_windows=sum(w['hit'] for w in scored),
                missed_windows=sum(w['missed'] for w in scored),
                duplicates=sum(w['duplicates'] for w in scored),
                false_candidates=sum(w['false_candidates'] for w in scored),
                negative_exposure_s=sum((w['end_sample']-w['start_sample'])/report['config']['fs'] for w in ordered if w.get('expected') is None),
                unscored_candidates=len(report['events'])-len(scored_event_indices), windows=scored,
                note='Cue-based window scoring, not precise event-onset accuracy or intent verification.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording')
    parser.add_argument('--windows', help='Local JSON list of reviewed start_sample/end_sample/expected windows')
    parser.add_argument('--fs', type=int, default=250)
    parser.add_argument('--threshold', type=float, default=1200)
    parser.add_argument('--vertical-polarity', type=int, choices=(-1, 1), default=1)
    args = parser.parse_args()
    try:
        report = review(args.recording, DoubleBlinkConfig(fs=args.fs, threshold=args.threshold, vertical_polarity=args.vertical_polarity))
        if args.windows:
            with open(args.windows) as stream: windows = json.load(stream)
            report['evaluation'] = score_windows(report, windows)
        print(json.dumps(report, indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
