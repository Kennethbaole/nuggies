# Learning movement patterns from existing recordings

## Purpose

Use reviewed recordings already collected to build algorithms before requesting
more sensor tests. This offline experiment learns entire two-channel waveforms
and compares them with the current fixed-threshold detector. It does not change
live control or require the user to repeat acquisition.

Gaze highlighting has been fully removed. Detector status and raw channel
readouts remain available in the companion.

## Inputs and exclusions

The manifest is a private JSON list, for example:

```json
[
  {
    "recording": "recordings/reviewed-session.csv",
    "run_id": "reviewed-run-id",
    "labels": ["neutral", "left", "right"]
  }
]
```

Only explicitly reviewed runs/classes are used. Raw timestamps and metadata
must align exactly. Duplicate trials, clipping and windows crossing run boundaries
are rejected. The current local manifest excludes interrupted runs, the invalidated
horizontal-session blink trials, and skipped vertical-session double blinks.
Reviewed vertical single blinks and the completed dedicated double-blink run are
included. Manifests, reports, checkpoints and recordings stay under Git-ignored
recordings/; none are shipped as public fixtures.

The dataset currently provides 45 windows: five each for four cardinal movements,
single blink and double blink, plus 15 neutral windows. Each example is three
seconds long. Movement windows begin at the instruction cue, not a hand-marked
physiological onset. Direction windows include the initial return; this is an
explicit limitation, not an online latency claim.

## Algorithms and evaluation

The first comparison uses causal 60 ms averaging and downsamples 250 Hz to 50 Hz.
A second uses rolling Sym20 level-one denoising on 50 raw samples. That short
wavelet window has boundary effects and is experimental.

A half-second preceding context establishes each example's baseline. Channel
scales are fit exclusively on training examples and sequences clipped to [-1,1].
The supervised template model learns the mean sequence for each class and chooses
the closest waveform by mean squared distance. It learns shape, polarity, relative
amplitude and timing from data, rather than a hand-set peak threshold.

The LSTM has three 128-unit recurrent layers, dropout 0.3, and an event-class head;
Adam trains for 50 epochs. It adapts a published recurrent architecture but is
not an exact paper reproduction: our targets are event classes rather than pixel
coordinates plus binary blink labels. No coordinate targets or model weights are
invented. The original fixed-threshold comparator is reset and given the same
context/window; it cannot distinguish single/double blinks as event classes.

Five folds each hold out one entire repetition across classes/sessions. The other
four repetitions train the model. Normalization and templates never fit held-out
examples. Epochs and seed are fixed; test scores do not select checkpoints.
Outputs include per-trial predictions, confusion matrices, fold checkpoints and
template arrays. Seven-class classification and navigation are reported separately.
For navigation, neutral and either blink class mean **no direction**, not an
activation or confirmation.

## Measured development result

The initial fixed-seed comparison on 45 held-out cue-aligned windows yielded:

| Model | Correct direction/no-direction | Exact seven-class event labels |
| --- | --- | --- |
| Current fixed thresholds | 20/45 | 19/45; no blink-class outputs |
| Learned waveform templates | 41/45 | 37/45 |
| LSTM, mean preprocessing | 34/45 | 18/45 |
| LSTM, Sym20 preprocessing | 33/45 | 19/45 |

The template model recognized 18/20 cardinal trials and rejected directional
navigation in 23/25 neutral/blink windows. Exact double-blink identification was
only 1/5 for templates; suppressing direction during a blink is not the same as
recognizing an intentional double-blink confirmation. Sym20 templates had the
same aggregate result as mean-preprocessed templates.

These results demonstrate useful algorithm work from existing data. They do not
establish reliable continuous control: examples are cue-aligned, only a few
independent repetitions exist, and classes are concentrated in different recording
sessions. Same-session folds can learn session artifacts. No unseen-session,
continuous false-trigger rate, diagonal accuracy, or live latency is claimed.

## Reproduce locally

Use an isolated environment and optional dependencies:

```sh
python3 -m venv /tmp/nuggies-eog-venv
/tmp/nuggies-eog-venv/bin/python -m pip install -r requirements-eog.txt
/tmp/nuggies-eog-venv/bin/python -m scripts.eog_experiment \
  --manifest recordings/reviewed-runs.json \
  --output recordings/sequence-experiment
/tmp/nuggies-eog-venv/bin/python -m scripts.eog_experiment \
  --manifest recordings/reviewed-runs.json \
  --output recordings/sequence-experiment-sym20 --smoothing sym20
```

Default seed: 17. Exact numerical results can vary by dependency/platform; reports
record runtime versions. Installations are separate from application requirements.
The experiment does not enable sensor actions or network services.

## Next engineering deliverable

Build continuous event segmentation and bounded recovery around the promising
learned waveform baseline. Replay the existing files from start to finish,
without using cue labels to start/reset detection; use labels only for scoring.
Measure event recall, wrong directions, return-pulse duplicates, misses and false
candidates during rest/blinks. Then shorten decision latency and add uncertainty
rejection. Keep model development and comparisons offline until that replay is
useful. Request a targeted fresh sensor check only after a measured improvement,
or to answer a specific gap the existing recordings cannot answer.

## Continuous follow-up

The next step is now implemented on `experiment/eog-continuous-detection`.
See [Continuous experiments](EOG_CONTINUOUS_EXPERIMENT.md). Continuous results
are lower than cue-aligned window accuracy and expose segmentation/recovery
failures; do not present the earlier41/45window score as live navigation accuracy.
