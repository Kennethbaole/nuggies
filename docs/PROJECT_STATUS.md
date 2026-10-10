# Current status and next session

Updated 2026-10-10.

Current experiment: opt-in guided waveform EOG mode is ready for a short live
check. Exact-runtime development replay:16/20 correct,3false candidates/275s.
Verification:167tests run,166passed,1optional skip; guided and normal desktop/mobile
browser checks passed. No Nano is currently detected and no new wearer/OLED test
was performed. Start with [the live-check guide](EOG_LIVE_CHECK.md).
The following main-baseline description predates this branch integration.

Latest pulled baseline: b1ceaa0. Reply generation now uses Qwen through Ollama
only; Gemini was removed. A Contacts page supports local contact profiles and
chat imports that supply style/examples to reply generation (no fine-tuning).
The pulled changes did not alter the EOG detector. Latest suite: 144 passing tests.
See [EOG detector review](EOG_DETECTION_PLAN.md) for the paper assessment and
recovery defect reproduced against existing recordings.

## Working implementation

Two BioAmp EXG Pills feed Nano R4 A0 (horizontal) and A1 (vertical). Firmware
samples both channels at 250 Hz and sends CSV over USB at 115200 baud. The
companion displays raw signals, supports labeled recordings and guided trials,
and shares phrase-wheel state with the phone and silent HUD views.

The experimental eye wheel test reads live serial data and focuses an eight-slot
radial wheel. Up targets the top slot (initial Hello), down targets bottom Back,
with left/right and diagonals mapped spatially. Gaze visual highlighting has been fully removed: no underline, glowing sector,
or filled gaze highlight. Detector state remains visible in the status/readouts. Gaze does not
activate phrases/utilities or speech. Keyboard/mouse confirmation remains
available; speech is disabled while the experimental test is active.

## Observed issue

Before visual feedback was removed, the underline changed but did not reliably correspond to intended
movements. Repeating the center/left trial did not resolve it. Usable directional
control has **not** been established. The cause is not yet isolated; this does
not by itself prove poor electrode signals or reversed wiring.

The current detector averages 15 samples (60 ms), learns a baseline for one
second, and triggers after 15 consecutive samples with either axis at least
1500 ADC counts from baseline. Positive horizontal assumes right; positive
vertical assumes up. At trigger time, subthreshold axes are zeroed and the vector
angle chooses the nearest of eight directions. The detector latches that initial
choice; it does not continuously update it as the gaze is held. An opposite
projection below -1000 counts for 10 samples or an eight-second timeout releases
hover. Quiet recovery is followed by another baseline warmup.

These fixed settings are not personal calibration. Different channel gains,
polarity, baseline drift, early axis crossing, return pulses, and blink activity
can affect the result. The trigger counts threshold activity without requiring
a consistent direction throughout that interval. AC-coupled movement pulses
cannot establish continuous absolute gaze position.

## Resume with offline algorithm development

1. Use the existing reviewed recordings for offline model development. The new
   [sequence experiment](EOG_SEQUENCE_EXPERIMENT.md) compares learned temporal
   templates and an LSTM with fixed-threshold logic. No new acquisition is
   required for this stage.
2. Extend the promising template baseline to continuous-stream event detection,
   using existing recordings to score return pulses, rest periods and blink
   interference without cue-based detection boundaries.
3. Verify polarity and compare channel noise, clipping, excursion amplitude,
   cross-axis leakage, and pulse timing. Fit separate per-axis thresholds/scales
   from measurements rather than guessing.
4. Update direction consistency, onset timing, and return handling using the
   labeled data. Start with four cardinal directions; add diagonals after those
   work. Existing calibration tools do not automatically configure live hover.
5. Evaluate unchanged settings on fresh trials, including blinks and neutral
   periods. Report hits, misses, wrong directions, false triggers, and latency.
6. Integrate deliberate confirmation only after navigation and blink rejection
   are reliable. The offline double-blink prototype is not live confirmation.

## Evidence and limits

The latest code passed 144 tests. Isolated browser checks exercised all eight
synthetic EOG directions through app ingest, hover release, no gaze activation,
and stop behavior. Underline styling was checked in the browser. These checks
verify software behavior, not biological direction accuracy. Earlier labeled
recordings and offline analysis are local and excluded from Git; see
[Acquisition](ACQUISITION.md) and [Validation](VALIDATION.md).

## Local session and restart

The latest local session uses http://127.0.0.1:8877 with serial port
/dev/cu.usbmodem1101. Ports may change on reconnection. At review time the server was running but serial was disconnected with a device
not configured error; recording and the eye-test toggle were off. Recheck the
port after reconnecting and restart the backend to load pulled Python changes.
No recording was started for the recent UI changes. To restart:

```sh
python3 -m backend.app --serial-port PORT --port 8877
```

Close other serial readers first. The test defaults off after restart. Preserve
private recordings locally and create new filenames for new sessions. Follow the
power and electrode precautions in [Acquisition](ACQUISITION.md) before resuming.

## Latest offline result

Forty-five reviewed windows were evaluated using all five leave-one-repetition-out
folds. For navigation (cardinal direction versus no direction during neutral/
blinks), current logic got 20/45, learned templates 41/45, and the initial LSTM
34/45. Templates recognized 18/20 cardinal trials and suppressed direction on
23/25 neutral/blink windows. These cue-aligned, same-session development results
are not continuous navigation validation or proof of cross-session accuracy.
Do not send the user back through the full acquisition protocol before exhausting
these existing-data experiments.

## Continuous algorithm branch

Further work is on `experiment/eog-continuous-detection`, not main. Continuous
replay now compares twelve variants without cue-driven resets; the strongest
waveform/rejection candidate recognized 16/20 movements with 6 false directions
over 275s negative exposure. Current live hover stalled in replay. No live control
was replaced. See [Continuous EOG experiments](EOG_CONTINUOUS_EXPERIMENT.md)
for results, reproducible commands, frozen raw-only replay and remaining work.
The branch suite passes 149 tests.


### Shape, retry and baseline follow-up (2026-10-10)

See [improvement roadmap](EOG_IMPROVEMENT_ROADMAP.md) for the requested guided-center/retry design,
research assessment and implementation priorities. New opt-in replay variants:
3s retry gate15/20 with5false directions;5s gate14/20 with4false over275s.
Existing waveform rejection remains16/20 with6false. Remembering rejected
labels, extra shape features and stable-only baseline replacement did not improve
the overall result; retain them as documented comparisons, not live defaults.
No application, OLED, confirmation or speech integration changed.


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


### Homepage speed-check follow-up

First live manual check: operator confirms intended cardinal responses and
retry for an untrained diagonal; no cue labels, so no numeric accuracy claim.
A new homepage button starts a recorded12-direction speed check after center.
Cue-to-response (includes reaction/UI delay) and candidate-window timing are
reported separately; early candidates are flagged. Detector settings remain
fixed.169tests run:168pass,1optional skip; homepage flow browser-checked.
See EOG_LIVE_CHECK.md for definitions and the live recording limitations.
