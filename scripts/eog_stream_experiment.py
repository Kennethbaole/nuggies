"""Continuous replay comparison; labels are used for fitting and scoring, never segmentation."""
import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import statistics

from backend.temporal_eog import CausalFilter, DecisionPolicy, EventSegmenter, PairedDirectionDetector, SegmentConfig
from backend.live_wheel import LiveWheelTest
from scripts.eog_experiment import load_trials, trial_fold

DIRECTIONS={'left','right','up','down'}


def read_streams(manifest):
    import numpy as np
    streams={}
    for entry in json.loads(Path(manifest).read_text()):
        path=Path(entry['recording'])
        if str(path) not in streams:
            with path.open() as f:raw=list(csv.DictReader(f))
            with path.with_suffix('.trials.csv').open() as f:rows=list(csv.DictReader(f))
            if len(raw)!=len(rows) or any(r['timestamp_ms']!=m['timestamp_ms'] for r,m in zip(raw,rows)):
                raise ValueError('Misaligned raw and trial metadata')
            filt=CausalFilter();frames=[];indices=[];resets=[];old=LiveWheelTest();old_events=[];previous=None
            for i,r in enumerate(raw):
                ts=int(r['timestamp_ms']);h=float(r['horizontal_adc']);v=float(r['vertical_adc'])
                if previous is not None and ts<previous:raise ValueError('Timestamps go backwards')
                gap=previous is not None and ts-previous>500
                if gap:filt.reset();old.reset()
                clipped=not (5<h<16378 and 5<v<16378)
                if gap or clipped:resets.append(len(frames))
                value=filt.process(h,v)
                if value is not None:frames.append(value);indices.append(i)
                slot=old.process(h,v)
                if slot is not None:old_events.append(dict(onset=i,emitted=i,label={0:'up',2:'right',4:'down',6:'left'}.get(slot,'diagonal')))
                previous=ts
            streams[str(path)]=dict(raw=raw,rows=rows,frames=np.asarray(frames),indices=np.asarray(indices),resets=set(resets),old_events=old_events)
    return streams


def features(x):
    import numpy as np
    return np.concatenate([np.max(x,axis=0),np.min(x,axis=0),np.mean(x,axis=0),
                           np.sqrt(np.mean(x*x,axis=0)),np.mean(abs(np.diff(x,axis=0)),axis=0),
                           np.mean(x[:len(x)//2],axis=0)-np.mean(x[len(x)//2:],axis=0)])


def training_segments(trials,streams,fold,capture,alignment="activity"):
    import numpy as np
    examples=[]
    for t in trials:
        if t['fold']==fold or t['label']=='neutral':continue
        s=next(s for p,s in streams.items() if Path(p).name==t['recording'])
        a=int(np.searchsorted(s['indices'],t['start_sample']))
        end=min(a+100,len(s['frames'])) # first 2s of instructed movement; no return used to find onset
        block=s['frames'][a:end]
        # Training alignment: earliest sizeable movement, relative to each trial peak.
        axis,sign={'left':(0,-1),'right':(0,1),'up':(1,1),'down':(1,-1)}.get(t['label'],(1,1))
        magnitude=np.maximum(block[:,axis]*sign,0) if alignment=="signed" else np.max(abs(block),axis=1)
        hits=np.flatnonzero(magnitude>=max(300,float(magnitude.max())*.35))
        onset=a+(int(hits[0]) if len(hits) else int(magnitude.argmax()))
        begin=max(0,onset-4);window=s['frames'][begin:begin+capture]
        if len(window)==capture:examples.append((t['label'],window))
    return examples


def fit(trials,streams,fold,capture,alignment="activity"):
    import numpy as np
    examples=training_segments(trials,streams,fold,capture,alignment)
    labels=[label for label,_ in examples];waves=np.stack([x for _,x in examples])
    scale=np.maximum(np.percentile(abs(waves),95,axis=(0,1)),100)
    waves=np.clip(waves/scale,-2,2)
    f=np.stack([features(x) for x in waves]);fscale=np.maximum(f.std(axis=0),.03)
    return dict(labels=labels,waves=waves,scale=scale,features=f/fscale,fscale=fscale)


def fit_recurrent(model, paper=False):
    import numpy as np
    import torch
    from torch import nn
    torch.set_num_threads(2);torch.manual_seed(37)
    labels=sorted(set(model['labels']))
    class Network(nn.Module):
        def __init__(self):
            super().__init__()
            width=128 if paper else 32
            self.rnn=nn.LSTM(2,width,num_layers=3 if paper else 1,
                             dropout=.3 if paper else 0,batch_first=True)
            self.head=nn.Linear(width*2,len(labels))
        def forward(self,x):
            y,_=self.rnn(x)
            return self.head(torch.cat((y.mean(1),y.max(1).values),1))
    net=Network();optimizer=torch.optim.Adam(net.parameters(),lr=.003)
    x=torch.tensor(np.asarray(model['waves']),dtype=torch.float32)
    y=torch.tensor([labels.index(l) for l in model['labels']])
    for epoch in range(100):
        net.train();optimizer.zero_grad()
        loss=nn.functional.cross_entropy(net(x),y);loss.backward()
        nn.utils.clip_grad_norm_(net.parameters(),1);optimizer.step()
    net.eval();model['network']=net;model['network_labels']=labels
    return model


def classify(window,model,method):
    import numpy as np
    x=np.clip(np.asarray(window)/model['scale'],-2,2)
    if method.startswith('lstm'):
        import torch
        with torch.no_grad():
            probs=model['network'](torch.tensor(x[None],dtype=torch.float32)).softmax(-1)[0].numpy()
        best=int(probs.argmax());label=model['network_labels'][best]
        return label,float(1-probs[best]),float(probs[best]/max(sum(p for p,l in zip(probs,model['network_labels']) if l in ('blink','double_blink')),1e-9))
    if method=='features':
        distance=np.square(model['features']-features(x)/model['fscale']).mean(axis=1)
    else:
        # Match individual examples, allowing +/- 80ms timing variation.
        distance=np.full(len(model['waves']),np.inf)
        for shift in range(-4,5,2):
            a=max(0,shift);b=max(0,-shift);n=len(x)-abs(shift)
            distance=np.minimum(distance,np.square(model['waves'][:,a:a+n]-x[b:b+n]).mean(axis=(1,2)))
    best=int(distance.argmin())
    label=model['labels'][best]
    blink_distance=min((float(d) for d,l in zip(distance,model['labels']) if l in ('blink','double_blink')),default=float('inf'))
    margin=blink_distance/max(float(distance[best]),1e-9)
    return label,float(distance[best]),margin


def score(events,rows,entry,fold,fs=250):
    """One direction per held-out movement cue; returns/rest are negative exposure."""
    from itertools import groupby
    windows=[];negative=[];start=0
    for key,group in groupby(rows,lambda r:(r.get('run_id'),r['trial_id'],r['phase'],r['intended_label'])):
        n=sum(1 for _ in group);a,b=start,start+n;start=b
        run,trial,phase,label=key
        if run!=entry['run_id']:continue
        if phase=='baseline' and label=='neutral':
            # Only score nonoverlapping baseline windows belonging to held-out fold.
            for begin in range(a+fs,b-3*fs+1,3*fs):
                # Preserve fold attribution from loader across multiple baseline blocks below.
                negative.append((begin,begin+3*fs,'baseline'))
            continue
        try:repeat=trial_fold(trial)
        except ValueError:continue
        if repeat!=fold:continue
        prefix=trial.rsplit('-',1)[0].replace('-','_')
        if prefix not in entry['labels']:continue
        if phase=='movement' and label in entry['labels'] and label in DIRECTIONS:
            windows.append(dict(a=a,b=b,label=label,trial=trial))
        elif label=='neutral' or label in entry['labels']:
            negative.append((a,b,phase))
    # Match only held-out neutral examples; neutral counter mirrors load_trials.
    baseline=[x for x in negative if x[2]=='baseline'][:5]
    negative=[x for x in negative if x[2]!='baseline']+[x for i,x in enumerate(baseline,1) if i==fold]
    hits=wrong=misses=duplicates=0;latencies=[];matched=set()
    for w in windows:
        candidates=[(i,e) for i,e in enumerate(events) if w['a']<=e['onset']<w['b'] and e['label'] in DIRECTIONS|{'diagonal'}]
        correct=[(i,e) for i,e in candidates if e['label']==w['label']]
        if correct:
            hits+=1;latencies.append((correct[0][1]['emitted']-w['a'])/fs)
        else:misses+=1
        wrong+=sum(e['label']!=w['label'] for _,e in candidates)
        duplicates+=max(0,len(correct)-1)
        matched.update(i for i,_ in candidates)
    false=sum(e['label'] in DIRECTIONS|{'diagonal'} and any(a<=e['onset']<b for a,b,_ in negative) for e in events)
    exposure=sum(b-a for a,b,_ in negative)/fs
    return dict(trials=len(windows),hits=hits,misses=misses,wrong=wrong,duplicates=duplicates,
                false_directions=false,negative_seconds=exposure,latencies=latencies)


def run(manifest,output,alignment="activity",selected=None):
    import numpy as np
    entries=json.loads(Path(manifest).read_text());trials=load_trials(manifest)
    streams=read_streams(manifest)
    # Predeclared development variants. All results remain exploratory, not a new held-out test.
    variants=[('current',None,None),('paired-0.7','paired',.7),('paired-1.0','paired',1.0)]
    for method in ('waveform','features'):
        for capture in (.6,1.0):variants.append((f'{method}-{capture}',method,capture))
    variants += [('waveform-policy','waveform',1.0),('waveform-reject','waveform',1.0),('features-policy','features',1.0),('lstm-small-policy','lstm-small',1.0),('lstm-paper-policy','lstm-paper',1.0)]
    if selected:
        names=set(selected)
        if names-{v[0] for v in variants}:raise ValueError('Unknown variant')
        variants=[v for v in variants if v[0] in names]
    reports={}
    for name,method,duration in variants:
        scores=[];outputs=[]
        for fold in range(1,6):
            model=fit(trials,streams,fold,round(duration*50),alignment) if method and method!='paired' else None
            if method and method.startswith('lstm'):model=fit_recurrent(model,paper=method=='lstm-paper')
            for entry in entries:
                s=streams[entry['recording']]
                if not method:events=s['old_events']
                elif method=='paired':
                    detector=PairedDirectionDetector(min_return_s=duration);events=[]
                    for i,(h,v) in enumerate(s['frames']):
                        if i in s['resets']:detector.reset()
                        event=detector.process(h,v)
                        if event:
                            delta=event['emitted']-event['onset']
                            events.append(dict(onset=int(s['indices'][max(0,i-delta)]),emitted=int(s['indices'][i]),label=event['label']))
                else:
                    detector=EventSegmenter(SegmentConfig(capture_s=duration));events=[];policy=DecisionPolicy(reject=name.endswith('reject'))
                    for i,(h,v) in enumerate(s['frames']):
                        if i in s['resets']:detector.reset();policy.reset()
                        segment=detector.process(h,v)
                        if segment:
                            label,distance,margin=classify(segment['samples'],model,method)
                            if name.endswith(('policy','reject')):
                                if method.startswith('lstm') and label in DIRECTIONS and distance>.4:label='unknown'
                                label,cooldown=policy.apply(label,distance,margin,i)
                                detector.ready_at=detector.index+cooldown
                            # Segment indices are local to resets; map using current emission position.
                            delta=segment['emitted']-segment['onset']
                            events.append(dict(onset=int(s['indices'][max(0,i-delta)]),emitted=int(s['indices'][i]),label=label,distance=distance))
                scores.append(score(events,s['rows'],entry,fold))
                outputs.append(dict(fold=fold,recording=Path(entry['recording']).name,events=events))
        summary={key:sum(s[key] for s in scores) for key in ('trials','hits','misses','wrong','duplicates','false_directions','negative_seconds')}
        latency=[v for s in scores for v in s['latencies']]
        summary['median_cue_to_emit_s']=statistics.median(latency) if latency else None
        summary['false_directions_per_minute']=summary['false_directions']*60/summary['negative_seconds'] if summary['negative_seconds'] else None
        reports[name]=dict(summary=summary,fold_scores=scores,streams=outputs)
        print(name,json.dumps(summary),flush=True)
    report=dict(variants=reports,limits=['Development comparison on reused recordings, not independent validation.',
                'Same-session repetition holdout; channel/session artifacts may confound classes.',
                'Detectors run full files; labels only fit training examples and score held-out regions.',
                'Cue-to-emit includes user reaction; true physiological onset is not annotated.',
                'Blink classes suppress directions; double-blink confirmation is not evaluated.',
                '250 Hz nominal raw rate; clipping/gaps reset candidates.'],
                alignment=alignment,recurrent_seed=37,recurrent_epochs=100,config=asdict(SegmentConfig()),runtime=dict(numpy=np.__version__))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'report.json').write_text(json.dumps(report,indent=2))
    # Deployment candidate fitted on all reviewed examples, never used for fold scoring.
    candidate=fit(trials,streams,0,50,alignment)
    profile=dict(version=1,alignment=alignment,labels=candidate['labels'],
                 waves=candidate['waves'].tolist(),scale=candidate['scale'].tolist(),
                 capture_s=1.0,threshold_h=800,threshold_v=800,reject=True,
                 note='All-data development candidate; replay only, not independently validated.')
    (output/'candidate-profile.json').write_text(json.dumps(profile))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
    p.add_argument('--alignment',choices=('activity','signed'),default='activity')
    p.add_argument('--variants',nargs='+',help='Optional subset of named variants')
    args=p.parse_args();run(args.manifest,args.output,args.alignment,args.variants)
