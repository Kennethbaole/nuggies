"""Two distinct positive lobes in an existing 50 Hz waveform window.

Engineering defaults for the current vertical electrode polarity. No model,
cue labels, application state or raw single-sample crossings are used here.
"""
import math


def blink_shape(samples, rate=50):
    if len(samples)<5 or rate<=0 or any(len(x)!=2 or not all(math.isfinite(v) for v in x) for x in samples):
        raise ValueError('Aligned finite two-channel waveform required')
    vertical=[x[1] for x in samples]
    peak=max(vertical)
    threshold=max(800,peak*.25)
    pulses=[];start=None
    for i,value in enumerate(vertical+[0]):
        if value>=threshold:
            if start is None:start=i
        elif start is not None:
            end=i
            k=max(range(start,end),key=vertical.__getitem__)
            amplitude=vertical[k]
            width=sum(vertical[j]>=amplitude*.5 for j in range(start,end))/rate
            # A lobe still above threshold at the window's end is incomplete.
            if amplitude>=1200 and .04<=width<=.24 and end<len(vertical):
                pulses.append((k,amplitude,width,start,end))
            start=None
    result=dict(blink_pulse_count=len(pulses),blink_pair_valid=0,
                blink_pair_gap_ms=0,blink_pair_ratio=0,blink_valley_ratio=0,
                blink_first_width_ms=0,blink_second_width_ms=0)
    if len(pulses)!=2:return result
    first,second=pulses
    gap=(second[0]-first[0])/rate
    ratio=second[1]/first[1]
    valley=min(vertical[first[0]:second[0]+1])/min(first[1],second[1])
    result.update(blink_pair_gap_ms=round(gap*1000),blink_pair_ratio=round(ratio,3),
                  blink_valley_ratio=round(valley,3),blink_first_width_ms=round(first[2]*1000),
                  blink_second_width_ms=round(second[2]*1000),
                  blink_pair_valid=int(.12<=gap<=.65 and .25<=ratio<=2.5 and valley<=.25))
    return result
