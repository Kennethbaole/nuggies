"""Compare actual confirmation modes on private raw recordings; no speech or hardware."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from backend.eog_waveform import WaveformProfile
from backend.guided_eog import GuidedEOGTest, GuidedConfig
from backend.eog_communication import EOGConfirmation
from backend.ring import RingState


def replay(path, profile, pulse_mode, start=0, until=None):
    detector=GuidedEOGTest(profile,GuidedConfig(pulse_confirmation=pulse_mode))
    detector.raw_index=start-1
    gate=EOGConfirmation(pulse_mode=pulse_mode);ring=RingState();ring.cardinal_layout=True
    with Path(path).open() as f: rows=list(csv.DictReader(f))
    with Path(path).with_suffix('.trials.csv').open() as f: cues=list(csv.DictReader(f))
    events=[];selections=[];last=None;last_pair=None
    for index,row in enumerate(rows):
        if index<start:continue
        if until is not None and index>until:break
        slot=detector.process(float(row['horizontal_adc']),float(row['vertical_adc']),int(row['timestamp_ms']))
        if slot is not None:
            gate.clear();ring.action('focus','offline-replay',slot)
            if ring.selected==slot and ring.slots()[slot]['enabled']:gate.focus(ring,index)
        event=detector.last_result if detector.last_result is not last else None
        selected=gate.update(ring,detector,event)
        if event is not None:
            last=event
            if selected:selections.append(dict(event))
        pair=detector.last_blink_result
        if pulse_mode and pair is not None and pair is not last_pair:
            last_pair=pair;selected=gate.update(ring,detector,pair)
            events.append(dict(pair))
            if selected:selections.append(dict(pair))
    for event in events+selections:
        cue=cues[event['onset_sample']]
        event['cue']={key:cue.get(key) for key in ('phase','intended_label','trial_id','run_id')}
    negative=[e for e in selections if not(e['cue']['phase']=='movement' and e['cue']['intended_label']=='double_blink')]
    return dict(pulse_mode=pulse_mode,recording=str(path),pairs=events,selections=selections,
                selection_phases=dict(Counter(e['cue']['phase'] or 'unlabeled' for e in selections)),
                negative_phase_selections=len(negative),
                intended_confirmation_misses=None,
                note='Unlabeled/negative-phase selections are behavioral risks, not proven wearer intent; acquisition cues did not instruct gaze-confirm sequences.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',required=True)
    p.add_argument('--manifest',default='recordings/reviewed-runs.json');p.add_argument('--output',required=True)
    args=p.parse_args();output=Path(args.output)
    if 'recordings' not in output.resolve().parts:p.error('Private output must be under recordings/')
    entries=json.loads(Path(args.manifest).read_text())
    entries.append(dict(recording='recordings/live-eog-20261010T194946508017Z.csv',start=13778,until=17100))
    reports=[]
    for entry in entries:
        for mode in (False,True):
            report=replay(entry['recording'],WaveformProfile.load(args.profile),mode,entry.get('start',0),entry.get('until'))
            reports.append(report)
            print(Path(entry['recording']).name,mode,report['selection_phases'],flush=True)
    output.write_text(json.dumps(reports,indent=2))


if __name__=='__main__':main()
