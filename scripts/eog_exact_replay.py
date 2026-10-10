"""Reproduce detector decisions from a v2 private audit and its matching raw CSV."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from backend.eog_diagnostics import DiagnosticLog, code_identity, restore_checkpoint
from backend.eog_waveform import WaveformProfile
from backend.guided_eog import GuidedConfig, GuidedEOGTest
from backend.recording import CSVReplaySource

CHECKED_KINDS={'decision','reset','component_reset'}


def _comparable(row):
    # Different checkouts can have the same detector source under different commits.
    return {key:value for key,value in row.items()
            if key not in {'sequence','code_commit','detector_source_sha256','profile_sha256'}}


def replay(csv_path,log_path,profile_path,*,allow_code_mismatch=False,csv_start_index=None):
    rows=[json.loads(line) for line in Path(log_path).read_text().splitlines() if line.strip()]
    session=next((row for row in rows if row['kind']=='session'),{})
    if session.get('audit_version')!=2:
        raise ValueError('Exact replay requires a v2 audit: historical logs omit resets and cannot prove exactness')
    profile=WaveformProfile.load(profile_path)
    if profile.digest!=session['profile_sha256']:raise ValueError('Profile digest differs from recorded session')
    if not allow_code_mismatch and code_identity()['detector_source_sha256']!=session['detector_source_sha256']:
        raise ValueError('Detector source differs; use the recorded checkout or explicitly --allow-code-mismatch for development comparison')
    start=next((row for row in rows if row['kind']=='input_start'),None)
    if start is None:raise ValueError('Audit has no raw input checkpoint')
    csv_starts=[row['sample_index'] for row in rows if row['kind']=='recording_start']
    if csv_start_index is None:
        if not csv_starts:raise ValueError('CSV origin is missing; provide --csv-start-index explicitly')
        csv_start_index=csv_starts[0]
    with open(csv_path,newline='',encoding='utf-8') as stream:
        source=CSVReplaySource(stream);samples=[]
        while (sample:=source.read_sample()) is not None:samples.append(sample)
    first=start['sample_index'];last=csv_start_index+len(samples)-1
    stop=next((row for row in rows if row['kind']=='recording_stop'),None)
    if stop:last=min(last,stop['sample_index'])
    end=next((row for row in rows if row['kind']=='input_end'),None)
    if end:last=min(last,end['sample_index'])
    if not csv_start_index<=first<=last:raise ValueError('CSV does not cover the initial detector checkpoint')
    relevant=[row for row in rows if row['sequence']>start['sequence']
              and row.get('sample_index') is not None and first<=row['sample_index']<=last
              and (not stop or row['sequence']<=stop['sequence'])]
    controls={};modes={}
    for row in relevant:
        if row['kind']=='reset' and row['origin']=='external':
            if row['position']!='between_samples':raise ValueError('External reset has unsupported ordering')
            controls.setdefault(row['sample_index'],[]).append(row)
        elif row['kind']=='mode':modes[row['sample_index']]=row['enabled']
    expected=[_comparable(row) for row in relevant if row['kind'] in CHECKED_KINDS]
    detector=GuidedEOGTest(profile,GuidedConfig(**session['settings']))
    restore_checkpoint(detector,start['checkpoint'])
    enabled=start['enabled']
    with tempfile.TemporaryDirectory() as directory:
        actual_path=Path(directory)/'events.jsonl';audit=DiagnosticLog(actual_path,detector)
        # Preserve recorded source identity: source match is checked above, commit
        # names can differ after documentation-only commits.
        audit.identity={key:session[key] for key in audit.identity}
        try:
            for index in range(first,last+1):
                sample=samples[index-csv_start_index]
                if index==first and sample.timestamp_ms!=start['timestamp_ms']:
                    raise ValueError('CSV checkpoint timestamp does not match audit')
                enabled=modes.get(index,enabled)
                audit.before_sample(detector,index,sample.timestamp_ms,enabled)
                if enabled:detector.process(sample.horizontal,sample.vertical,sample.timestamp_ms)
                audit.after_sample()
                for control in controls.get(index,[]):
                    enabled=control['enabled'];audit.boundary(index,control['timestamp_ms'],enabled)
                    if control['cause'].startswith('fault:'):
                        detector.fault(control['cause'][6:],origin='external')
                    else:
                        detector.reset(clear_events=control['clear_events'],cause=control['cause'],origin='external')
        finally:audit.close()
        actual=[_comparable(json.loads(line)) for line in actual_path.read_text().splitlines()
                if json.loads(line)['kind'] in CHECKED_KINDS]
    if actual!=expected:
        for index in range(max(len(actual),len(expected))):
            got=actual[index] if index<len(actual) else None
            wanted=expected[index] if index<len(expected) else None
            if got!=wanted:
                raise AssertionError(f'Replay differs at audit event {index}: expected {wanted!r}; got {got!r}')
    return dict(identical=True,samples=last-first+1,decisions=sum(row['kind']=='decision' for row in actual),
                resets=sum(row['kind']=='reset' for row in actual),
                code_verified=not allow_code_mismatch,
                note='Detector decisions only; no inference about wearer intent, confirmation correctness, or audible output.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv');parser.add_argument('events');parser.add_argument('--profile',required=True)
    parser.add_argument('--csv-start-index',type=int)
    parser.add_argument('--allow-code-mismatch',action='store_true')
    args=parser.parse_args()
    print(json.dumps(replay(args.csv,args.events,args.profile,csv_start_index=args.csv_start_index,
                            allow_code_mismatch=args.allow_code_mismatch),indent=2))


if __name__=='__main__':main()
