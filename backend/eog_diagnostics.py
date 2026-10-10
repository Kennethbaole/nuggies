"""Private, append-only-per-session diagnostic recording; never replace prior logs."""
import json
from dataclasses import asdict


class DiagnosticLog:
    def __init__(self,path,detector):
        self.stream=open(path,'x',encoding='utf-8')
        self.last=None
        self.write(dict(kind='session',engine=detector.engine,profile_sha256=detector.profile.digest,settings=asdict(detector.config),
                        note='Development EOG session; confirmation requires explicit application communication mode.'))

    def write(self,value):
        self.stream.write(json.dumps(value,allow_nan=False)+'\n');self.stream.flush()

    def record(self,detector,sample_index=None,timestamp_ms=None,enabled=True):
        state=detector.snapshot()
        state["enabled"]=enabled
        event=state.pop('last_event')
        state.pop('events')
        signature=(enabled,state['phase'],state['reason'],json.dumps(event,sort_keys=True))
        if signature==self.last:return
        self.last=signature
        if event and sample_index is not None:
            event=dict(event)
            for key in ('onset_sample','emitted_sample'):
                if key in event:event[key]=sample_index-(detector.raw_index-event[key])
        self.write(dict(kind='transition',sample_index=sample_index,timestamp_ms=timestamp_ms,
                        state=state,event=event))

    def close(self):self.stream.close()
