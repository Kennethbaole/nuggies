"""Offline waveform measurements, not blink classification or selection commands.

python -m backend.vertical_features recordings/trial.csv > recordings/features.json
Labels select analysis windows only; they do not establish event onsets or intent.
"""
import argparse
import csv
import json
import statistics
from itertools import groupby
from pathlib import Path
from .recording import CSVReplaySource


def smooth(values, size):
    out=[]; total=0
    for i,v in enumerate(values):
        total+=v
        if i>=size: total-=values[i-size]
        out.append(total/min(i+1,size))
    return out


def waveform_features(horizontal, vertical, baseline_h, baseline_v, fs=250, peak_threshold=1500, peak_gap_s=.25):
    if len(horizontal)!=len(vertical) or not horizontal or fs<=0 or peak_threshold<=0 or peak_gap_s<=0:
        raise ValueError('Aligned nonempty channels and positive fs required')
    v=[x-baseline_v for x in vertical];h=[x-baseline_h for x in horizontal]
    positive=max(range(len(v)),key=v.__getitem__);negative=min(range(len(v)),key=v.__getitem__)
    pos=max(0,v[positive]);neg=max(0,-v[negative])
    # Width of the connected positive lobe surrounding the largest peak.
    left=right=positive
    if pos:
        while left>0 and v[left-1]>=pos/2:left-=1
        while right+1<len(v) and v[right+1]>=pos/2:right+=1
    peaks=[]
    for i in range(1,len(v)-1):
        if v[i]>=peak_threshold and v[i]>v[i-1] and v[i]>=v[i+1]:
            if peaks and i-peaks[-1]<max(1,round(peak_gap_s*fs)):
                if v[i]>v[peaks[-1]]:peaks[-1]=i
            else:peaks.append(i)
    return dict(positive_peak_counts=round(pos,2),negative_peak_counts=round(neg,2),
                negative_positive_ratio=round(neg/pos,3) if pos else None,
                positive_peak_s=round(positive/fs,3),negative_peak_s=round(negative/fs,3),
                signed_peak_gap_s=round((negative-positive)/fs,3),
                positive_half_height_width_s=round((right-left+1)/fs,3) if pos else 0,
                horizontal_peak_counts=round(max(abs(x) for x in h),2),
                horizontal_vertical_ratio=round(max(abs(x) for x in h)/max(pos,neg),3) if max(pos,neg) else None,
                peak_threshold_counts=peak_threshold, peak_gap_s=peak_gap_s,
                positive_peak_candidates=[dict(time_s=round(i/fs,3),amplitude=round(v[i],2)) for i in peaks])


def review(path,fs=250,smoothing_ms=100,peak_threshold=1500,peak_gap_ms=250):
    if min(fs,smoothing_ms,peak_threshold,peak_gap_ms)<=0:raise ValueError('Analysis settings must be positive')
    path=Path(path)
    with path.open() as stream:
        source=CSVReplaySource(stream);raw=[]
        while (sample:=source.read_sample()) is not None:raw.append(sample)
    with path.with_suffix('.trials.csv').open() as stream:labels=list(csv.DictReader(stream))
    if len(raw)!=len(labels) or any(str(x.timestamp_ms)!=y['timestamp_ms'] for x,y in zip(raw,labels)):
        raise ValueError('Trial metadata is not aligned')
    for row in labels:
        if not {'trial_id','phase','intended_label'}.issubset(row):raise ValueError('Trial metadata lacks required columns')
    size=max(1,round(smoothing_ms/1000*fs));h=smooth([x.horizontal for x in raw],size);v=smooth([x.vertical for x in raw],size)
    groups=[];start=0
    for key,group in groupby(labels,key=lambda x:(x.get('run_id',''),x['trial_id'],x['phase'],x['intended_label'])):
        n=sum(1 for _ in group);groups.append((key,start,start+n));start+=n
    windows=[]
    for index,(key,a,b) in enumerate(groups):
        run,trial,phase,label=key
        if phase=='movement':
            if index+1<len(groups):
                next_key,na,nb=groups[index+1]
                if next_key[:2]==key[:2] and next_key[2] in ('return','rest'): b=nb
        elif trial or label not in ('up','down','blink','double_blink','neutral'):continue
        base_start=max(0,a-fs)
        base_h=statistics.median(h[base_start:a]) if a else h[0]
        base_v=statistics.median(v[base_start:a]) if a else v[0]
        windows.append(dict(run_id=run,trial_id=trial,intended_label=label,
                            start_sample=a,end_sample=b,duration_s=round((b-a)/fs,3),
                            scope='movement and return/rest' if trial else 'manual block; may contain multiple events',
                            clipped_samples=sum(x.horizontal<=5 or x.horizontal>=16378 or x.vertical<=5 or x.vertical>=16378 for x in raw[a:b]),
                            features=waveform_features(h[a:b],v[a:b],base_h,base_v,fs,peak_threshold,peak_gap_ms/1000)))
    return dict(fs=fs,smoothing_ms=smoothing_ms,peak_threshold_counts=peak_threshold,peak_gap_ms=peak_gap_ms,samples=len(raw),windows=windows,experimental=True,
                note='No classifier or SELECT events. Ratios are descriptive, not a validated rule. Peak signs depend on placement. Signed gap uses extrema, not measured gaze onset. Multiple events can contaminate a window.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('recording');parser.add_argument('--fs',type=int,default=250)
    parser.add_argument("--smoothing-ms",type=float,default=100)
    parser.add_argument("--peak-threshold",type=float,default=1500)
    parser.add_argument("--peak-gap-ms",type=float,default=250)
    args=parser.parse_args()
    try: print(json.dumps(review(args.recording,args.fs,args.smoothing_ms,args.peak_threshold,args.peak_gap_ms),indent=2))
    except (ValueError,OSError) as error:parser.exit(1,f'{error}\n')

if __name__=='__main__':main()
