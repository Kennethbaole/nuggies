"""Compare historical and current direction decisions on identical recorded inputs.

Uses v2 reset/control logs, including disabled intervals. Private reports never
claim intended direction or confirmation accuracy. Does not touch the live app.
"""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from backend.eog_diagnostics import _unpack, global_event, restore_checkpoint
from backend.eog_waveform import WaveformProfile
from backend.guided_eog import GuidedConfig, GuidedEOGTest
from scripts.eog_reset_search import historical_detector, MATCH_KEYS


def compare(csv_path, log_path, profile_path, reference='ee76de4'):
    logs=[json.loads(line) for line in Path(log_path).read_text().splitlines()]
    session=logs[0]
    if session.get('audit_version')!=2:raise ValueError('A v2 reset audit is required')
    start=next(r for r in logs if r['kind']=='input_start')
    origin=next(r['sample_index'] for r in logs if r['kind']=='recording_start')
    stop=next((r for r in logs if r['kind']=='recording_stop'),None)
    controls={};modes={}
    for row in logs:
        if row['sequence']<=start['sequence'] or stop and row['sequence']>stop['sequence']:continue
        if row['kind']=='reset' and row['origin']=='external':controls.setdefault(row['sample_index'],[]).append(row)
        if row['kind']=='mode':modes[row['sample_index']]=row['enabled']
    commit,Old,OldProfile=historical_detector(reference)
    profile=WaveformProfile.load(profile_path)
    if profile.digest!=session['profile_sha256']:raise ValueError('Profile digest differs')
    old=Old(OldProfile.load(profile_path))
    new=GuidedEOGTest(profile,GuidedConfig(**session['settings']))
    restore_checkpoint(new,start['checkpoint'])
    checkpoint=_unpack(start['checkpoint'])
    old.__dict__.update(checkpoint['guided']);old.filter.__dict__.update(checkpoint['filter'])
    old.detector.__dict__.update(checkpoint['segmenter'])
    enabled=start['enabled'];prior=[old.last_result,new.last_result]
    events=[[],[]];phases=[Counter(),Counter()];differences=[]
    with Path(csv_path).open() as stream:
        for offset,row in enumerate(csv.DictReader(stream)):
            index=origin+offset
            if index<start['sample_index']:continue
            if stop and index>stop['sample_index']:break
            enabled=modes.get(index,enabled)
            if enabled:
                for which,detector in enumerate((old,new)):
                    detector.process(float(row['horizontal_adc']),float(row['vertical_adc']),int(row['timestamp_ms']))
                    phases[which][detector.phase]+=1
                    if detector.last_result is not prior[which]:
                        prior[which]=detector.last_result
                        if detector.last_result:
                            event=global_event(detector.last_result,detector.raw_index,index)
                            events[which].append({k:event[k] for k in MATCH_KEYS if k in event})
                if old.phase!=new.phase or old.horizontal!=new.horizontal or old.vertical!=new.vertical:
                    differences.append(dict(sample_index=index,old_phase=old.phase,new_phase=new.phase))
            for control in controls.get(index,[]):
                enabled=control['enabled'];cause=control['cause']
                if cause.startswith('fault:'):
                    old.fault(cause[6:]);new.fault(cause[6:])
                else:
                    old.reset(clear_events=control['clear_events'])
                    new.reset(clear_events=control['clear_events'],cause=cause)
    return dict(historical_commit=commit,profile_sha256=profile.digest,
                identical=events[0]==events[1] and not differences,
                events=events,frame_state_differences=differences,
                phase_seconds=[{k:v/250 for k,v in phase.items()} for phase in phases],
                note='Identical recorded samples and resets; compares waveform direction decisions, not confirmation or wearer intent.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv');parser.add_argument('events');parser.add_argument('--profile',required=True)
    parser.add_argument('--reference',default='ee76de4');parser.add_argument('--output',required=True)
    args=parser.parse_args();output=Path(args.output)
    if 'recordings' not in output.resolve().parts:parser.error('Private report must stay under recordings/')
    report=compare(args.csv,args.events,args.profile,args.reference)
    output.write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('events','frame_state_differences')}))
    if not report['identical']:raise SystemExit('Direction behavior differs; inspect private report before deployment')


if __name__=='__main__':main()
