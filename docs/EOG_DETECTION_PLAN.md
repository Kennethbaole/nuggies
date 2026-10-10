# EOG detector review and next implementation

Reviewed 2026-10-10. The live detector has not been changed by this review.
An offline trained-template/LSTM comparison now exists: see
[Sequence experiment](EOG_SEQUENCE_EXPERIMENT.md). Use existing recordings for
continuous replay development before asking for further acquisition.

## Research reference

Zendehdel et al., *Hands-Free UAV Control: Real-Time Eye Movement Detection Using
EOG and LSTM Networks*, DOI [10.1109/ACCESS.2025.3578558](https://doi.org/10.1109/ACCESS.2025.3578558).
The [Missouri S&T record](https://scholarsmine.mst.edu/mec_aereng_facwork/6199/)
identifies the published version. Publisher/repository PDFs were inaccessible
from this session; methods and results were read in the
[author-version full text](https://www.researchgate.net/publication/392578039_Hands-Free_UAV_Control_Real-Time_Eye_Movement_Detection_Using_EOG_and_LSTM_Networks).

Their setup uses two BioAmp EXG Pills and Jetson Orin Nano. Training uses timed
screen targets and cue-assisted blink labels. Their normalized, denoised sequences
feed a three-layer, 128-unit-per-layer LSTM with gaze and blink outputs. Reported
Jetson results are 98.4% command accuracy, 98.1% blink accuracy and 38.87 FPS.
These are study results, not Nuggies validation or transferable threshold settings.

## What our recordings support

Local recordings and aligned sidecars already cover horizontal gaze, vertical
gaze, single blinks and deliberate double blinks. Reuse the completed reviewed
runs; exclude interrupted runs and skipped double-blink cues. Cue labels indicate
intent and do not establish precise physiological onset.

Existing waveform review shows that upward-gaze peaks can also be narrow and
biphasic. Positive-peak width, negative/positive ratio, and horizontal response
are useful features, not independently reliable blink labels. Whole movement/
return windows can contain extra blinks; segment and inspect actual events before
training. A higher ADC resolution does not establish cleaner electrode signals.
No trained classifier has yet been compared with our baseline on held-out data.

## Concrete live-detector problems

The current detector uses fixed thresholds and assumes channel polarity. It
latches the first threshold-derived angle, even when a second axis responds
later, and does not require consistent direction through the trigger interval.

After return or timeout, release waits for 100 samples within 600 counts of the
frozen baseline. There is no recovery timeout or baseline reacquisition while
waiting. Replay of an earlier completed horizontal run reproduced prolonged
release after an early false candidate. This is a software recovery defect, not
proof that the sensor hardware is unsuitable. Replay is offline reproduction,
not an explanation proven for every live misclassification.

## Implementation order

1. Add bounded recovery and baseline reacquisition from a stable window. Changing
   the baseline during motion must not manufacture a new direction. Expose
   recovery/quality status and refuse uncertain candidates.
2. Fit polarity and independent channel scales/thresholds from reviewed neutral
   and cardinal trials. Connect an explicit hover profile; current classifier
   calibration files do not configure live_wheel.py.
3. Segment onset, movement pulse, return and blink candidates. Require direction
   consistency and compare both normalized channels over a short decision window.
   Start with four directions; enable diagonals after cardinal results hold.
4. Compare amplitude, width, slope, opposite-lobe timing and size, recovery time,
   and cross-channel energy. Allow an unknown outcome rather than forcing all
   events into gaze or blink. Measure the latency added by waiting for shape.
5. Compare a calibrated temporal rule baseline with a small feature classifier
   if labels support it. Split by recording session/trial before generating
   overlapping windows; never mix adjacent windows between train and test.
6. Test unchanged settings on fresh recordings with blinks, returns, held gaze,
   neutral periods and reattached electrodes. Report wrong directions, misses,
   false triggers per minute and latency, not just accuracy.

Preserve spatial up/down/left/right navigation as the intended interaction. No
long-blink command is currently wired into this hover mode, so removing one does
not fix the present issue. Keep confirmation separate and speech off during
navigation validation. Gaze highlighting has been removed. Double-blink confirmation remains offline and unvalidated.

## Next sensor session

After the existing-data replay work demonstrates an improvement, check port and
channel transport, confirm electrode labels/placement, then record
neutral, left/right/up/down with returns, and separate single/double blinks. Use
fixed screen targets and several repetitions with explicit cues; review existing
recordings first to determine which additional trials are actually needed. A
short fresh session after software recovery/calibration changes is the acceptance
check. Keep all recordings and derived per-person reports local and Git-ignored.
