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
Leave sensor actions disabled during acquisition. Stop with Ctrl-C.

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
five blink trials, and a final 20-second neutral baseline. Total: 170 seconds.
Keep the page visible; timing does not pause when the browser is hidden.

Recording now also writes `<name>.trials.csv` with receipt timestamp, intended
label, trial ID, phase, and cue for every sample. The raw CSV and two-column
labels CSV remain compatible with existing tools. Return phases are explicitly
separate from movement phases. All sidecars stay local in recordings/. Cue times
are server instructions, not measured human reaction times or exact event onsets;
browser polling and USB buffering introduce timing uncertainty. Do not infer
classifier accuracy from cue labels alone. A single horizontal Pill cannot
validate the disconnected vertical channel or the two-channel blink detector.

The start button requires active recording and a connected input. Stop test ends
cues and restores Unlabeled, while raw recording continues. A disconnect ends
recording and stops the protocol; restart acquisition before a new test.
