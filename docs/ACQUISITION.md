# Raw acquisition and recording

A0 is horizontal and A1 is vertical. USB serial runs at 115200 baud and sends
`horizontal,vertical` followed by two integer ADC counts (0–16383) per line.
Both Nano R4 sketches use 14-bit resolution and sequential channel reads.
`firmware/nano_r4_two_channel` is a roughly 10 Hz voltage-check sketch.
Use `firmware/nano_r4_eog_250hz` for eye-movement trials: it schedules one
A0/A1 pair every 4 ms (250 pairs per second). Acquisition timestamps are host
receipt times, so USB batching can make individual timestamp gaps uneven.
Check the sustained received sample rate rather than assuming every gap is 4 ms.

`SerialADCSource` skips malformed rows and buffers partial lines with a bounded
buffer. Five seconds without valid data raises an error. `ADCRecorder` flushes
raw samples to CSV; `CSVReplaySource` preserves timestamps, source and units.
The fixture in examples/nano_r4_bench.csv is voltage bench data, not eye signals.
Raw counts never go directly into a normalized direction classifier.

Install pyserial only for live acquisition:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m scripts.doctor
```

Close Arduino Serial Monitor before Python opens the port. Discover the actual
port; do not assume a fixed device name. A disconnect stops acquisition and
requires restart. Start browser recording with:

```sh
mkdir -p recordings
.venv/bin/python -m backend.app --serial-port /dev/cu.usbmodem101 --port 8877 --record recordings/eog-trial.csv
```

Use the actual serial port. Recording starts immediately and refuses to overwrite
existing files. Open Signal workspace and select a Trial label before each block.
The raw CSV and companion `.labels.csv` stay in the Git-ignored recordings folder.
Leave sensor actions disabled during acquisition. Choose **Stop recording · keep monitor open** to close the recording files
while keeping the live webpage and serial monitor running. Ctrl-C shuts down the
whole server and makes the webpage unavailable. A new recording currently requires
restarting acquisition with a new `--record` filename.

For an initial single-Pill session, connect OUT to A0 and ignore the floating A1
channel. Record 15 seconds of Neutral, then five Left trials and five Right trials
(each: look in the labeled direction for 2 seconds, return to center for 3).
Choose Neutral during center intervals if practical; otherwise each label describes
the whole trial block, including returns. Record five ordinary blinks spaced
3 seconds apart under Blink, then finish with 15 seconds of Neutral. Keep the head
and cables still. A blink label identifies an intended trial, not a precise onset.
Horizontal recordings can contain blink artifacts; a spike alone does not identify
a blink or direction. Review repeatability and neutral false triggers before fitting
thresholds or enabling navigation. Use sample order and verified sampling rate for
waveform timing; receipt timestamps alone are unsuitable for precise blink duration.

Before connecting electrodes, confirm the exact Pill revision, electrode leads,
connectors and body-connected power arrangement against manufacturer guidance:
https://docs.upsidedownlabs.tech/hardware/bioamp/bioamp-exg-pill/index.html
Record placement, firmware, rate and power setup privately with each trial.
No body-connected acquisition has been validated by software tests.

For a larger live trace, open Signal workspace and choose **Expand signal
workspace**. The view fills the window and retains trial labeling and the current
recording. Choose **Close expanded view** or press Escape to return.

## Guided acquisition

With live serial recording running and sensor navigation disabled, expand the
signal workspace and choose **Start guided test**. Follow the on-screen cues;
manual labeling is locked until completion or Stop test. The server schedules a
5-second preparation, 20-second neutral baseline, five alternating left/right
trials (3-second center preparation, 2-second sideways hold, 4-second return),
five blink trials, and a final 20-second neutral baseline. Total: 175 seconds. Blink cues last 2 seconds to allow reaction time.
Keep the page visible; timing does not pause when the browser is hidden.

Recording now also writes `<name>.trials.csv` with receipt timestamp, intended
label, trial ID, phase, cue, and unique run ID for every sample. The raw CSV and two-column
labels CSV remain compatible with existing tools. Return phases are explicitly
separate from movement phases. All sidecars stay local in recordings/. Cue times
are server instructions, not measured human reaction times or exact event onsets;
browser polling and USB buffering introduce timing uncertainty. Do not infer
classifier accuracy from cue labels alone. A single horizontal Pill cannot
validate the disconnected vertical channel or the two-channel blink detector.

The start button requires active recording and a connected input. Stop test ends
cues and restores Unlabeled, while raw recording continues. A disconnect ends
recording and stops the protocol; restart acquisition before a new test.

## Offline glance-and-return prototype

`backend.paired_glance` is an experimental single-channel detector used for horizontal offline replay
and, only with explicit opt-in, the supervised live wheel test described below. It smooths A0 over 100 ms, tracks a slow resting baseline,
then requires a sustained excursion, an opposite excursion 0.8–5 seconds later,
and 200 ms near baseline before emitting one PREV (negative-first) or NEXT
(positive-first). A 500 ms cooldown follows. Baseline adaptation is frozen during
a candidate. Incomplete candidates expire without a command. A1 is never read.
This detects a signal pattern, not absolute eye position; it deliberately requires
a glance, hold, and return. A user who does not return receives no command.

```sh
python3 -m backend.review_glances recordings/eog-trial.csv --threshold 1500
```

Replay reports events and optional trial-phase metadata as JSON to stdout.
Metadata is checked for alignment and used only for reporting, never for detection.
Save reports under recordings/ to keep them local. Sampling time uses sample index
and `--fs` (default 250); verify the real acquisition rate first. Defaults are
exploratory: independent recordings must establish detection, duplicate/false
commands, missed movements, and latency before enabling navigation. Fast paired
artifacts are rejected by timing, but slower artifacts can mimic the required
pattern. Ordinary blinks are not SELECT commands in this prototype. The live app
continues to use its existing classifier and remains monitoring-only unless
explicitly configured otherwise; this prototype is only used live through the explicit experimental wheel-test toggle.

The recording indicator distinguishes monitoring-only from local recording.
**Stop test** ends cues but keeps recording; **Stop recording** finalizes capture
and ends cues while keeping the server and live trace available. Escape in the
expanded workspace closes that view without navigating the phrase ring.

## Vertical gaze versus blink comparison

Choose **Up/down, single and double blinks** in the guided Test selector for a
225-second protocol. It has initial/final 20-second baselines and five trials
each of Up, Down, single Blink, and Double blink. Center returns have their own
phase. Double-blink cues ask for two natural blinks about half a second apart.
This records intended trials; no blink action or selection is enabled. Keep the
page visible and allow an uncertain or mistimed run to be excluded during review.

Compare local waveforms with:

```sh
python3 -m backend.vertical_features recordings/eog-trial.csv > recordings/vertical-features.json
```

This offline tool reports positive/negative peak sizes, negative-to-positive
ratio, signed time between extrema, positive half-height width, positive peak
candidates, horizontal-to-vertical amplitude ratio, and clipping. Guided windows
include movement plus its return/rest; manual windows cover entire label blocks
and can contain several events. A run ID distinguishes repeated protocols. Do
not interpret extrema from different events as the rebound of one blink. Cues
are not exact onset annotations. Features use a 100 ms causal moving mean and
the median of the preceding second as baseline; this filtering changes measured
widths and amplitude ratios and needs checking against raw waveforms.

Hypothesis: gaze and recentering may yield a delayed, more balanced opposite
lobe, whereas a blink may be shorter and asymmetric. This is a feature hypothesis,
not a guaranteed distinction. Quick gaze returns, stronger blinks, drift, changes
in electrode placement, and simultaneous gaze/blink activity can confound it.
Natural single blinks must remain noncommands; a double-blink pattern also needs
validation against ordinary successive blinks and vertical gaze before SELECT.
No universal amplitude-ratio cutoff or double-blink classifier is implemented.
Research measures blink amplitude, duration, and shape rather than relying only
on amplitude: [BLINKER](https://pmc.ncbi.nlm.nih.gov/articles/PMC5289990/) and
[blink-type comparison](https://pubmed.ncbi.nlm.nih.gov/10407913/).

For a separate double-blink capture, choose **Double blinks only · 1m 15s**.
This protocol has a 5-second preparation, 10-second baseline, five double-blink
trials (3-second preparation, 3-second blink cue, 4-second rest), and a final
10-second baseline. Follow each cue once; baseline single blinks are allowed.
If a section was skipped, exclude its labeled windows rather than treating the
cue label as proof the movement happened. This remains recording-only.

### Close double-blink peak review

The default 250 ms peak separation can merge fast blink pairs. Compare alternate
filtering and candidate spacing explicitly rather than treating missing peaks as
missing blinks:

```sh
python3 -m backend.vertical_features recordings/trial.csv --smoothing-ms 20 --peak-threshold 1000 --peak-gap-ms 80 > recordings/close-peaks.json
```

Reports include all analysis settings and `positive_peak_candidates`. Reducing
smoothing or spacing also exposes noise and secondary lobes of single blinks;
two candidate peaks are not proof of two physical blinks or deliberate intent.
Compare unchanged settings on single-blink, gaze and resting recordings before
using peak pairs for SELECT. The default smoothing remains 100 ms.

## Offline double-blink candidate detector

`backend.double_blink` is an experimental streaming two-channel detector;
`backend.review_blinks` replays complete local recordings without issuing live
commands. It uses 20 ms smoothing and slow baselines, requires two separate
positive pulses with compatible widths/peak ratios, 120–650 ms between peaks,
limited horizontal activity, and quiet recovery. Continuous multi-peak pulses,
clipping, extra activity during recovery, broad pulses and isolated blinks are
rejected. Baseline freezes while a candidate is pending; one-second cooldown
follows an emitted candidate. Defaults are development settings, not validated
personal calibration. Polarity is configurable.

```sh
python3 -m backend.review_blinks recordings/trial.csv > recordings/blink-review.json
python3 -m backend.review_blinks recordings/trial.csv --windows recordings/trial.blink-windows.json > recordings/blink-evaluation.json
```

An optional evaluation file is a JSON list of nonoverlapping intervals containing
`start_sample` (inclusive), `end_sample` (exclusive), and `expected` (`"SELECT"`
or `null` for no command). Optional `name` identifies a trial. Use only reviewed
intervals, excluding skipped/mistimed trials; metadata labels alone do not prove
intent. The report includes expected-pair hits/misses, duplicate candidates,
negative-window false candidates and exposure time, and unscored candidates.
All interval boundaries must fit the recording. Candidate timestamps use sample
index/fs and include processing/recovery delay. Trial metadata is aligned before
reporting and never drives the detector. Keep reports and evaluation files local.

Known limitations: false candidates have occurred during gaze/return activity,
and a close deliberate pair can be rejected when it never drops enough between
peaks. Natural successive blinks can resemble deliberate pairs. No morphology
rule can establish intent by itself. Evaluate negative recordings as well as
successful pairs, then test unchanged settings on fresh data. These development
recordings are not held-out validation. The tool emits SELECT *candidates* in JSON;
it is not connected to the live app, which remains monitoring-only. No gesture
threshold or live navigation behavior is changed by running replay.

## Supervised live directional hover

Choose **Start experimental eye wheel test** with both Pills connected and the
250 Hz firmware. Live serial input is required; guided tests and calibrated
navigation must be off. Rest at center for one second before looking toward a slot.

| EOG direction | Highlighted wheel position |
| --- | --- |
| Up (positive A1) | Top, slot 0 (Hello on the initial home page) |
| Up-right | Slot 1 |
| Right (positive A0) | Slot 2 |
| Down-right | Slot 3 |
| Down (negative A1) | Bottom, slot 4 (Back) |
| Down-left | Slot 5 |
| Left (negative A0) | Slot 6 |
| Up-left | Slot 7 |

Eight triangular direction sectors stay invisible until gaze hover is detected.
The corresponding sector lights up turquoise behind its slot, and the slot gets
a matching highlight. Sectors clear when hover releases, the mode stops, or the
serial connection becomes stale. No phrase, Back action, navigation, or
speech is activated by gaze. Confirm with existing mouse/keyboard controls when
needed. Speech remains disabled while this test is on. The page shows smoothed
horizontal/vertical deviations in ADC counts and the detector phase.

This is experimental pulse-based direction detection, not absolute gaze tracking.
A 60 ms smoothing window and sustained threshold crossing trigger the first
highlight; both axes must exceed 1500 counts for a diagonal. Polarity assumes the
verified placement and must be checked for each setup. AC-coupled signals decay
while gaze is held, so the hover is latched until an opposite return pulse or an
eight-second timeout. Return to center and rest before another direction. A return
pulse clears the hover outline; keyboard focus remains at the last enabled slot.
Clipping, sample gaps, stopping, and serial failure reset the detector.

Blink spikes can still resemble vertical gaze. Diagonal timing, individual
thresholds, and blink rejection need live validation; this mode does not use the
offline double-blink classifier. Stop the test to disable sensor highlighting.
Recording remains independent and the mode defaults off after restarting.
