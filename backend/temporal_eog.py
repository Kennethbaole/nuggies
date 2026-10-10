"""Causal offline event segmentation; no cue labels and no application commands."""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SegmentConfig:
    rate: int = 50
    threshold_h: float = 800
    threshold_v: float = 800
    capture_s: float = .8
    refractory_s: float = 2.5
    warmup_s: float = 1

    def __post_init__(self):
        if any(not math.isfinite(x) or x <= 0 for x in self.__dict__.values()):
            raise ValueError('Segmentation settings must be finite and positive')


class CausalFilter:
    """250 Hz raw -> 50 Hz, 60 ms smoothing and a continuously adapting DC estimate."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.window = deque(maxlen=15)
        self.baseline = None
        self.count = 0

    def process(self, h, v):
        if not all(math.isfinite(x) and 5 < x < 16378 for x in (h,v)):
            self.reset()
            return None
        self.window.append((h,v)); self.count += 1
        fast = tuple(sum(s[i] for s in self.window)/len(self.window) for i in (0,1))
        if self.baseline is None:self.baseline=fast
        delta = tuple(fast[i]-self.baseline[i] for i in (0,1))
        self.baseline = tuple(self.baseline[i]+.004*delta[i] for i in (0,1))
        return delta if self.count % 5 == 0 else None


class EventSegmenter:
    """Collect fixed windows after consistent threshold activity; recovery is bounded."""
    def __init__(self, config=SegmentConfig()):
        self.config=config
        self.reset()

    def reset(self):
        self.index=-1;self.history=deque(maxlen=5)
        self.candidate=None;self.active=0;self.sign=None
        self.ready_at=round(self.config.warmup_s*self.config.rate)

    def process(self, h, v):
        self.index+=1
        self.history.append((h,v))
        if not all(math.isfinite(x) for x in (h,v)):
            self.reset();return None
        if self.candidate is not None:
            self.candidate['samples'].append((h,v))
            if len(self.candidate['samples']) >= round(self.config.capture_s*self.config.rate):
                result=self.candidate;result['emitted']=self.index
                self.candidate=None;self.active=0;self.sign=None
                self.ready_at=self.index+round(self.config.refractory_s*self.config.rate)
                return result
            return None
        if self.index < self.ready_at:return None
        normalized=(h/self.config.threshold_h,v/self.config.threshold_v)
        axis=max(range(2),key=lambda i:abs(normalized[i]))
        sign=(axis,1 if normalized[axis]>0 else -1)
        if abs(normalized[axis])>=1:
            self.active=self.active+1 if sign==self.sign else 1
            self.sign=sign
        else:self.active=0;self.sign=None
        if self.active>=2:
            self.candidate=dict(onset=self.index-1,samples=list(self.history))
        return None


class DecisionPolicy:
    """Separate blink recovery, opposite-return suppression and optional rejection."""
    def __init__(self, reject=False, rate=50):
        self.reject=reject;self.rate=rate
        self.reset()

    def reset(self):
        self.direction=None;self.emitted=-99999

    def apply(self,label,distance,margin,index):
        directions={'left','right','up','down'}
        cooldown=round((.4 if label in directions else .15)*self.rate)
        if not math.isfinite(distance) or not math.isfinite(margin):return 'unknown',cooldown
        if label in directions:
            opposite={'left':'right','right':'left','up':'down','down':'up'}
            if label==opposite.get(self.direction) and index-self.emitted<4*self.rate:
                return 'return',cooldown
            if self.reject and (distance>.08 or margin<1.5):return 'unknown',cooldown
            self.direction=label;self.emitted=index
        return label,cooldown


class PairedDirectionDetector:
    """Timing baseline: a direction requires an opposite return, not an isolated pulse."""
    def __init__(self, rate=50, threshold=800, min_return_s=.7):
        self.rate=rate;self.threshold=threshold;self.min_return=round(min_return_s*rate)
        self.reset()

    def reset(self):
        self.index=-1;self.phase='warmup';self.started=0;self.axis=0;self.sign=0
        self.active=0;self.quiet=0;self.peak=0

    def process(self,h,v):
        self.index+=1;values=(h,v)
        if not all(math.isfinite(x) for x in values):self.reset();return None
        if self.phase=='warmup':
            if self.index-self.started>=self.rate:self.phase='idle'
        elif self.phase=='idle':
            axis=max(range(2),key=lambda a:abs(values[a]))
            if abs(values[axis])>=self.threshold:
                self.axis=axis;self.sign=1 if values[axis]>0 else -1
                self.started=self.index;self.phase='outbound';self.peak=abs(values[axis]);self.active=1
        else:
            delta=values[self.axis]*self.sign;age=self.index-self.started
            if age>5*self.rate:
                self.phase='idle';self.active=0;return None
            if self.phase=='outbound':
                self.peak=max(self.peak,delta)
                if delta>=self.threshold:self.active+=1
                if delta<self.threshold*.35:
                    if self.active<2:self.phase='idle'
                    else:self.phase='return'
            elif self.phase=='return':
                if delta < -self.threshold:
                    if age<self.min_return:
                        # Fast opposite lobe: blink/rebound, not a held glance/return.
                        self.phase='cooldown';self.quiet=0
                    else:self.phase='settle';self.quiet=0
            elif self.phase=='settle':
                self.quiet=self.quiet+1 if abs(delta)<self.threshold*.5 else 0
                if self.quiet>=round(.2*self.rate):
                    label={ (0,-1):'left',(0,1):'right',(1,1):'up',(1,-1):'down'}[(self.axis,self.sign)]
                    event=dict(onset=self.started,emitted=self.index,label=label)
                    self.phase='cooldown';self.quiet=0
                    return event
            elif self.phase=='cooldown':
                self.quiet+=1
                if self.quiet>=round(.3*self.rate):self.phase='idle'
        return None
