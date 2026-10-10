# Continuous EOG algorithm experiments

Branch: `experiment/eog-continuous-detection`, based on main `301cfef`.
Date: 2026-10-10. No new participant recording was required.

## What changed

Continuous replay now compares twelve variants: current live hover, two
outbound/return timing baselines, short/long waveform and feature matching,
adaptive recovery/return suppression, ambiguous-match rejection, a small LSTM,
and a three-layer 128-unit recurrent variant. A separate signed-onset alignment
experiment was also conducted and did not improve false-trigger counts.

The new filter smooths 60 ms at 250 Hz, updates its DC estimate continuously,
and emits 50 Hz frames. This prevents permanent waiting against a frozen baseline.
A consistent dominant-axis threshold crossing starts a fixed event window.
Learned examples come from training repetitions only, aligned to pulse onset.
Waveform matching allows +/-80 ms alignment shifts. Feature matching uses peaks,
mean, energy, slope and early/late differences.

The improved policy shortens recovery after blink-class events, suppresses
opposite-direction returns for four seconds after an accepted direction, and
can reject distant/ambiguous matches. The waveform rejection settings are
squared-distance >0.08 or blink-distance/direction-distance <1.5. They are
exploratory settings, not calibrated probabilities. A small or paper-sized LSTM
classifies the same event windows, with temporal mean/max pooling and a 0.6
minimum directional confidence. Models train for 100 epochs, seed 37.

These policies have costs: deliberate opposite movements within the suppression
interval can be discarded, one-second windows delay decisions, and confidence
rejection misses some intended movements. No diagonal or blink-confirmation
behavior is claimed.

## Evaluation boundaries

Detectors run **entire raw files**, without cue resets or label input. Causal
filtering also runs continuously. Only clipping and receipt gaps >500 ms reset
candidates. Unreviewed lead-in can affect detector state but is not scored.

Reviewed cue labels fit training examples and score held-out repetitions, not
segmentation. Five folds hold out one repetition across classes. Movement onset
must fall inside an intended movement cue to count. Wrong directions and repeat
correct events are counted separately. Neutral baseline chunks, prepare, return,
rest, and reviewed blink periods provide 275 seconds of negative exposure.
Invalidated blink trials and skipped double-blink cues remain excluded.

The dataset has only 20 cardinal trials and classes are concentrated in different
sessions. Repeated development comparisons reuse those recordings. Results are
**development replay measurements**, not an untouched final test, cross-session
validation, or intended-user evidence. Cue-to-emission includes reaction time;
physiological onset latency is unknown. False directions are candidates, not
spoken phrases or activated utilities.

## Results with activity-based training alignment

| Variant | Correct movements / 20 | Wrong directions during movements | False directions / 275s | Median cue-to-emission |
| --- | --- | --- | --- | --- |
| Current live hover | 0 | 0 | 0 | — |
| Gaze/return pairing, 0.7s minimum | 14 | 0 | 12 | 3.54s |
| Waveform, 1s, fixed recovery | 11 | 1 | 9 | 1.50s |
| Features, 1s, adaptive recovery | 15 | 0 | 9 | 1.50s |
| Waveform, adaptive recovery | 15 | 1 | 11 | 1.50s |
| **Waveform with rejection** | **16** | **0** | **6** | **1.51s** |
| Small LSTM with policy | 15 | 1 | 16 | 1.50s |
| Three-layer LSTM with policy | 14 | 0 | 23 | 1.51s |

The current comparator stalled in recovery. Its zero false directions reflects
unresponsiveness, not a good result. Earlier cue-reset experiments are a different
task and must not be substituted for these continuous scores.

The waveform/rejection candidate recognized left 4/5, right 3/5, up 4/5, down 5/5,
with no duplicate correct outputs. Its six false directions correspond to about
1.31/minute in scored negative exposure. This is an improvement, not reliable
finished control. Full JSON reports retain all twelve variants and events.

Signed-onset alignment held movement recall at 16/20 but increased false directions
to seven for the rejection candidate. It remains selectable for comparison; the
default is activity alignment. LSTM architecture alone did not reproduce the
paper's performance on these event labels and small recording set.

## Reproduce

Use the optional experiment environment described in [Sequence experiment](EOG_SEQUENCE_EXPERIMENT.md).
The private reviewed-run manifest is unchanged.

```sh
python -m scripts.eog_stream_experiment \
  --manifest recordings/reviewed-runs.json \
  --output recordings/continuous-experiment-final

# Fast comparison without recurrent training:
python -m scripts.eog_stream_experiment \
  --manifest recordings/reviewed-runs.json \
  --output recordings/continuous-fast \
  --variants current waveform-1.0 waveform-reject

# Alternative training alignment:
python -m scripts.eog_stream_experiment \
  --manifest recordings/reviewed-runs.json \
  --output recordings/continuous-signed --alignment signed
```

Each output contains report.json and candidate-profile.json. The profile fits all
reviewed movement examples and is **not** used for held-out fold scores. It is a
private development artifact, not a validated production model.

The frozen profile can replay a raw file with **no sidecars present**:

```sh
python -m scripts.eog_candidate_replay recordings/trial.csv \
  --profile recordings/continuous-experiment-final/candidate-profile.json \
  --output recordings/candidate-events.json
```

This CLI never reads cue files, connects to hardware, changes RingState, confirms
anything or speaks. A raw-only replay of 68,873 samples completed successfully.
All artifacts remain local under Git-ignored recordings/.

## Tests and next work

149 tests pass, including direction consistency, continuous DC recovery, clipping,
bounded rearm, opposite-return expiry, ambiguous rejection, fast blink rejection,
paired-return timing, scoring of wrong/duplicate directions, negative exposure,
and exclusion of other folds. No live sensor, Jetson or physical HUD test was
performed on this branch.

Next: inspect the four missed movements and six false directions in the private
report; refine event onset and uncertainty using training data; compare additional
negative sessions without relabeling them as a new independent test. Then expose
the frozen candidate as an opt-in diagnostic stream before connecting navigation.
The existing app detector is unchanged. Gaze highlighting stays removed.
