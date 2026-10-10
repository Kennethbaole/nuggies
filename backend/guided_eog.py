"""Opt-in cardinal diagnostic control. Never confirms, speaks or estimates gaze position."""
from collections import deque
from dataclasses import dataclass
import math
import statistics

from .eog_waveform import DIRECTIONS, WaveformProfile
from .temporal_eog import CausalFilter, EventSegmenter, SegmentConfig


@dataclass(frozen=True)
class GuidedConfig:
    center_s: float = 3
    retry_s: float = 5
    direction_margin: float = 1.1
    haar_weight: float = 0
    recovery_s: float = 4
    reject_blinks: bool = True
    blink_horizontal_min: float = .25

    def __post_init__(self):
        if any(not math.isfinite(x) or x <= 0 for x in (self.center_s,self.retry_s,self.direction_margin,self.recovery_s)) or not math.isfinite(self.haar_weight) or self.haar_weight<0:
            raise ValueError('Invalid guided EOG settings')
        if type(self.reject_blinks) is not bool or not math.isfinite(self.blink_horizontal_min) or not 0<=self.blink_horizontal_min<=1:
            raise ValueError('Invalid blink rejection settings')


class GuidedEOGTest:
    engine = 'waveform'

    def __init__(self, profile, config=GuidedConfig()):
        self.profile = profile if isinstance(profile,WaveformProfile) else WaveformProfile.load(profile)
        self.config = config
        self.events = deque(maxlen=64)
        self.raw_index=-1
        self.totals = dict(accepted=0,rejected=0,blinks=0,returns=0,faults=0)
        self.reset()

    def reset(self, clear_events=True):
        self.filter = CausalFilter()
        self.detector = EventSegmenter(SegmentConfig(capture_s=1,
                        threshold_h=self.profile.thresholds[0],threshold_v=self.profile.thresholds[1]))
        self.phase='centering';self.reason='look_center'
        self.message='Look straight ahead. Collecting 3 seconds of clean resting signal; blink normally.'
        self.horizontal=self.vertical=0
        self.slot=None;self.direction=None;self.last_result=None
        self.frame=0;self.previous_timestamp=None
        self.clean=deque(maxlen=max(1,round(max(self.config.center_s,self.config.retry_s)*50)))
        self.rest_offset=(0.,0.);self.noise=(0.,0.)
        self.recent_frames=deque(maxlen=100)
        self.previous_frame=None;self.mask_until=0;self.recovery_started=0;self.return_seen=False;self.return_sample=None
        self.progress=0;self.wait_started=0
        if clear_events:self.events.clear()

    def fault(self, reason):
        if self.phase == 'signal_lost' and self.reason == reason:return
        self.reset(clear_events=False);self.totals['faults']+=1
        self.phase='signal_lost';self.reason=reason
        self.message='Signal interrupted. Check the connection, then look straight ahead to recenter.'

    def snapshot(self):
        result=self.last_result
        return dict(engine=self.engine,phase=self.phase,reason=self.reason,message=self.message,
                    slot=self.slot,direction=self.direction,horizontal=round(self.horizontal),vertical=round(self.vertical),
                    progress=round(self.progress,2),noise=[round(x,1) for x in self.noise],
                    last_event=result,events=list(self.events),totals=dict(self.totals),
                    needs_retry=self.phase in ('retry','signal_lost'),
                    waiting_too_long=self.frame-self.wait_started>15*50 and self.phase in ('centering','retry'))

    def _event(self,label,reason,segment=None,result=None):
        event=dict(label=label,reason=reason,emitted_sample=self.raw_index)
        if segment:event['onset_sample']=self.raw_index-(segment['emitted']-segment['onset'])*5
        if result:
            event.update({k:round(v,6) for k,v in result.items() if k!='label' and math.isfinite(v)})
            event['candidate']=result['label']
        self.last_result=event;self.events.append(event)
        return event

    def _clean_frame(self,value):
        step=max(abs(a-b) for a,b in zip(value,self.previous_frame)) if self.previous_frame else 0
        self.previous_frame=value
        if max(map(abs,value))>400 or step>100:self.mask_until=self.frame+25
        if self.frame>=50 and self.frame>=self.mask_until:self.clean.append((self.frame,value))
        duration=self.config.retry_s if self.phase=='retry' else self.config.center_s
        while self.clean and self.frame-self.clean[0][0]>duration*100:self.clean.popleft()
        needed=round(duration*50)
        self.progress=min(1,len(self.clean)/needed)
        return len(self.clean)>=needed

    def _retry(self,reason,segment,result):
        self.totals['rejected']+=1;self.phase='retry';self.reason=reason;self.slot=None
        self.clean.clear();self.wait_started=self.frame;self.progress=0
        self.message='Look center / Retry. Reading uncertain; waiting for clean resting signal.'
        self._event('unknown',reason,segment,result)

    def process(self,h,v,timestamp_ms=None):
        if timestamp_ms is not None:
            if self.previous_timestamp is not None and (timestamp_ms<self.previous_timestamp or timestamp_ms-self.previous_timestamp>500):
                self.fault('timestamp_gap')
            self.previous_timestamp=timestamp_ms
        self.raw_index+=1
        if not all(math.isfinite(x) and 5<x<16378 for x in (h,v)):
            self.fault('clipping');return None
        if self.phase=='signal_lost':
            self.phase='centering';self.reason='look_center'
            self.message='Signal restored. Look straight ahead while center is checked.'
        value=self.filter.process(h,v)
        if value is None:return None
        self.frame+=1
        self.horizontal,self.vertical=value
        self.recent_frames.append((self.raw_index,*value))
        settled=self._clean_frame(value)
        if self.phase in ('centering','retry'):
            if settled:
                # Robust resting residual/noise, separate from continuous DC removal.
                self.rest_offset=tuple(statistics.median(x[1][i] for x in self.clean) for i in (0,1))
                self.noise=tuple(1.4826*statistics.median(abs(x[1][i]-self.rest_offset[i]) for x in self.clean) for i in (0,1))
                self.phase='ready';self.reason='ready';self.slot=None;self.direction=None
                self.detector.reset();self.clean.clear();self.progress=1
                self.message='Ready. Look left, right, up or down, then return to center. Speech stays off.'
            elif self.frame-self.wait_started>15*50:
                self.message='Still waiting for clean rest. Look straight ahead; check electrode contact or choose Recenter.'
            return None
        adjusted=tuple(value[i]-self.rest_offset[i] for i in (0,1))
        if self.phase=='ready' and settled and self.detector.candidate is None:
            center=tuple(statistics.median(x[1][i] for x in self.clean) for i in (0,1))
            self.rest_offset=tuple(self.rest_offset[i]+max(-.5,min(.5,.01*(center[i]-self.rest_offset[i]))) for i in (0,1))
        segment=self.detector.process(*adjusted)
        if self.phase=='recovery' and (self.return_seen or self.frame-self.recovery_started>=round(self.config.recovery_s*50)):
            recent=[x for x in self.clean if x[0]>=self.frame-20]
            if len(recent)>=15:
                self.phase='ready';self.reason='ready';self.slot=None;self.direction=None
                self.detector.reset();self.clean.clear()
                self.message='Ready for the next direction.'
                return None
        if not segment:return None
        result=self.profile.classify(segment['samples'],self.config.haar_weight)
        label=result['label']
        self.detector.ready_at=self.detector.index+round((.15 if label not in DIRECTIONS else .4)*50)
        if label not in DIRECTIONS:
            if self.config.reject_blinks and self.phase=='ready' and result['distance']>.08 and result['horizontal_fraction']>=self.config.blink_horizontal_min:
                self._retry('unrecognized_waveform',segment,result)
                return None
            self.totals['blinks']+=1;self.mask_until=self.frame+25;self.clean.clear()
            self._event(label,'blink',segment,result)
            return None
        if self.phase=='recovery':
            opposite={'left':'right','right':'left','up':'down','down':'up'}
            if label==opposite.get(self.direction):
                self.return_seen=True
                if self.return_sample is None:self.return_sample=self.raw_index-(segment['emitted']-segment['onset'])*5
            self.totals['returns']+=1
            self._event('return','recovering',segment,result)
            return None
        reason=('distant_match' if result['distance']>.08 else
                'blink_overlap' if result['blink_margin']<1.5 else
                'direction_overlap' if result['direction_margin']<self.config.direction_margin else None)
        if reason:
            self._retry(reason,segment,result)
            return None
        self.phase='recovery';self.reason='return_center';self.direction=label;self.slot=DIRECTIONS[label]
        self.recovery_started=self.frame;self.return_seen=False;self.return_sample=None;self.clean.clear()
        self.totals['accepted']+=1
        self.message=f'{label.capitalize()} detected. Return to center before the next direction.'
        self._event(label,'accepted',segment,result)
        return self.slot
