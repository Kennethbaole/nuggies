"""Private append-only EOG audit logs, including resets and exact replay inputs."""
from collections import deque
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess

AUDIT_VERSION = 2
INDEX_FIELDS = ('onset_sample', 'emitted_sample', 'confirmation_armed_sample', 'window_start_sample')


def code_identity():
    root=Path(__file__).resolve().parents[1]
    try:
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True,stderr=subprocess.DEVNULL,timeout=2).strip()
    except (OSError,subprocess.SubprocessError):commit='unknown'
    files=('guided_eog.py','temporal_eog.py','eog_waveform.py','blink_shape.py','eog_communication.py','app.py')
    source=hashlib.sha256()
    for name in files:
        source.update(name.encode());source.update((root/'backend'/name).read_bytes())
    return dict(code_commit=commit,detector_source_sha256=source.hexdigest())


def _pack(value):
    """JSON-safe state, retaining tuple/deque distinctions needed by the segmenter."""
    if isinstance(value,deque):return {'__deque__':[_pack(x) for x in value],'maxlen':value.maxlen}
    if isinstance(value,tuple):return {'__tuple__':[_pack(x) for x in value]}
    if isinstance(value,list):return [_pack(x) for x in value]
    if isinstance(value,dict):return {key:_pack(item) for key,item in value.items()}
    return value


def _unpack(value):
    if isinstance(value,list):return [_unpack(x) for x in value]
    if isinstance(value,dict):
        if '__deque__' in value:return deque((_unpack(x) for x in value['__deque__']),maxlen=value['maxlen'])
        if '__tuple__' in value:return tuple(_unpack(x) for x in value['__tuple__'])
        return {key:_unpack(item) for key,item in value.items()}
    return value


def detector_checkpoint(detector):
    excluded={'profile','config','filter','detector','audit_observer'}
    return _pack(dict(guided={key:value for key,value in detector.__dict__.items() if key not in excluded},
                      filter=dict(detector.filter.__dict__),
                      segmenter={key:value for key,value in detector.detector.__dict__.items() if key!='config'}))


def restore_checkpoint(detector, checkpoint):
    state=_unpack(deepcopy(checkpoint))
    detector.__dict__.update(state['guided'])
    detector.filter.__dict__.update(state['filter'])
    detector.detector.__dict__.update(state['segmenter'])


def global_event(value, detector_index, global_index):
    value=deepcopy(value)
    if global_index is None:return value
    offset=global_index-detector_index
    for key in INDEX_FIELDS:
        if key in value:value[key]+=offset
    return value


class DiagnosticLog:
    def __init__(self,path,detector):
        self.stream=open(path,'x',encoding='utf-8')
        self.last=None;self.detector=detector;self.sample_index=-1;self.timestamp_ms=None
        self.enabled=False;self.position='between_samples';self.started=False;self.sequence=0
        self.identity=dict(code_identity(),profile_sha256=detector.profile.digest)
        self.write(dict(kind='session',audit_version=AUDIT_VERSION,engine=detector.engine,
                        **self.identity,settings=asdict(detector.config),
                        sample_coordinate='global application input index, zero-based; CSV origin recorded separately',
                        note='Private development audit; detector replay does not establish wearer intent or speech delivery.'))
        detector.audit_observer=self.notice

    def write(self,value):
        self.stream.write(json.dumps(dict(sequence=self.sequence,**value),allow_nan=False)+'\n')
        self.stream.flush();self.sequence+=1

    def boundary(self,sample_index,timestamp_ms=None,enabled=None):
        """A control or polling operation after the last ingested input sample."""
        self.sample_index=sample_index;self.timestamp_ms=timestamp_ms;self.position='between_samples'
        if enabled is not None:self.enabled=enabled

    def before_sample(self,detector,sample_index,timestamp_ms,enabled):
        self.sample_index=sample_index;self.timestamp_ms=timestamp_ms;self.position='sample'
        if not self.started:
            self.started=True
            self.write(dict(kind='input_start',sample_index=sample_index,timestamp_ms=timestamp_ms,
                            enabled=enabled,checkpoint=detector_checkpoint(detector)))
        elif enabled!=self.enabled:
            self.write(dict(kind='mode',sample_index=sample_index,timestamp_ms=timestamp_ms,
                            position='before_sample',enabled=enabled))
        self.enabled=enabled

    def after_sample(self):self.position='between_samples'

    def recording(self,kind,sample_index):
        self.write(dict(kind=kind,sample_index=sample_index))

    def notice(self,detector,notice):
        notice=deepcopy(notice)
        if notice['kind']=='decision':
            notice['event']=global_event(notice['event'],detector.raw_index,self.sample_index)
            diagnostic=notice.get('classification')
            if diagnostic:
                diagnostic=global_event(diagnostic,detector.raw_index,self.sample_index)
                context=diagnostic.get('onset_context')
                if context:context['sample_index']=self.sample_index-detector.raw_index+context.pop('raw_index')
                notice['classification']=diagnostic
            notice.update(self.identity)
        self.write(dict(sample_index=self.sample_index,timestamp_ms=self.timestamp_ms,
                        detector_raw_index=detector.raw_index,enabled=self.enabled,position=self.position,**notice))

    def record(self,detector,sample_index=None,timestamp_ms=None,enabled=True):
        if sample_index is not None:
            self.sample_index=sample_index;self.timestamp_ms=timestamp_ms
        self.enabled=enabled
        state=detector.snapshot();state['enabled']=enabled
        event=state.pop('last_event');state.pop('events')
        signature=(enabled,state['phase'],state['reason'],json.dumps(event,sort_keys=True))
        if signature==self.last:return
        self.last=signature
        if event:event=global_event(event,detector.raw_index,self.sample_index)
        self.write(dict(kind='transition',sample_index=self.sample_index,timestamp_ms=self.timestamp_ms,
                        state=state,event=event))

    def close(self):
        if self.stream.closed:return
        self.write(dict(kind='input_end',sample_index=self.sample_index,timestamp_ms=self.timestamp_ms))
        if getattr(self.detector,'audit_observer',None)==self.notice:self.detector.audit_observer=None
        self.stream.close()
