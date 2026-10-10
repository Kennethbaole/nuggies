"""Replay a frozen development waveform profile without any cue/label files.

Never connects to the wheel, serial device, speech or other services.
"""
import argparse
import json
from pathlib import Path

from backend.recording import CSVReplaySource
from backend.temporal_eog import CausalFilter, DecisionPolicy, EventSegmenter, SegmentConfig
from scripts.eog_stream_experiment import classify


def replay(recording,profile):
    import numpy as np
    p=json.loads(Path(profile).read_text())
    if p.get('version')!=1:raise ValueError('Unsupported profile version')
    waves=np.asarray(p['waves'],dtype=float);scale=np.asarray(p['scale'],dtype=float)
    if waves.ndim!=3 or waves.shape[1:]!=(50,2) or len(p['labels'])!=len(waves) or scale.shape!=(2,) or not np.all(np.isfinite(waves)) or not np.all(np.isfinite(scale)) or np.any(scale<=0):
        raise ValueError('Invalid profile arrays')
    model=dict(waves=waves,scale=scale,labels=p['labels'])
    filt=CausalFilter();detector=EventSegmenter(SegmentConfig(capture_s=1,threshold_h=p['threshold_h'],threshold_v=p['threshold_v']))
    policy=DecisionPolicy(reject=p['reject']);frames=[];events=[];previous=None
    with Path(recording).open() as stream:
        source=CSVReplaySource(stream);count=0
        while (sample:=source.read_sample()) is not None:
            if previous is not None and sample.timestamp_ms-previous>500 or not (5<sample.horizontal<16378 and 5<sample.vertical<16378):
                filt.reset();detector.reset();policy.reset()
            previous=sample.timestamp_ms
            value=filt.process(sample.horizontal,sample.vertical)
            if value is not None:
                frames.append(count)
                event=detector.process(*value)
                if event:
                    label,distance,margin=classify(event['samples'],model,'waveform')
                    label,cooldown=policy.apply(label,distance,margin,len(frames)-1)
                    detector.ready_at=detector.index+cooldown
                    delta=event['emitted']-event['onset']
                    events.append(dict(onset_sample=frames[max(0,len(frames)-1-delta)],emitted_sample=count,
                                       label=label,distance=distance))
            count+=1
    return dict(samples=count,events=events,note='Development replay only; no cue files read, no actions emitted.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('recording');p.add_argument('--profile',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();Path(args.output).write_text(json.dumps(replay(args.recording,args.profile),indent=2))
