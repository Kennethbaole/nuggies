"""Offline, reproducible EOG signal comparisons; never starts hardware or speech.

Optional NumPy is imported only when running the experiment. Runtime modules stay
pure Python. Outputs must live under the ignored recordings directory. Cue labels
are used for fitting/scoring only; each detector runs an entire raw file.
"""
import argparse
from collections import Counter, deque
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

from backend.blink_shape import blink_shape
from backend.eog_communication import EOGConfirmation
from backend.eog_waveform import DIRECTIONS, WaveformProfile, haar
from backend.guided_eog import GuidedEOGTest, GuidedConfig
from backend.ring import RingState
from backend.temporal_eog import CausalFilter, StableBaselineFilter, EventSegmenter
from scripts.eog_experiment import load_trials, trial_fold
from scripts.eog_guided_experiment import profile_dict
from scripts.eog_stream_experiment import fit, read_streams, score, training_segments

VARIANTS = ('baseline', 'pulse-confirmation', 'extend1.6', 'lp10-notch60', 'lp15-notch60', 'lp20-notch60',
            'median3', 'stable3', 'haar0.1', 'haar0.25', 'haar-multiscale',
            'second-half', 'nearest2', 'dtw4', 'lda', 'crosstalk', 'bounded-scale')


class Biquad:
    """Direct form II, initially equilibrated at the first value."""
    def __init__(self, frequency, kind='lowpass', q=math.sqrt(.5), rate=250):
        w=2*math.pi*frequency/rate; c=math.cos(w); a=math.sin(w)/(2*q)
        if kind=='notch': b=(1,-2*c,1)
        else: b=((1-c)/2,1-c,(1-c)/2)
        self.b=tuple(v/(1+a) for v in b)
        self.a=(-2*c/(1+a),(1-a)/(1+a));self.z=None
    def process(self,x):
        b0,b1,b2=self.b;a1,a2=self.a
        if self.z is None:self.z=[x*(1-b0),x*(b2-a2)]
        y=b0*x+self.z[0]
        self.z=[b1*x-a1*y+self.z[1],b2*x-a2*y]
        return y


class AlternativeFilter(CausalFilter):
    def __init__(self, variant):self.variant=variant;super().__init__()
    def reset(self):
        super().reset();self.median=deque(maxlen=3)
        cutoff=int(self.variant.split('-')[0][2:]) if self.variant.startswith('lp') else None
        self.sos=[[Biquad(60,'notch',q=30),Biquad(cutoff)] for _ in (0,1)] if cutoff else None
    def process(self,h,v):
        if not all(math.isfinite(x) and 5<x<16378 for x in (h,v)):
            self.reset();return None
        self.count+=1;pair=(h,v)
        if self.sos:
            fast=[]
            for axis in (0,1):
                value=pair[axis]
                for stage in self.sos[axis]:value=stage.process(value)
                fast.append(value)
        else:
            self.median.append(pair)
            pair=tuple(statistics.median(x[i] for x in self.median) for i in (0,1))
            self.window.append(pair)
            fast=tuple(sum(x[i] for x in self.window)/len(self.window) for i in (0,1))
        if self.baseline is None:self.baseline=fast
        delta=tuple(fast[i]-self.baseline[i] for i in (0,1))
        self.baseline=tuple(self.baseline[i]+.004*delta[i] for i in (0,1))
        return delta if self.count%5==0 else None


def make_filter(variant):
    if variant=='stable3':return StableBaselineFilter(3)
    if variant=='median3' or variant.startswith('lp'):return AlternativeFilter(variant)
    return CausalFilter()


def event_features(samples):
    """Bounded morphology in physical seconds plus normalized amplitudes."""
    result=[]
    for axis in (0,1):
        y=[float(row[axis]) for row in samples];n=len(y)
        k=max(range(n),key=lambda i:abs(y[i]));peak=max(abs(y[k]),1e-9)
        sign=1 if y[k]>=0 else -1;s=[v*sign for v in y]
        d=[y[i]-y[i-1] for i in range(1,n)]
        half=[i for i,v in enumerate(s) if v>=peak*.5]
        left=min(half,default=k);right=max(half,default=k)
        return_index=next((i for i in range(k+1,n) if abs(y[i])<=peak*.2),n)
        velocity=sum(d[i-1]>0>=d[i] or d[i-1]<0<=d[i] for i in range(1,len(d)))
        rise=max(1,k-left+1);fall=max(1,right-k+1)
        result.extend((max(y),min(y),sum(y)/n,sum(abs(v) for v in y)/n,
                       len(half)/50,max(d)/peak,min(d)/peak,rise/fall,
                       velocity/n,(return_index-k)/50))
    energy=[sum(row[i]**2 for row in samples) for i in (0,1)]
    shape=blink_shape(samples)
    result.extend((energy[1]/max(sum(energy),1e-9),shape['blink_pulse_count'],
                   shape['blink_pair_gap_ms']/1000,shape['blink_pair_ratio']))
    return result


def train_lda(model):
    import numpy as np
    x=np.asarray([event_features(w*model['scale']) for w in model['waves']]);labels=sorted(set(model['labels']))
    mean=x.mean(0);scale=np.maximum(x.std(0),.01);z=(x-mean)/scale
    centers=np.asarray([z[np.asarray(model['labels'])==label].mean(0) for label in labels])
    residual=np.asarray([z[i]-centers[labels.index(label)] for i,label in enumerate(model['labels'])])
    covariance=residual.T@residual/max(1,len(x)-len(labels))
    covariance=.2*covariance+.8*np.diag(np.maximum(np.diag(covariance),.1))
    weights=centers@np.linalg.pinv(covariance)
    intercept=-.5*np.sum(weights*centers,axis=1)
    return dict(version=1,labels=labels,feature_mean=mean.tolist(),feature_scale=scale.tolist(),
                weights=weights.tolist(),intercepts=intercept.tolist(),
                note='Development LDA; scores are uncalibrated. Pure Python dot products suffice.')


def lda_scores(features,model):
    z=[(v-m)/s for v,m,s in zip(features,model['feature_mean'],model['feature_scale'])]
    return [b+sum(w*v for w,v in zip(row,z)) for row,b in zip(model['weights'],model['intercepts'])]


class ExperimentProfile(WaveformProfile):
    """Optional NumPy is strictly inside this offline comparison module."""
    def __init__(self,model,variant,leak=0):
        import numpy as np
        super().__init__(profile_dict(model));self.variant=variant;self.leak=leak
        self.array=np.asarray(self.waves);self.gain=[1.,1.]
        self.lda=train_lda(model) if variant=='lda' else None
        self.seen=0
        if leak:self.array[:,:,0]-=leak*self.array[:,:,1]*self.scale[1]/self.scale[0]
    def classify(self,samples,haar_weight=0):
        import numpy as np
        x=np.clip(np.asarray(samples)/(np.asarray(self.scale)*self.gain),-2,2)
        if self.leak:x[:,0]-=self.leak*x[:,1]*self.scale[1]/self.scale[0]
        ds=np.full(len(self.waves),np.inf)
        for shift in range(-4,5,2):
            a=max(0,shift);b=max(0,-shift);n=50-abs(shift)
            d=np.square(self.array[:,a:a+n]-x[b:b+n]).mean(axis=(1,2))
            ds=np.minimum(ds,d)
        if self.variant.startswith('haar'):
            widths=(3,6,10) if self.variant=='haar-multiscale' else (10,)
            weight=.1 if self.variant=='haar-multiscale' else float(self.variant[4:])
            for width in widths:
                hx=np.asarray(haar(x[:,1].tolist(),width))
                hw=np.asarray([haar(w[:,1].tolist(),width) for w in self.array])
                ds+=weight*np.square(hw-hx).mean(1)/len(widths)
        elif self.variant=='second-half':
            ds+=np.square(self.array[:,20:]-x[20:]).mean(axis=(1,2))
        elif self.variant=='dtw4':
            ds=np.asarray([dtw_distance(w,x,4) for w in self.array])
        self.last_distances=[float(d) for d in ds]
        by_label={l:float(min(d for d,k in zip(ds,self.labels) if k==l)) for l in set(self.labels)}
        if self.variant=='nearest2':
            by_label={l:float(statistics.mean(sorted(float(d) for d,k in zip(ds,self.labels) if k==l)[:2])) for l in set(self.labels)}
        label=min(by_label,key=by_label.get)
        if self.lda:
            scores=lda_scores(event_features((x*np.asarray(self.scale)).tolist()),self.lda)
            label=self.lda['labels'][max(range(len(scores)),key=scores.__getitem__)]
        distance=by_label[label];energy=np.square(x).sum(0)
        return dict(**blink_shape(samples),label=label,distance=distance,
                    other_label_margin=min(d for l,d in by_label.items() if l!=label)/max(distance,1e-9),
                    blink_margin=min(d for l,d in by_label.items() if l not in DIRECTIONS)/max(distance,1e-9),
                    direction_margin=min(d for l,d in by_label.items() if l in DIRECTIONS and l!=label)/max(distance,1e-9),
                    horizontal_fraction=float(energy[0]/max(float(sum(energy)),1e-9)))


def dtw_distance(left,right,band=4):
    """Narrow Sakoe-Chiba band, squared two-axis error / 100 scalar values."""
    n=len(left);previous=[math.inf]*(n+1);previous[0]=0
    for i in range(1,n+1):
        current=[math.inf]*(n+1)
        for j in range(max(1,i-band),min(n,i+band)+1):
            cost=sum((float(left[i-1][a])-float(right[j-1][a]))**2 for a in (0,1))
            current[j]=cost+min(current[j-1],previous[j],previous[j-1])
        previous=current
    return previous[n]/(2*n)


class AdaptiveSegmenter(EventSegmenter):
    """Offline extension perturbation; cannot recover peaks before window start."""
    def process(self,h,v):
        result=super().process(h,v)
        if result is None:return None
        if len(result['samples'])<80 and abs(v)>400:
            result.pop('emitted',None);self.candidate=result
            return None
        if len(result['samples'])>50:
            values=result['samples'];last=len(values)-1
            result['samples']=[tuple(values[int(i*last/49)][axis]*(1-i*last/49%1)+
                values[min(last,int(i*last/49)+1)][axis]*(i*last/49%1)
                for axis in (0,1)) for i in range(50)]
        return result


class ExperimentDetector(GuidedEOGTest):
    def __init__(self,profile,variant):self.variant=variant;super().__init__(profile,GuidedConfig(pulse_confirmation=variant=='pulse-confirmation'))
    def reset(self,*args,**kwargs):
        super().reset(*args,**kwargs);self.filter=make_filter(self.variant)
        if self.variant=='extend1.6':self.detector=AdaptiveSegmenter(self.detector.config)


def simulate(raw,profile,variant='baseline',confirmation_factory=EOGConfirmation):
    """Transport-free simulation using real confirmation and ring behavior; no speech."""
    detector=ExperimentDetector(profile,variant);confirmation=confirmation_factory(pulse_mode=variant=='pulse-confirmation');ring=RingState()
    ring.cardinal_layout=True;events=[];selections=[];last=None;last_pair=None;accepted_amplitudes=[]
    for row in raw:
        slot=detector.process(float(row['horizontal_adc']),float(row['vertical_adc']),int(row['timestamp_ms']))
        if slot is not None:
            confirmation.clear();ring.action('focus','offline-replay',slot)
            if ring.selected==slot and ring.slots()[slot]['enabled']:confirmation.focus(ring,detector.raw_index)
        event=detector.last_result if detector.last_result is not last else None
        if confirmation.update(ring,detector,event):
            selections.append(dict(event,onset=event.get('onset_sample',detector.raw_index),emitted=detector.raw_index))
        pair=detector.last_blink_result
        if variant=='pulse-confirmation' and pair is not None and pair is not last_pair:
            last_pair=pair
            if confirmation.update(ring,detector,pair):
                selections.append(dict(pair,onset=pair['onset_sample'],emitted=detector.raw_index))
        if event is not None:
            last=event;events.append(dict(event,onset=event.get('onset_sample',detector.raw_index),emitted=detector.raw_index))
            if variant=='bounded-scale' and event['reason']=='accepted' and len(accepted_amplitudes)<3:
                # Online engineering perturbation, fitted only from past accepted events.
                # It can reinforce false positives; retained only as a comparison.
                recent=list(detector.recent_frames)[-50:]
                for axis in (0,1):
                    peak=max(abs(frame[axis+1]) for frame in recent)
                    if peak>800:
                        target=max(.8,min(1.25,peak/profile.scale[axis]))
                        profile.gain[axis]=max(.8,min(1.25,.8*profile.gain[axis]+.2*target))
                accepted_amplitudes.append(event)
    return events,selections,detector.snapshot()


def confirmation_score(selections,rows,entry,fold):
    """Selection intent is absent: show phase counts and conservative negatives."""
    selected=[]
    for event in selections:
        index=max(0,min(len(rows)-1,event['onset']));r=rows[index]
        if r.get('run_id')!=entry['run_id']:continue
        try:repeat=trial_fold(r['trial_id'])
        except ValueError:continue
        if repeat!=fold:continue
        prefix=r['trial_id'].rsplit('-',1)[0].replace('-','_')
        if prefix not in entry['labels']:continue
        selected.append(dict(phase=r['phase'],label=r['intended_label'],sample=index))
    negative=[s for s in selected if not(s['phase']=='movement' and s['label']=='double_blink')]
    return dict(selections=len(selected),negative_phase_confirmations=len(negative),
                by_phase=dict(Counter(x['phase'] for x in selected)),
                by_label=dict(Counter(x['label'] for x in selected)),details=selected,
                intended_selection_misses=None,
                note='No instructed gaze/confirm sequences: deliberate selection hits/misses unknowable.')


def spectral_report(streams,entries):
    import numpy as np
    result=[]
    for entry in entries:
        s=streams[entry['recording']];blocks=[]
        for start in range(0,len(s['raw'])-500,250):
            metadata=s['rows'][start:start+500]
            if not all(r.get('run_id')==entry['run_id'] and r['phase']=='baseline' and r['intended_label']=='neutral' for r in metadata):continue
            x=np.asarray([[float(r[k]) for k in ('horizontal_adc','vertical_adc')] for r in s['raw'][start:start+500]])
            x-=x.mean(0);power=np.abs(np.fft.rfft(x*np.hanning(len(x))[:,None],axis=0))**2
            freq=np.fft.rfftfreq(len(x),1/250)
            blocks.append((power,freq))
        row=dict(recording=Path(entry['recording']).name,blocks=len(blocks),channels={})
        for axis,name in enumerate(('horizontal','vertical')):
            if not blocks:continue
            power=np.median(np.asarray([p[:,axis] for p,_ in blocks]),axis=0);f=blocks[0][1]
            tone=power[(f>=59)&(f<=61)].sum();surround=power[((f>=54)&(f<=58))|((f>=62)&(f<=66))].mean()
            row['channels'][name]=dict(mains_59_61_fraction=float(tone/max(power[(f>=1)&(f<=100)].sum(),1e-9)),
                mains_peak_over_neighbor=float(power[(f>=59)&(f<=61)].max()/max(surround,1e-9)),
                peak_55_65_hz=float(f[(f>=55)&(f<=65)][np.argmax(power[(f>=55)&(f<=65)])]))
        result.append(row)
    return result


def altered_streams(base,variant):
    import numpy as np
    result={}
    for path,s in base.items():
        filt=make_filter(variant);frames=[];indices=[];previous=None
        for i,row in enumerate(s['raw']):
            timestamp=int(row['timestamp_ms'])
            if previous is not None and timestamp-previous>500:filt.reset()
            value=filt.process(float(row['horizontal_adc']),float(row['vertical_adc']))
            if value is not None:frames.append(value);indices.append(i)
            previous=timestamp
        result[path]=dict(s,frames=np.asarray(frames),indices=np.asarray(indices))
    return result


def crosstalk_coefficient(model):
    import numpy as np
    waves=np.asarray(model['waves'])[np.asarray([l in ('blink','double_blink') for l in model['labels']])]
    h=(waves[:,:,0]*model['scale'][0]).ravel();v=(waves[:,:,1]*model['scale'][1]).ravel()
    return max(-.3,min(.3,float(h@v/max(v@v,1e-9))))


def coverage(trials):
    sessions=sorted({t['recording'] for t in trials})
    return [dict(held_out=session,held_out_labels=sorted({t['label'] for t in trials if t['recording']==session and t['label']!='neutral'}),
                 training_labels=sorted({t['label'] for t in trials if t['recording']!=session and t['label']!='neutral'}),
                 missing_training_labels=sorted({t['label'] for t in trials if t['recording']==session and t['label']!='neutral'}-
                                                {t['label'] for t in trials if t['recording']!=session and t['label']!='neutral'}),
                 hits=None,misses=None,false_confirmations=None,
                 reason='Held-out classes absent from training; no identifiable cross-session comparison.') for session in sessions]


def run(manifest,output,variants=VARIANTS):
    import numpy as np
    output=Path(output).resolve();private=Path('recordings').resolve()
    if not output.is_relative_to(private):raise ValueError('Private outputs must be beneath recordings/')
    output.mkdir(parents=True,exist_ok=True)
    entries=json.loads(Path(manifest).read_text());trials=load_trials(manifest);base=read_streams(manifest)
    report=dict(evidence='Reused-data development replay; not accuracy or independent validation.',
                commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                numpy=np.__version__,spectra=spectral_report(base,entries),leave_session_out=coverage(trials),
                limits=['All classes are concentrated by session. Repetition holdout is not session holdout.',
                        'Cue-to-emit includes wearer response; physiological onset is not annotated.',
                        'No instructed selection task in reviewed runs: false confirmations are negative-cue proxies; true confirmation misses are N/A.',
                        'No natural-versus-deliberate blink intention labels in live logs; numerical separation is N/A.',
                        'Offline alternatives refit their templates inside each training fold; no held-out trial is used to fit.',
                        'Classifier distances, LDA scores and engineered margins are not calibrated probabilities.'],variants={})
    for variant in variants:
        started=time.monotonic();streams=altered_streams(base,variant) if variant=='stable3' or variant=='median3' or variant.startswith('lp') else base
        scores=[];confirmations=[];runs=[];leaks=[]
        for fold in range(1,6):
            model=fit(trials,streams,fold,50);leak=crosstalk_coefficient(model) if variant=='crosstalk' else 0
            if leak:leaks.append(leak)
            for entry in entries:
                profile=ExperimentProfile(model,variant,leak)
                events,selections,final=simulate(streams[entry['recording']]['raw'],profile,variant)
                s=score(events,streams[entry['recording']]['rows'],entry,fold);scores.append(s)
                c=confirmation_score(selections,streams[entry['recording']]['rows'],entry,fold);confirmations.append(c)
                runs.append(dict(fold=fold,recording=Path(entry['recording']).name,events=events,selections=selections,confirmation=c))
        summary={k:sum(s[k] for s in scores) for k in ('trials','hits','misses','wrong','duplicates','false_directions','negative_seconds')}
        latency=[x for s in scores for x in s['latencies']]
        summary.update(median_cue_to_emit_s=statistics.median(latency) if latency else None,
                       false_events_per_minute=summary['false_directions']*60/summary['negative_seconds'],
                       negative_phase_confirmations=sum(c['negative_phase_confirmations'] for c in confirmations),
                       total_scored_selections=sum(c['selections'] for c in confirmations),
                       intended_confirmation_misses=None,processing_seconds=round(time.monotonic()-started,2))
        report['variants'][variant]=dict(summary=summary,fold_scores=scores,confirmation_scores=confirmations,runs=runs,leak_coefficients=leaks)
        (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
        print(variant,json.dumps(summary),flush=True)
    all_model=fit(trials,base,0,50)
    (output/'feature-lda.json').write_text(json.dumps(train_lda(all_model),indent=2))
    # Morphology by reviewed instructed label; windows are training-aligned, not independent events.
    shape={}
    for label,w in training_segments(trials,base,0,50):
        raw_features=event_features(w.tolist())
        shape.setdefault(label,[]).append(dict(vertical_half_height_s=raw_features[14],
            vertical_rise_fall_ratio=raw_features[17],vertical_return_s=raw_features[19],
            **blink_shape(w.tolist())))
    report['morphology_by_cue']=shape
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',default='recordings/reviewed-runs.json')
    p.add_argument('--output',required=True);p.add_argument('--variants',nargs='+',choices=VARIANTS,default=VARIANTS)
    args=p.parse_args();run(args.manifest,args.output,args.variants)
