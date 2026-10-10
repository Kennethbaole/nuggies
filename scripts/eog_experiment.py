"""Offline supervised sequence experiment on reviewed EOG trials.

python -m scripts.eog_experiment --manifest recordings/reviewed-runs.json \
    --output recordings/sequence-experiment

Optional requirements-eog.txt. No raw data, profiles or models leave this machine.
Cue-aligned classification is an algorithm experiment, not live gaze tracking.
"""
import argparse
import csv
import json
from itertools import groupby
from pathlib import Path
import random
import re

LABELS = ('neutral', 'left', 'right', 'up', 'down', 'blink', 'double_blink')


def trial_fold(trial_id):
    match = re.search(r'-(\d+)$', trial_id)
    if not match or not 1 <= int(match[1]) <= 5:
        raise ValueError('Movement trial needs a repetition suffix from 1 to 5')
    return int(match[1])


def load_trials(manifest, fs=250, seconds=3):
    """Validate alignment; exclude unreviewed runs/classes by explicit manifest."""
    from backend.recording import CSVReplaySource
    trials = []
    size = round(fs * seconds)
    entries = json.loads(Path(manifest).read_text())
    if not entries:
        raise ValueError('Manifest must list reviewed runs')
    for entry in entries:
        path = Path(entry['recording'])
        with path.open() as stream:
            source = CSVReplaySource(stream)
            raw = []
            while (sample := source.read_sample()) is not None:
                raw.append(sample)
        with path.with_suffix('.trials.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        if len(raw) != len(rows) or any(str(s.timestamp_ms) != r['timestamp_ms'] for s, r in zip(raw, rows)):
            raise ValueError('Trial metadata is not aligned with raw samples')
        if entry['run_id'] not in {r.get('run_id') for r in rows}:
            raise ValueError('Reviewed run not found')
        allowed = set(entry['labels'])
        if not allowed <= set(LABELS):
            raise ValueError('Unknown reviewed class')
        groups = []
        start = 0
        for key, group in groupby(rows, lambda r: (r.get('run_id'), r['trial_id'], r['phase'], r['intended_label'])):
            count = sum(1 for _ in group)
            groups.append((key, start, start + count))
            start += count
        neutral_fold = 0
        for (run, trial, phase, label), a, b in groups:
            if run != entry['run_id'] or label not in allowed:
                continue
            if phase == 'movement':
                spans = [(a, trial_fold(trial), trial)]
            elif phase == 'baseline' and label == 'neutral':
                spans = []
                # One-second lead-in; disjoint neutral examples, capped at five/run.
                for begin in range(a + fs, b - size + 1, size):
                    if neutral_fold == 5:
                        break
                    neutral_fold += 1
                    spans.append((begin, neutral_fold, f'neutral-{neutral_fold}'))
            else:
                continue
            for begin, fold, trial in spans:
                end = begin + size
                if begin < fs // 2 or end > len(raw) or any(r.get('run_id') != run for r in rows[begin:end]):
                    raise ValueError('Trial lacks context or crosses a run boundary')
                if label == 'neutral' and end > b:
                    raise ValueError('Neutral window crosses a cue boundary')
                context = raw[begin-fs//2:begin]
                samples = raw[begin:end]
                if any(s.horizontal <= 5 or s.horizontal >= 16378 or s.vertical <= 5 or s.vertical >= 16378 for s in samples):
                    raise ValueError('Reviewed trial clips; exclude/review it explicitly')
                trials.append(dict(recording=path.name, run=run, trial=trial, label=label, fold=fold,
                                   start_sample=begin, context=[[s.horizontal,s.vertical] for s in context],
                                   samples=[[s.horizontal,s.vertical] for s in samples]))
    identities = [(t['recording'],t['run'],t['trial']) for t in trials]
    if len(identities) != len(set(identities)):
        raise ValueError('Duplicate trial in manifest')
    return trials


def sequence(trial, smoothing='mean'):
    import numpy as np
    raw = np.asarray(trial['context'] + trial['samples'], dtype=float)
    baseline = np.median(np.asarray(trial['context']), axis=0)
    offset = len(trial['context'])
    output = []
    for end in range(offset + 5, len(raw) + 1, 5):
        if smoothing == 'sym20':
            import pywt
            import warnings
            # Mirrors the paper's short rolling window; boundary effects need evaluation.
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                value = []
                for axis in (0,1):
                    window = raw[end-50:end,axis]
                    approximation, detail = pywt.wavedec(window, 'sym20', level=1)
                    sigma = np.median(abs(detail - np.median(detail))) / .6745
                    detail = pywt.threshold(detail, sigma * np.sqrt(2*np.log(len(window))))
                    value.append(pywt.waverec([approximation,detail],'sym20')[-1])
        else:
            value = raw[end-15:end].mean(axis=0)
        output.append(np.asarray(value) - baseline)
    return np.asarray(output, dtype='float32')


def metrics(actual, predicted, labels):
    matrix = [[sum(a == left and p == right for a,p in zip(actual,predicted)) for right in labels] for left in labels]
    recalls = [matrix[i][i]/sum(row) for i,row in enumerate(matrix) if sum(row)]
    return dict(count=len(actual), correct=sum(a==p for a,p in zip(actual,predicted)),
                accuracy=sum(a==p for a,p in zip(actual,predicted))/len(actual),
                balanced_accuracy=sum(recalls)/len(recalls), labels=labels, confusion=matrix)


def run(trials, output, epochs=50, seed=17, smoothing='mean'):
    import numpy as np
    import torch
    from torch import nn
    from backend.live_wheel import LiveWheelTest
    torch.set_num_threads(2)
    labels = [label for label in LABELS if any(t['label']==label for t in trials)]
    if len(labels)<2 or epochs<1:
        raise ValueError('Need multiple classes and positive epochs')
    for label in labels:
        if {t['fold'] for t in trials if t['label']==label} != set(range(1,6)):
            raise ValueError('Every class must have all five reviewed repetitions')
    data = np.stack([sequence(t,smoothing) for t in trials])
    targets = np.asarray([labels.index(t['label']) for t in trials])
    predictions = []
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    class Network(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(2,128,num_layers=3,dropout=.3,batch_first=True)
            self.head = nn.Linear(128,len(labels))
        def forward(self,x):
            _,(hidden,_) = self.lstm(x)
            return self.head(hidden[-1])
    for fold in range(1,6):
        random.seed(seed+fold); np.random.seed(seed+fold); torch.manual_seed(seed+fold)
        train = np.asarray([i for i,t in enumerate(trials) if t['fold']!=fold])
        test = np.asarray([i for i,t in enumerate(trials) if t['fold']==fold])
        # Scales estimated exclusively from training sequences; preserve relative amplitudes.
        scale = np.maximum(np.percentile(abs(data[train]),95,axis=(0,1)),1)
        normalized = np.clip(data/scale,-1,1).astype('float32')
        x = torch.from_numpy(normalized)
        y = torch.from_numpy(targets).long()
        model = Network()
        optimizer = torch.optim.Adam(model.parameters(),lr=.001)
        counts = np.bincount(targets[train],minlength=len(labels))
        loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(len(train)/(len(labels)*counts),dtype=torch.float32))
        for epoch in range(epochs):
            model.train()
            order = train[np.random.permutation(len(train))]
            for a in range(0,len(order),16):
                ids = order[a:a+16]
                optimizer.zero_grad(); loss=loss_fn(model(x[ids]),y[ids]);loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(),1)
                optimizer.step()
        model.eval()
        with torch.no_grad():
            probs = model(x[test]).softmax(-1).numpy()
            train_accuracy = (model(x[train]).argmax(-1)==y[train]).float().mean().item()
        templates = np.stack([normalized[train][targets[train]==i].mean(0) for i in range(len(labels))])
        np.savez(output/f'templates-fold-{fold}.npz', templates=templates, scale=scale, labels=labels)
        torch.save(dict(state_dict=model.state_dict(), scale=scale.tolist(), labels=labels,
                        held_out_fold=fold), output/f'lstm-fold-{fold}.pt')
        for position,index in enumerate(test):
            t = trials[index]
            template = labels[int(np.square(templates-normalized[index]).mean(axis=(1,2)).argmin())]
            # Fixed current-detector comparator: center context plus the same 3s cue window.
            detector = LiveWheelTest()
            for _ in range(250):detector.process(*np.median(np.asarray(t['context']),axis=0))
            first = None
            for sample in t['samples']:
                slot = detector.process(*sample)
                if first is None and slot is not None:first=slot
            current = {0:'up',2:'right',4:'down',6:'left'}.get(first,'neutral' if first is None else 'diagonal')
            predictions.append(dict(recording=t['recording'],run=t['run'],trial=t['trial'],fold=fold,
                                    expected=t['label'],lstm=labels[int(probs[position].argmax())],
                                    confidence=float(probs[position].max()),template=template,current=current))
        print(f'Fold {fold}: train={len(train)}, test={len(test)}, LSTM train accuracy={train_accuracy:.3f}',flush=True)
    actual = [p['expected'] for p in predictions]
    report = dict(seed=seed,epochs=epochs,smoothing=smoothing,window_s=3,sequence_rate_hz=50,
                  architecture='3-layer 128-unit LSTM; 7-or-fewer event-class outputs',
                  split='leave-one-repetition-out, all 5 folds; shared recording sessions',
                  limits=['Cue-aligned 3s windows; not a continuous live detector or gaze-coordinate regressor.',
                          'Not an exact paper reproduction; no blink onset labels or pixel-coordinate targets.',
                          'Very few independent trials; same-session folds do not establish new-session generalization.',
                          'Direction classes are concentrated in different sessions; session artifacts can confound classification.',
                          '3s direction windows include initial return; baseline context may contain artifacts.',
                          'No test-fold model selection; confidence is not calibrated; no live activation.',
                          'Current comparator reset per trial; full-stream recovery faults need separate scoring.'],
                  results={name:metrics(actual,[p[name] for p in predictions],labels+(['diagonal'] if name=='current' else [])) for name in ('current','template','lstm')},
                  predictions=predictions)
    nav_label = lambda value: value if value in ('left','right','up','down','diagonal') else 'no_direction'
    report['navigation'] = {name: metrics([nav_label(p['expected']) for p in predictions],
                                         [nav_label(p[name]) for p in predictions],
                                         ['no_direction','left','right','up','down','diagonal'])
                            for name in ('current','template','lstm')}
    report['runtime'] = dict(python=__import__('sys').version, numpy=np.__version__, torch=torch.__version__)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report['results'],indent=2))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--epochs',type=int,default=50)
    parser.add_argument('--seed',type=int,default=17)
    parser.add_argument('--smoothing',choices=('mean','sym20'),default='mean')
    args=parser.parse_args()
    trials=load_trials(args.manifest)
    run(trials,args.output,args.epochs,args.seed,args.smoothing)

if __name__=='__main__':main()
