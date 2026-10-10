# EOG improvement plan and replay evidence

Updated 2026-10-10. Branch: `experiment/eog-continuous-detection`.
This guide supplements [continuous experiments](EOG_CONTINUOUS_EXPERIMENT.md)
and the central [NUGGET handoff](../NUGGET.md).

## Why the approach changed

Amplitude thresholds were useful to establish acquisition and polarity, but we
spent too long tuning them before evaluating complete event waveforms. Amplitude
alone cannot resolve overlapping blink/up signals. Recent continuous experiments
already use waveform matching, temporal features and recurrent models; they are
not connected to the live application. Thresholds now locate possible events,
while waveform and recovery logic determine what, if anything, they mean.

## Requested user experience

1. Initial setup explicitly asks the wearer to look straight ahead. Collect
   3–5 seconds of clean center data; exclude blink/activity samples. Estimate
   baseline and resting noise robustly, retaining session/channel metadata.
2. During use, correct drift slowly using quality-checked stable intervals.
   Freeze corrections through movement, blink and recovery intervals. Adaptation
   must be bounded, and cannot overwrite polarity/gain calibration.
3. Reject uncertain commands. Show `Look center / Retry` once for an ambiguous
   attempted gesture, pause navigation/confirmation, and resume after sufficient
   clean settling data. Ordinary blinks/resting noise should not repeatedly warn.
4. Track outbound, blink, return and recovery separately. A rejected outbound
   event must not make its return a fresh command. Do not trust its guessed
   direction as ground truth either.

Quiet voltage is not proof of physical gaze center: the analog chain and digital
DC removal can settle during a held off-center gaze. The prompt supplies the
behavioral reference; electrical settling only checks signal stability. An
explicit recenter action remains available if adaptation cannot recover.

This is a design, not an installed OLED feature. The app, physical OLED bridge,
confirmation and speech paths remain unchanged by these experiments.

## Experiments conducted using existing recordings

Same five repetition folds, continuous raw streams and strict cue scoring as the
previous comparison. No new wearer recording. Reports remain Git-ignored:
`recordings/recovery-shape-stable/report.json` and
`recordings/retry-comparison/report.json`. Labels fit training examples and score
held-out regions; they never drive event segmentation or retry/settling state.

| Variant | Correct / 20 | Wrong during movement | False directions / 275s |
| --- | --- | --- | --- |
| Existing waveform rejection | 16 | 0 | 6 |
| Remember rejected direction for return suppression | 15 | 0 | 7 |
| Explicit shape features, adaptive recovery | 16 | 1 | 13 |
| Existing compact features, adaptive recovery | 15 | 0 | 9 |
| Rejection plus 3s clean settling gate | 15 | 0 | 5 |
| Rejection plus 5s clean settling gate | 14 | 0 | 4 |
| Stable-only baseline, 3s, rejected-direction suppression | 8 | 5 | 84 |
| Stable-only baseline, 5s, rejected-direction suppression | 8 | 5 | 84 |

These are reused-data development measurements, not independent validation.
Three of the original six false directions are cue-boundary ambiguous. Do not
interpret each false count as a proven unintended physical movement. All new
variants have opt-in names; the default replay policy/profile is unchanged.

The explicit feature variant adds half-height occupancy, peak timing, opposite
lobe strength/timing, tail residual and channel energy ratio to existing features.
It improves recall over compact features but worsens false directions. Whole
waveforms already encode shape; adding hand-selected shape features is not
inherently better. No paper-equivalent wavelet implementation is claimed.

The rejected-direction variant illustrates why an uncertain label should not
become trusted recovery direction. Retry gates instead suppress direction output
until 3 or 5 seconds of clean 50 Hz frames accumulate within a rolling interval
of twice that duration. Frames require both filtered axes below 400 counts and
frame changes below 100 counts. Activity pauses accumulation; stale clean frames
expire. The gate does not classify every excluded excursion as a blink, prove
center, or automatically recalibrate baseline. It can remain waiting if the
signal never settles; live UI needs explicit reset/contact-check guidance.

The stable-baseline variants are deliberately conservative: 60ms smoothing,
initial first-sample baseline, a 400-count activity/100-count slope gate, 500ms
mask, robust clean-window median/MAD and bounded updates of at most 2 counts per
20ms frame. Large drift falls outside the update gate, leaving persistent offsets
and retriggers. These replays do not include a wearer responding to a center
prompt; they test a simple unattended correction, not the complete requested
setup. They show why replacing continuous DC handling with a frozen baseline is
not ready for adoption. A hybrid signal path is the next baseline experiment.

Reproduce:

```sh
python -m scripts.eog_stream_experiment \
  --manifest recordings/reviewed-runs.json \
  --output recordings/retry-comparison \
  --variants waveform-reject waveform-retry3 waveform-retry5 features-policy shape-policy

python -m scripts.eog_stream_experiment \
  --manifest recordings/reviewed-runs.json \
  --output recordings/recovery-shape-stable \
  --variants waveform-reject waveform-recovery shape-policy stable-3-recovery stable-5-recovery
```

Use the optional experiment environment documented in the continuous guide.

## Useful research and limits

[Wei et al., Sensors 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12609384/)
use detrending, a 200ms median filter and Haar-wavelet blink identification. Their
blink criterion pairs positive/negative wavelet peaks within 0.5s, followed by
interpolation. Borrow blink masking and timing analysis. Their offline processing
uses future samples, so streaming versions need explicit buffering/latency;
200ms smoothing must be tested for lost blink detail. This is not validation of
our thresholds or quiet-only recentering. Their instructed calibration is useful
motivation for accessible, guided setup.

[SUNY prototype](https://suny.technologypublisher.com/tech/Smart_Glasses_with_On-Device_Eye-Movement_Control_and_Neuro-Health_Monitoring)
describes wavelet drift correction, median filtering and Haar-based saccade
analysis. This motivates a lightweight wavelet comparator. Its technology summary
is not a reproducible accuracy benchmark or a complete implementation.

[MIT Lincoln Laboratory](https://www.ll.mit.edu/partner-us/available-technologies/eye-tracking-free-living-conditions)
uses EOG plus gyroscope data for continual calibration. An IMU could help account
for head motion later; the present two-channel stream lacks that reference.

[Wearable Sensing](https://wearablesensing.com/eog/) supports conventional
horizontal/vertical electrode placement, using different acquisition hardware.
Do not transfer their voltage thresholds, bandwidth or performance to our Pills.

## Implementation order and acceptance evidence

| Priority | Improvement | What establishes progress |
| --- | --- | --- |
| 1 | Guided center, reason-coded rejection and explicit recovery state | No command from an uncertain gesture or its return; recovery visible; normal blinks quiet; no permanent hidden stall |
| 1 | Hybrid drift handling | Keep causal transient/DC separation; robust center/noise estimates update only when eligible; compare drift tracking, false triggers and recovery time |
| 1 | Blink-aware waveform classifier | Compare Haar features and timing/shape jointly across both channels; overlapping classes may remain unknown |
| 1 | Better rejection | Compare nearest competing direction as well as blink distance; report coverage versus false commands rather than calling distance a probability |
| 2 | Adaptive event boundaries | Shorter decisions only when evidence is stable; retain enough trailing waveform for blink/return discrimination; include processing delay |
| 2 | Movement/return state machine | Replace unconditional 4s opposite suppression with observed recovery, retaining intentional opposite commands after recentering |
| 2 | Noise-relative thresholds and channel scaling | Learn robust resting noise and per-axis scale/polarity from reviewed training/setup data; freeze during gestures, avoid chasing artifacts |
| 2 | Cross-channel consistency | Reject motion/contact artifacts and ambiguous diagonals; do not assume all blinks have zero horizontal response |
| 2 | Double-blink confirmation | Detect individual blinks first, then test pair timing and false confirmation; ordinary single blinks never activate phrases |
| 2 | Signal-quality handling | Expose clipping, dropouts, timestamp gaps and unstable/contact-like artifacts; reset partial events and inhibit commands during faults |
| 2 | Opt-in diagnostic integration | Stream label, reason, state and timestamp to app/HUD first; no speech/confirmation until end-to-end behavior is verified |
| 3 | Evaluation improvements | Preserve strict cue score, add separately labeled boundary sensitivity, per-class recall, retries, false commands/minute and recovery duration |
| 3 | Stronger model comparison | Compare templates, regularized feature classifiers and wavelets before larger networks; split by session/person when data allows |
| Later | IMU/head-motion reference | Requires new synchronized acquisition and evidence; MIT-style calibration cannot be reproduced from quiet EOG alone |

Use existing recordings first, including negative periods. Do not relabel invalid
runs as clean truth or use future cue labels to reset detectors. Class/session
confounding and repeated reuse limit current conclusions. After a candidate
survives replay, run a short targeted live task with fixed settings and retain it
as a separate evaluation; avoid asking the wearer to repeat the entire suite.
All raw data stays private. Gaze highlighting stays removed.

## Verification

Base environment: 153 tests run, 152 passed and one optional NumPy shape test
skipped. Experiment environment: all nine temporal tests passed, including the
shape test. Full replay comparisons completed. No physical OLED, live sensor or
wearer response to the proposed recovery prompt was tested.


### Integrated guided EOG mode — 2026-10-10

The experimental branch now has opt-in app integration using --eog-profile:
three-second guided center, hybrid DC/rest estimates, five-second retry,
recovery/return suppression, uncertain horizontal blink handling and quality
faults. Cardinal focus only; no automatic confirmation or speech. Browser HUD
shows status without gaze highlighting. Private raw/decision logs and a short
readiness-aware live protocol are available. Selected exact-runtime replay:
16/20 correct,0wrong/duplicates,3false candidates/275s (two boundary ambiguous,
one blink-related up); median cue-to-emission1.51s. Existing main behavior
without the profile flag is unchanged. Physical OLED status adapter is untested.
See [live-check guide](EOG_LIVE_CHECK.md) for evidence, launch instructions and remaining
limitations. Earlier statements that no integration exists are historical.
