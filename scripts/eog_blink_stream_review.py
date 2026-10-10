"""Offline pulse-stream development review; no live commands or intent inference.

Writes participant-derived evidence only under recordings/. Cue labels are read
only for scoring after raw replay. No wearer accuracy claim is made.
"""
import argparse
import csv
import json
from pathlib import Path
from collections import Counter
from backend.blink_stream import BlinkPulseStream
from backend.guided_eog import GuidedEOGTest
from backend.eog_waveform import WaveformProfile


def review(recording, profile, start=0):
    detector = GuidedEOGTest(profile)
    detector.raw_index = start-1
    stream = BlinkPulseStream()
    events, pulses = [], []
    prior = None
    with Path(recording).open() as f:
        for index, row in enumerate(csv.DictReader(f)):
            if index < start: continue
            old_frame = detector.frame
            detector.process(float(row['horizontal_adc']), float(row['vertical_adc']), int(row['timestamp_ms']))
            if detector.frame == old_frame: continue
            if detector.phase in ('centering', 'retry', 'signal_lost'):
                stream.reset(); continue
            event = stream.process(detector.horizontal-detector.rest_offset[0],
                                   detector.vertical-detector.rest_offset[1], index, detector.noise)
            if stream.last_pulse is not None and stream.last_pulse is not prior:
                prior = stream.last_pulse; pulses.append(dict(prior))
            if event:
                # A pulse-anchored window includes both pulses despite navigation cooldown.
                frames = [(h,v) for i,h,v in stream.history if i >= event['onset_sample']-15][:50]
                if len(frames) == 50:
                    event['waveform'] = profile.classify(frames)
                events.append(event)
    return dict(recording=str(recording), start=start, events=events, pulses=pulses)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',required=True);p.add_argument('--manifest',default='recordings/reviewed-runs.json')
    p.add_argument('--output',required=True);p.add_argument('--target',action='store_true')
    args=p.parse_args();output=Path(args.output)
    if 'recordings' not in output.resolve().parts: p.error('Private output must be under recordings/')
    profile=WaveformProfile.load(args.profile);reports=[]
    entries=json.loads(Path(args.manifest).read_text())
    if args.target: entries=[dict(recording='recordings/live-eog-20261010T194946508017Z.csv',start=13778)]
    for entry in entries:
        report=review(entry['recording'],profile,entry.get('start',0))
        sidecar=Path(entry['recording']).with_suffix('.trials.csv')
        if sidecar.exists():
            with sidecar.open() as f: labels=list(csv.DictReader(f))
            for event in report['events']:
                cue=labels[event['onset_sample']]
                event['cue']={k:cue.get(k) for k in ('phase','intended_label','trial_id','run_id')}
        reports.append(report)
        print(Path(entry['recording']).name,'pairs',len(report['events']),
              dict(Counter((e.get('cue',{}).get('phase'),e.get('cue',{}).get('intended_label')) for e in report['events'])))
    output.write_text(json.dumps(dict(note='Reused-data pulse candidates, not confirmations or accuracy.',reports=reports),indent=2))


if __name__=='__main__': main()
