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
