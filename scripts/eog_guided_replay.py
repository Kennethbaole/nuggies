"""Replay the exact guided app detector from raw ADC alone; no cue/label files read."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from backend.guided_eog import GuidedEOGTest
from backend.recording import CSVReplaySource


def replay(recording,profile):
    detector=GuidedEOGTest(profile);events=[];transitions=[];last=None;phase=None;count=0
    started=time.perf_counter()
    with Path(recording).open() as stream:
        source=CSVReplaySource(stream)
        while (sample:=source.read_sample()) is not None:
            detector.process(sample.horizontal,sample.vertical,sample.timestamp_ms)
            if detector.last_result is not None and detector.last_result is not last:
                last=detector.last_result;events.append(last)
            if detector.phase!=phase:
                phase=detector.phase;transitions.append(dict(sample=count,phase=phase,reason=detector.reason))
            count+=1
    return dict(samples=count,events=events,transitions=transitions,settings=asdict(detector.config),
                processing_seconds=round(time.perf_counter()-started,3),final=detector.snapshot(),
                note='Raw-only development replay; no sidecars read, no hardware or commands emitted.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('recording');p.add_argument('--profile',required=True)
    p.add_argument('--output',required=True);args=p.parse_args()
    report=replay(args.recording,args.profile)
    with Path(args.output).open('x') as stream:json.dump(report,stream,indent=2)
    print(json.dumps({k:report[k] for k in ('samples','processing_seconds','note')}))
