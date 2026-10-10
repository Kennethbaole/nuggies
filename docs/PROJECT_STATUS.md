# Current status and next session

Updated 2026-10-10.

## Working implementation

Two BioAmp EXG Pills feed Nano R4 A0 (horizontal) and A1 (vertical). Firmware
samples both channels at 250 Hz and sends CSV over USB at 115200 baud. The
companion displays raw signals, supports labeled recordings and guided trials,
and shares phrase-wheel state with the phone and silent HUD views.

The experimental eye wheel test reads live serial data and focuses an eight-slot
radial wheel. Up targets the top slot (initial Hello), down targets bottom Back,
with left/right and diagonals mapped spatially. Gaze only underlines the detected
label: glowing sectors and filled gaze highlights were removed. Gaze does not
activate phrases/utilities or speech. Keyboard/mouse confirmation remains
available; speech is disabled while the experimental test is active.

## Observed issue

In live use the underline changes, but does not reliably correspond to intended
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

## Resume with calibration, not more UI changes

1. Recheck the setup and acquire a quiet center baseline. Keep wheel control off
   while recording labeled measurements.
2. Record separate left, right, up, and down trials, with explicit center returns
   and several repetitions. Record blinks separately; distinguish intended gaze
   from its return in the review.
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

The last full suite passed 133 tests. Isolated browser checks exercised all eight
synthetic EOG directions through app ingest, hover release, no gaze activation,
and stop behavior. Underline styling was checked in the browser. These checks
verify software behavior, not biological direction accuracy. Earlier labeled
recordings and offline analysis are local and excluded from Git; see
[Acquisition](ACQUISITION.md) and [Validation](VALIDATION.md).

## Local session and restart

The latest local session uses http://127.0.0.1:8877 with serial port
/dev/cu.usbmodem1101. Ports may change on reconnection. The server was left
running; its availability and eye-test toggle should be checked on return.
No recording was started for the recent UI changes. To restart:

```sh
python3 -m backend.app --serial-port PORT --port 8877
```

Close other serial readers first. The test defaults off after restart. Preserve
private recordings locally and create new filenames for new sessions. Follow the
power and electrode precautions in [Acquisition](ACQUISITION.md) before resuming.
