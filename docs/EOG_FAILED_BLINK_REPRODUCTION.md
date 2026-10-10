# Exact reconstruction of the failed double blink

2026-10-10. Historical development evidence on reused participant data, not an
accuracy estimate or a new live check. No acceptance thresholds change here.

The user's right → center → deliberate double blink was missed because the
classifier received the **negative recovery tail after the blinks**. Both
positive blink peaks occurred during the preceding return event's 400 ms
refractory interval. The second blink was not cut off at the end of a one-second
window: the window started after both positive peaks.

## Reproduction and reset search

The private `live-eog-20261010T194946508017Z` recording and event log were replayed
against the historical detector source at `ee76de4`. Every possible final reset
index from 4060 through 15477 was considered. There were no clipping/timestamp
faults in that interval. A filter reset at row `r` emits its first 50 Hz frame at
`r+4`, then every five rows; 9,135 indices therefore cannot become Ready at 15477.
The remaining 2,283 indices were simulated through their first Ready transition.

Exactly three reset indices produce Ready at 15477: 13773, 13778 and 13963.
**Only 13778 reproduces all three target event indices, labels and metrics to
six decimal places.** The other candidates produce similar timings but different
distances/margins, and are not accepted as exact reproductions. This reconstructs
the last reset needed for these events; it does not recover earlier invisible
operator actions or identify which action caused that reset.

| Event | Emission / onset sample | Distance | Other-label margin | Horizontal energy fraction |
| --- | --- | --- | --- | --- |
| Right accepted | 15962 / 15732 | 0.023405 | 1.816352 | 0.576967 |
| Return, candidate left | 16292 / 16062 | 0.034311 | 3.111529 | 0.959253 |
| Double-blink label | 16622 / 16392 | 0.005388 | 1.218038 | 0.055910 |

Coordinates are zero-based global application/CSV sample indices for this file,
at nominal 250 Hz. The earlier `confirmation_armed_sample` was detector-local;
this reconstruction does not infer its global coordinate from the CSV alone.
The historical log explicitly records `uncertain_blink_match` after arming.

## What the exact window contains

The two filtered positive peaks are at samples 16312 and 16367, separated by
220 ms. Both have an 80 ms sampled half-height width. The second peak is about
0.54 times the first. Their maximum rise/fall velocity magnitudes are similar,
consistent with the reported deliberate double blink; this observation alone
does not validate an intent classifier.

The return emitted at 16292 sets the segmenter unavailable until 16392. At that
point the signal is already the second blink's negative rebound. The classified
50-frame window spans **16377–16622**, with reported threshold onset 16392.
It includes only the end of the second positive lobe, followed by negative
recovery. `blink_shape()` reports zero completed positive pulses and no pair.
Extending this window's end cannot recover the missing earlier peaks.

| Frozen template (zero-based index) | Label | Distance | Best shift |
| --- | --- | --- | --- |
| 28 | double_blink | 0.0053880618 | 0 frames |
| 21 | blink | 0.0065628665 | +2 frames |
| 19 | down | 0.0371943527 | 0 frames |

The winning double-blink template and closest single-blink competitor both
represent predominantly negative recovery tails. Their ratio is 1.218038, below
the gate's required 1.5. A close tail match cannot establish that two blinks
occurred. This is evidence of lost event context in both segmentation and these
labeled training templates, rather than evidence that the raw pair was absent.

An independent pulse stream needs to observe the vertical signal while the
navigation segmenter is refractory. It must still check arming, return timing,
expiry, faults and one-shot consumption, and reject up/return or single-blink
overshoot pairs. A late-window pulse-count override cannot solve this failure.

## Reproduce locally

Use the documented project Python from the repository root:

```sh
python -m scripts.eog_reset_search \
  --csv recordings/live-eog-20261010T194946508017Z.csv \
  --events recordings/live-eog-20261010T194946508017Z.events.jsonl \
  --profile recordings/guided-runtime-selected/candidate-profile.json \
  --first-reset 4060 --ready-sample 15477 --until 17100 \
  --target-samples 15962,16292,16622 --trace-start 16000 \
  --code-ref ee76de4 --out recordings/failed-double-blink-reproduction.json
```

The script loads historical source into an isolated module namespace without
checking out or changing runtime files. It requires a Git-ignored report path.
The private JSON contains exact windows, every template distance, per-label best
distances, onset baseline/rest offset and the 50 Hz trace. Its private CSV sidecar
includes samples 16000–17100, raw/filtered values and first-difference velocity.
No participant window or profile is committed.

Three analytic synthetic regressions cover the refractory blind interval,
similar single/double recovery tails, and rejecting timing-only replay matches.
They contain no real participant signal arrays.

For the one explicitly identified interaction: **one intended confirmation
missed, zero observed false confirmations**. This is not enough negative exposure
to estimate a false-confirmation rate. The existing reviewed-run simulation's
two prepare-interval selections remain a known false-confirmation risk; this
forensic change neither fixes nor conceals them.
