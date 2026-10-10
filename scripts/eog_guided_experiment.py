"""Evaluate the exact guided diagnostic runtime on reused recordings, without cues as input."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics

from backend.eog_waveform import WaveformProfile
from backend.guided_eog import GuidedConfig, GuidedEOGTest
from scripts.eog_experiment import load_trials
from scripts.eog_stream_experiment import fit, read_streams, score


def profile_dict(model):
    return dict(version=1,capture_s=1,threshold_h=800,threshold_v=800,reject=True,
                labels=model['labels'],scale=model['scale'].tolist(),waves=model['waves'].tolist())


def run(manifest,output):
    entries=json.loads(Path(manifest).read_text());trials=load_trials(manifest);streams=read_streams(manifest)
    variants={'guided-unchecked-blink':GuidedConfig(reject_blinks=False),
              'guided':GuidedConfig(),
              'guided-retry3':GuidedConfig(retry_s=3),
              'guided-reject-all-blinks':GuidedConfig(blink_horizontal_min=0),
              'guided-haar-low':GuidedConfig(haar_weight=.1),
              'guided-haar-medium':GuidedConfig(haar_weight=.25),
              'guided-haar':GuidedConfig(haar_weight=.5)}
    reports={}
    models={fold:WaveformProfile(profile_dict(fit(trials,streams,fold,50))) for fold in range(1,6)}
    for name,config in variants.items():
        scores=[];outputs=[]
        for fold,profile in models.items():
            for entry in entries:
                stream=streams[entry['recording']];detector=GuidedEOGTest(profile,config);events=[];last=None
                for row in stream['raw']:
                    detector.process(float(row['horizontal_adc']),float(row['vertical_adc']),int(row['timestamp_ms']))
                    if detector.last_result is not None and detector.last_result is not last:
                        last=detector.last_result
                        events.append(dict(last,onset=last.get('onset_sample',last['emitted_sample']),emitted=last['emitted_sample']))
                scores.append(score(events,stream['rows'],entry,fold))
                outputs.append(dict(fold=fold,recording=Path(entry['recording']).name,events=events,final=detector.snapshot()))
        summary={k:sum(s[k] for s in scores) for k in ('trials','hits','misses','wrong','duplicates','false_directions','negative_seconds')}
        latencies=[x for s in scores for x in s['latencies']]
        summary['median_cue_to_emit_s']=statistics.median(latencies) if latencies else None
        reports[name]=dict(config=asdict(config),summary=summary,fold_scores=scores,streams=outputs)
        print(name,json.dumps(summary),flush=True)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'report.json').write_text(json.dumps(dict(variants=reports,
        limits=['Reused-data development comparison, not independent validation.',
                'Recordings contain no wearer response to a retry prompt.',
                'Fixed polarity; cardinal focus only; no confirmation or speech.']),indent=2))
    (output/'candidate-profile.json').write_text(json.dumps(profile_dict(fit(trials,streams,0,50))))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();run(args.manifest,args.output)
