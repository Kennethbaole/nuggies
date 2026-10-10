"""Forensic reset search for old logs that omitted detector resets.

This is offline development tooling. It reads the chosen historical Git source
in an isolated module namespace; it does not check out files or change runtime.
Reports contain participant signal data and must stay in an ignored location.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import types

from backend.blink_shape import blink_shape

ROOT = Path(__file__).resolve().parents[1]
MATCH_KEYS = ('label', 'reason', 'candidate', 'onset_sample', 'emitted_sample',
              'distance', 'other_label_margin', 'blink_margin',
              'direction_margin', 'horizontal_fraction')


def historical_detector(ref):
    """Load only detector dependencies from a recorded commit, without mutation."""
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', ref + '^{commit}'],
                                     cwd=ROOT, text=True).strip()
    name = '_eog_forensic_' + commit
    package = types.ModuleType(name)
    package.__path__ = []
    sys.modules[name] = package
    modules = {}
    for part in ('temporal_eog', 'eog_waveform', 'guided_eog'):
        source = subprocess.check_output(['git', 'show', commit + ':backend/' + part + '.py'],
                                         cwd=ROOT, text=True)
        module = types.ModuleType(name + '.' + part)
        module.__package__ = name
        sys.modules[module.__name__] = module
        exec(compile(source, commit + '/backend/' + part + '.py', 'exec'), module.__dict__)
        modules[part] = module
    return commit, modules['guided_eog'].GuidedEOGTest, modules['eog_waveform'].WaveformProfile


def load_rows(path):
    with Path(path).open(newline='') as stream:
        return [(float(r['horizontal_adc']), float(r['vertical_adc']), float(r['timestamp_ms']))
                for r in csv.DictReader(stream)]


def find_resets(rows, profile, detector_type, first, ready_sample):
    """Exhaust every possible last reset; skip impossible frame residues only.

    Without a sample fault, a new filter emits at r+4, r+9, ... . Therefore a
    first Ready at ready_sample requires (ready_sample-r+1) % 5 == 0. If any
    clipping/timestamp reset could realign the filter, test all residues.
    """
    safe = all(all(math.isfinite(v) and 5 < v < 16378 for v in row[:2])
               and (i == first or 0 <= row[2] - rows[i-1][2] <= 500)
               for i, row in enumerate(rows[first:ready_sample+1], first))
    candidates = []
    tested = 0
    for reset in range(first, ready_sample+1):
        if safe and (ready_sample-reset+1) % 5:
            continue
        tested += 1
        detector = detector_type(profile)
        detector.raw_index = reset - 1
        for index in range(reset, ready_sample+1):
            detector.process(*rows[index])
            if detector.phase == 'ready':
                if index == ready_sample:
                    candidates.append(reset)
                break
    return dict(first=first, last=ready_sample, considered=ready_sample-first+1,
                simulated=tested, impossible_residues_skipped=ready_sample-first+1-tested,
                fault_free=safe, ready_candidates=candidates)


def template_distances(profile, samples):
    normalized = [tuple(max(-2, min(2, f[a]/profile.scale[a])) for a in (0, 1))
                  for f in samples]
    distances = []
    for number, (label, wave) in enumerate(zip(profile.labels, profile.waves)):
        distance, shift = min((sum((wave[j+max(0, s)][a]-normalized[j+max(0, -s)][a])**2
                                   for j in range(50-abs(s)) for a in (0, 1)) /
                              (2*(50-abs(s))), s) for s in range(-4, 5, 2))
        distances.append(dict(template_index=number, label=label, distance=distance, shift=shift))
    return sorted(distances, key=lambda item: item['distance'])


def capture(rows, profile, detector_type, reset, until, trace_start):
    detector = detector_type(profile)
    detector.raw_index = reset-1
    original = profile.classify
    windows = []
    trace = []
    frames = {}

    def classify(samples, weight=0):
        result = original(samples, weight)
        distances = template_distances(profile, samples)
        by_label = {}
        for item in distances:
            by_label.setdefault(item['label'], item['distance'])
        windows.append(dict(emitted_sample=detector.raw_index,
                            window_start_sample=detector.raw_index-245,
                            samples=[list(frame) for frame in samples],
                            result=result, blink_shape=blink_shape(samples),
                            per_template_distances=distances,
                            per_label_best_distances=by_label))
        return result

    profile.classify = classify
    try:
        for index in range(reset, until+1):
            frame = detector.frame
            detector.process(*rows[index])
            if detector.frame != frame:
                value = dict(sample_index=index, timestamp_ms=rows[index][2],
                             horizontal_raw=rows[index][0], vertical_raw=rows[index][1],
                             horizontal=detector.horizontal, vertical=detector.vertical,
                             horizontal_adjusted=detector.horizontal-detector.rest_offset[0],
                             vertical_adjusted=detector.vertical-detector.rest_offset[1],
                             filter_baseline=list(detector.filter.baseline),
                             rest_offset=list(detector.rest_offset), phase=detector.phase)
                frames[index] = value
                if index >= trace_start:
                    trace.append(value)
        events = list(detector.events)
        for window in windows:
            emitted = window['emitted_sample']
            event = next(e for e in events if e['emitted_sample'] == emitted)
            window['onset_sample'] = event['onset_sample']
            onset = frames[event['onset_sample']]
            window['filter_baseline_at_onset'] = onset['filter_baseline']
            window['rest_offset_at_onset'] = onset['rest_offset']
        return dict(reset_sample=reset, events=events, windows=windows, trace_50hz=trace)
    finally:
        profile.classify = original


def matches(actual, expected):
    return all(actual.get(key) == value for key, value in expected.items() if key in MATCH_KEYS)


def write_trace(path, trace):
    fields = ['sample_index', 'timestamp_ms', 'horizontal_raw', 'vertical_raw',
              'horizontal_adjusted', 'vertical_adjusted', 'vertical_velocity_counts_s', 'phase']
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        previous = None
        for row in trace:
            values = {k: row[k] for k in fields if k in row}
            values['vertical_velocity_counts_s'] = (None if previous is None else
                50*(row['vertical_adjusted']-previous))
            previous = row['vertical_adjusted']
            writer.writerow(values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', required=True)
    parser.add_argument('--events', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--first-reset', type=int, required=True)
    parser.add_argument('--ready-sample', type=int, required=True)
    parser.add_argument('--until', type=int, required=True)
    parser.add_argument('--target-samples', required=True, help='Comma-separated global event indices')
    parser.add_argument('--trace-start', type=int, required=True)
    parser.add_argument('--code-ref', default='ee76de4')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    output = Path(args.out).resolve()
    if subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT).returncode:
        parser.error('--out must be Git-ignored: reports contain private participant signals')
    rows = load_rows(args.csv)
    if not 0 <= args.first_reset <= args.ready_sample < args.until < len(rows):
        parser.error('Require 0 <= first reset <= ready sample < until < row count')
    commit, detector_type, profile_type = historical_detector(args.code_ref)
    profile = profile_type.load(args.profile)
    targets = [int(s) for s in args.target_samples.split(',')]
    log = [json.loads(line) for line in Path(args.events).read_text().splitlines()]
    expected = {sample: next(record['event'] for record in log if record.get('event')
                             and record['event'].get('emitted_sample') == sample)
                for sample in targets}
    search = find_resets(rows, profile, detector_type, args.first_reset, args.ready_sample)
    replays = []
    for reset in search['ready_candidates']:
        replay = capture(rows, profile, detector_type, reset, args.until, args.trace_start)
        by_sample = {event['emitted_sample']: event for event in replay['events']}
        replay['exact_target_match'] = all(sample in by_sample and matches(by_sample[sample], event)
                                           for sample, event in expected.items())
        replays.append(replay)
    exact = [replay['reset_sample'] for replay in replays if replay['exact_target_match']]
    report = dict(evidence='Historical reused-data development reconstruction, not accuracy',
                  code_commit=commit, profile_sha256=profile.digest,
                  csv_sha256=hashlib.sha256(Path(args.csv).read_bytes()).hexdigest(),
                  search=search, target_events=expected, exact_reset_matches=exact, replays=replays)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    for replay in replays:
        if replay['exact_target_match']:
            write_trace(output.with_name(output.stem+'-trace-'+str(replay['reset_sample'])+'.csv'),
                        replay['trace_50hz'])
    print(json.dumps(dict(search=search, exact_reset_matches=exact, private_report=str(output))))
    if not exact:
        raise SystemExit('No exact reconstruction: do not use approximate matches as a regression.')


if __name__ == '__main__':
    main()
