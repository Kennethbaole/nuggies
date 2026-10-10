# Signal alternatives: development evidence

2026-10-10. `scripts.eog_signal_comparison` runs the existing three reviewed raw
recordings continuously, fits templates inside each repetition holdout, and scores
cue phases afterward. The comparison table is in `EOG_CONTINUOUS_EXPERIMENT.md`.
No alternative filtering or direction classifier was adopted: none reduced both
misses and false directions. All runtime detection remains pure Python; the
comparison optionally uses NumPy offline.

## Signal processing findings

Raw resting blocks contain a spectral peak at nominal 60 Hz. Median 59–61 Hz power
as a fraction of 1–100 Hz power was 8.71%, 0.99%, 1.57% horizontally and 0.41%, 0.08%,
0.13% vertically for sessions 4/5/6. These estimates assume the sketch's nominal
250 Hz; host timestamps cannot independently verify ADC timing. A 15-point moving
average has nulls at multiples of 250/15 Hz, so 60 Hz is attenuated but not nulled.
LP10/LP15 plus a 60 Hz notch reduced false directions from three to two but left
four misses and two negative-phase confirmations. LP20 added a miss. Median3 did
not improve directions and added a negative-phase confirmation. None replaces the
current filter in this change.

The DC tracker has coefficient .004 per 250 Hz sample: its ideal discrete decay
time constant is `-1/(250*log(.996))`, approximately 1.0 s. Even a held electrical
step therefore becomes a decaying pulse after this software stage. The Pill's
analog filtering also shapes the waveform; software quiet does not prove gaze
center. The existing stable-only baseline variant stalled on these files and
missed all 20 scored directions, so it was rejected.

The manufacturer's [Pill v1.0 documentation](https://docs.upsidedownlabs.tech/hardware/bioamp/bioamp-exg-pill/index.html)
confirms configurable gain/bandpass and default EEG/EOG configuration. Its
[published schematic](https://github.com/upsidedownlabs/BioAmp-EXG-Pill/blob/main/hardware/BioAmp-EXG-Pill.kicad_sch)
annotates an 11× instrumentation stage and 1000× bandpass stage, with configurable
R6/R12/C5 and JP1. Those are nominal circuit annotations, not a measured gain or
passband for the wearer's assembled boards. A numeric analog cutoff has not been
verified here. Do not confuse the manufacturer's [0.5–19.5 Hz EOG software filter](https://github.com/upsidedownlabs/BioAmp-EXG-Pill/blob/main/README.md)
with the Pill's hardware passband. Measuring/deriving the actual configured analog
transfer function remains open; no guessed cutoff was put into the live detector.

## Shape, templates and features

[Bulling, Ward, Gellersen and Tröster, TPAMI 33(4), 741–753, 2011](https://www.collaborative-ai.org/publications/bulling11_pami/)
is the verified citation (DOI 10.1109/TPAMI.2010.86). Their [paper](https://www.collaborative-ai.org/publications/bulling11_pami.pdf)
uses Haar CWT for saccades and opposite-sign wavelet peaks with a bounded interval
for blinks. It supports examining temporal shape; it does not validate our ADC
thresholds or voluntary double-blink confirmation. Our derivative pulse stream is
an engineering adaptation, not a reproduction of their CWT detector. The Haar
weights .1/.25 and multi-scale widths 3/6/10 worsened this replay's tradeoff.

Second-half waveform distance reduced false directions but added misses. Nearest-two
per-label averaging and shrinkage LDA lost more directions. Narrow-band DTW retained
16 hits but doubled negative-phase confirmations. Extending active windows to at most
1.6 s and resampling to 50 frames added a miss; it cannot restore peaks that occurred
before a refractory window began. This extension experiment reuses 1 s training
windows and is a bounded perturbation, not an optimized variable-duration model.

The LDA export is private JSON containing feature scaling, weights and intercepts;
inference is pure Python dot products. Features include per-axis amplitudes, signed
area, half-height width, slopes, turning points, return time, energy ratio, pulse count
and gap. Scores are uncalibrated. No model export is committed or loaded live.

On five training-aligned windows per instructed class, median vertical half-height
width was 100 ms for up and 80 ms for single blink; ranges overlapped (80–140 versus
40–140 ms). Median post-peak return time was 120 versus 60 ms, also overlapping.
These window-derived values include segmentation effects. Neither width nor symmetry
alone provides a reliable up rejection rule. Two-lobe negative-cue candidates include
separate pulse-like events in prepare/return intervals; cue labels do not reveal
whether the wearer blinked naturally or deliberately then. Rejecting poor template
matches and retaining arming context is essential.

Bounded online gain scaling (first three accepted events, 0.8–1.25 range) and
blink-derived vertical→horizontal regression did not improve direction misses/false
events. Noise-adaptive blink floors are enabled only in the independent pulse path;
no automatic electrode polarity or profile normalization was enabled. A short optional
blink calibration is not required now. If needed later, offer three single and three
double blinks within 30 s after the transport and morphology issues are resolved.

## Evidence limits that change what can be claimed

Leave-one-repetition-out is reported. Leave-one-session-out is **not identifiable**:
session 4 alone contains reviewed left/right, session 5 alone contains up/down/single
blink, and session 6 alone contains double blink. Each held-out session removes its
classes entirely from training. The script records missing classes and null results
for every such fold; it does not manufacture a cross-session score.

Unlabeled live logs have no natural-versus-voluntary blink ground truth. Amplitude or
width cannot be evaluated as an intent separator there; no numerical voluntary/natural
result is claimed. The known right/center/double interaction is one explicit annotation.
Negative cue phases are conservative false-confirmation proxies, not proof of no blink.
Reviewed acquisition protocols did not instruct selection, so confirmation misses are
N/A; raw pulse misses and negative selections are reported separately.

The retry change keeps a pending choice until its original expiry after an unclear
pair. Existing-data replay found no additional negative selections; that is not a
calibrated confidence score or evidence of future zero false confirmations.
