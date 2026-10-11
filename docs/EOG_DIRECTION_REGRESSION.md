# Direction regression investigation — 2026-10-10

The wearer reported worse directional behavior after the independent blink path was
started. Live communication and recording were stopped; further work uses existing
recordings. No new generic calibration or repeated wearer protocol is requested.

## Same-input comparison

`python -m scripts.eog_direction_parity CSV EVENTS --profile PROFILE --output
recordings/parity.json` loads the previous `ee76de4` detector directly from Git,
without checking out or changing runtime files. It feeds that detector and the
current detector the same raw rows, recorded resets, polling faults and enabled
intervals. It compares filtered values and phases at every enabled sample, and
classification labels, onset/emission indices and distances to six decimal places.
It does not compare confirmation policies or infer what the wearer intended.

On the just-preserved live recording, both produced the same **65 waveform
decisions**, including every accepted direction, with **zero differences in
filtered values or phase**. Time in each phase was identical: centering 57.708 s,
ready 75.432 s, recovery 54.560 s, retry 68.560 s. Thus the newly added pulse path
has not changed the direction classifier on this input. The observation of poor
interaction still stands: the existing direction/recovery policy rejects events
and spends substantial time unable to accept another direction.

Some rejected horizontal candidates have distances .131 and .123 above the .08
cutoff; other windows overlap the blink templates. Without per-attempt intention
annotations these cannot be relabeled correct or used to claim direction accuracy.
The one-second capture, four-second recovery fallback and five-second clean retry
remain explicit usability suspects. Reverting the direction code to `ee76de4`
would reproduce these same decisions on this recording.

Private full evidence: `recordings/current-direction-parity.json`. Live v2 audit
replay independently reproduced the complete 89,820-sample recording, all 86 classified decisions
(including pulse decisions), and eight recorded resets exactly. This closes the
previous invisible-reset investigation problem. A synthetic parity regression
covers repeated reset, disabled intervals, clipping and polling/timestamp faults.

## Deployment rule for the next change

Keep the current direction path as a fixed comparison. Evaluate recovery/retry
changes offline on reviewed sessions and this stress recording; report blocked time,
misses, wrong/duplicate directions, and false confirmations together. Do not promote
an extra experimental detector or ask the wearer to repeat calibration because a
reused-data example passed. No new direction or retry settings have been deployed.
The remaining live result is a usability failure report, not a completed scripted
acceptance check; correct and false confirmation totals remain unscored by intent.

## Timing sweep outcome

Retry .6/1/2/3 s retains 16 hits and four misses but increases false directions from three to five/four/four/four over 275 s; all have zero negative-phase confirmations in this replay. Recovery 1 s falls to 11 hits/nine misses with two false directions; recovery 2 s keeps 16/four and three false directions, with zero negative-phase confirmations. No timing variant is enabled. The full table separates actual blocked time from scored negative exposure.

The next algorithm experiment should track an uncertain excursion and its return explicitly while preserving the pending-choice rules, rather than discarding the whole temporal context and demanding another long clean-rest buffer. Fit and compare that state change on existing recordings before another live deployment. Shorter retry alone has now been checked and does not solve this tradeoff.

## Fixed: Ready concealed a second warmup

Both center-ready and recovery-ready called `EventSegmenter.reset()`, which imposed
one more second of warmup even though filtering and guided settling were complete.
The UI already said Ready. The outgoing gaze could be ignored while its later,
opposite return became the first eligible candidate. Guided resets now explicitly
mark the segmenter warmed up; standalone segmentation retains its original warmup.

In the preserved live record, center-ready was sample 3500 and segmentation remained
blind through 3750. Horizontal activity peaked +2429 at 3740 inside that gap; the
next horizontal negative pulse was accepted Left at 4400. A second instance followed
recovery-ready at 81976, with positive activity inside the hidden warmup followed by
Left at 82816. These are temporal mechanism observations consistent with the wearer's
report, not independently annotated physical eye directions.

Held-out repetition replay after this change keeps 16 hits, four misses, zero wrong
or duplicate directions, three false directions / 275 s and zero negative-phase
confirmations under the pulse policy; median cue-to-emission remains 1.51 s. Across
whole streams retry time increased by about 30.9 s because previously hidden inputs
can now be rejected. This fixes truthful readiness, not all retry/return behavior.
Private report: `recordings/signal-comparison-ready-warmup/report.json`. A synthetic
regression moves immediately after actual center/recovery transitions and verifies
capture starts within 120 ms. No new wearer recording was requested.

Frozen-profile pulse-confirmation replay also retains two selections in session-6 double-blink cues, zero in negative cue phases across sessions 4–6, and one selection in the exactly reconstructed failed interaction. Pulse-pair misses remain two of five reviewed cues; acquisition-only confirmation misses are not identifiable. Private report: `recordings/pulse-confirmation-ready-fix.json`.

## Reserved returns from uncertain excursions

`--eog-return-guard` enables a pure-Python 50 Hz navigation veto. It records a
sustained horizontal excursion while Ready, even if its eventual waveform command
is rejected or labelled blink-family. It also remembers directional candidates
at rejection/acceptance. An open excursion survives quiet, retry, and timeout
rearming. Its opposite is reserved as a return. An observed opposite lobe followed
by quiet closes ownership, but its interval remains recorded so a delayed window
cannot issue a new opposite command. Explicit reset/fault clears the guard.

The guard generates no gaze or confirmation. It requires existing classified
candidates to navigate and retains the pulse-confirmation gate. Automatic horizontal
tracking uses three filtered frames, a count floor, and a minimal horizontal/vertical
ratio; these remain engineering settings. Vertical ownership comes from directional
candidates, avoiding automatic vertical blink ownership. New automatic excursions
are disabled during recovery so a small rebound cannot reserve the next real gaze.

A first prototype that seeded during recovery caused a reviewed right cue to be
swallowed and its return to be accepted left: 15 hits/five misses/four false directions.
That prototype was rejected. The selected guard retains **16 hits/four misses, zero
wrong/duplicate directions, three false directions / 275 s, and zero negative-phase
confirmations**, with median cue-to-emission 1.51 s. Frozen-profile replay retains
two selections in double-blink movement cues and the single exactly reconstructed
failed confirmation, with no negative-phase confirmations. Raw pair misses remain
two of five cues; intended selection misses remain unidentifiable in acquisition data.

In the new raw-recording comparison, the suspect Left at sample 4400 is now consumed
as a return. Additional right candidates are also reserved; those intervals lack
per-attempt intention labels, so suppression cannot be counted as either correct
or missed user commands. The outgoing mixed/uncertain waveform is not turned into
a confident Right. This change prevents a demonstrated mechanism; it is not a
claim that all outward movement recognition or retry waits are fixed.

Private evidence: `signal-comparison-return-guard-final/report.json`,
`pulse-confirmation-return-guard.json`, and `live-return-guard-comparison.json` under
recordings/. Synthetic regressions cover rejected outbound→long quiet→opposite,
returns already inside capture, late classification, blink interference, recovery
rebounds, explicit reset and input gaps. Exact replay now retains guard state.

## Preserved offline Left experiment (2026-10-11)

`scripts/eog_left_review.py` reproduces saved Left-window classifications with
the matching private profile and writes its report only beneath `recordings/`.
A reviewed unlabelled live log had 25 Left candidates: 8 accepted, 7 blink-overlap
rejections, 9 recovering and 1 remembered excursion. These are policy counts,
not intended movement hits or accuracy. One rejected horizontal window also
failed direction separation (1.023 against 1.1); relaxing only its blink margin
would not accept it. Intent cannot be recovered from these unlabelled windows.

The offline `pulse-horizontal-axis` alternative uses horizontal energy to limit
competing direction classes. Repetition-holdout replay of reviewed sessions 4–6
did not improve the result, so it remains an offline experiment, not a live rule.

| Variant | Hits / 20 | Misses | Wrong | Duplicates | False directions / min | Negative-phase confirmations | Median cue-to-emit |
|---|---:|---:|---:|---:|---:|---:|---:|
| pulse-return-guard | 16 | 4 | 0 | 0 | 0.655 | 0 | 1.51 s |
| pulse-horizontal-axis | 16 | 4 | 0 | 0 | 0.655 | 0 | 1.51 s |

Both had three false directions over 275 seconds of negative exposure and one
selection during a movement cue. These acquisition sessions did not instruct
confirmation, so intended selection misses and actual false confirmations cannot
be determined; zero negative-phase confirmations is only a proxy. This is
reused-data development evidence from the earlier confirmation policy, not
validation of the newer pending-choice behavior or cross-session accuracy.
Private report: `recordings/left-axis-comparison/report.json` (excluded from Git).
