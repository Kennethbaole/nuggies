# EOG development handoff — 2026-10-11

## Current branch and interface follow-up

Kenneth now requires all work directly on `main`. Feature branch changes have
been consolidated. Do not create branches unless he changes this instruction.
Read [agent workflow](../AGENTS.md); older branch restrictions are superseded.
The project name is Glint; the GitHub repo remains Kennethbaole/nuggies.
`1643651` adds the full-width centered wheel, stronger readiness cues, blank
homepage tagline, blue/violet themes, motion and team/project tabs including Bella.
`de01b53` preserves pending choices during retry and later returns, disarming
until recovery settles without extending the ten-second expiry. `e1c64bc`
replaces manual gesture controls with Listen/Text/Default choices at the wheel
and makes options larger and closer. Pulse-mode early confirmation now keeps
the pending choice for a fresh retry; the early pair still cannot select.

The local wrapper was safely restarted from this branch after e1c64bc; Nano was
disconnected, recording and eye control were off. No new wearer test was requested.
Any subsequent backend change needs another safe restart to become live. The offline Left-analysis files are preserved in `a0dc9b4`; no live direction
threshold was changed. The horizontal-axis alternative did not improve replay.
The sections below are historical unless superseded here. OLED fit work remains
outstanding; frontend appearance does not establish physical display readability.


## Open integration questions

- Which machine owns Arduino Nano USB: laptop or Jetson?
- Where should confirmed speech play: companion browser or a Jetson speaker?
- Is the physical ESP32 display required for this demo?

These remain undecided. Do not invent a topology or claim Jetson/OLED validation.

## Current priority and working rules

Work in `/private/tmp/nuggies`, remote `Kennethbaole/nuggies`, branch
`main`. Kenneth authorizes
changes, incremental commits and pushes. Commit one concern with its documentation;
run the complete suite before every push and check status for private files.
Never commit recordings, profiles, `.env`, speech caches or participant waveforms.

Kenneth's latest report: **double-blink selection is more consistent, but directions
request retry too often and a rightward glance's return can be treated as Left.**
Stop asking for generic calibration or repeated movement protocols. Use the saved
raw recordings and exact decision windows to improve these specific failures.
The prescribed six-attempt live check was not completed as an intention-labelled
acceptance test; do not mark it passed. Keep the successful blink path separate from
changes to directional recognition. No further wearer test is requested in this handoff.

Runtime stays pure Python. Optional NumPy belongs only in offline experiments.
Reused-data replay is development evidence, never independent accuracy. Always
report misses and false confirmations together. Read NUGGET.md, EOG_COMMUNICATION.md,
EOG_DIRECTION_REGRESSION.md and PROJECT_STATUS.md before changing behavior.

## What changed, with pushed commits

| Commit | Concern |
| --- | --- |
| `897ff4d` | Starting communication enables companion speech through the browser click; refresh defaults speech off. |
| `fcac617` | Exhaustive historical reset search and exact failed-double-blink reconstruction. |
| `3649ac3` | Reset/window/source/profile audit evidence and exact detector replay CLI. |
| `a42f780` | Independent causal blink pulse pairing, opt-in confirmation and safety regressions. |
| `730b36d` | An unclear armed blink pair can be retried without a new gaze or extending expiry. |
| `29ea363` | Shared transport-free pipeline, contract v1 and headless JSONL entry point. |
| `23ae4f6` | Optional sequenced/timestamped Nano sketch and backward-compatible host metadata. Not flashed. |
| `076f2b0` | Broad signal/classifier comparisons, evidence table and source assessment. |
| `9027804` | Exact replay from a checkpoint between synthetic blink pulses. |
| `ec6b9c2` | Historical direction parity comparison using recorded resets. |
| `d71d878` | Offline retry/recovery duration comparisons; live timings unchanged. |
| `000792c` | Ready immediately listens; removes redundant one-second segmenter warmup. |
| `8dbd864` | Optional remembered-excursion guard vetoes opposite return commands; browser and replay checks. |

## Concrete failure mechanisms

### Failed double blink: resolved reconstruction and targeted fix

Target `recordings/live-eog-20261010T194946508017Z.{csv,events.jsonl}` came from
pre-f96cb3d code. Search considered all 11,418 reset indices 4060..15477; 9,135
impossible 50 Hz residues were excluded and 2,283 simulated. Only **13778** reproduces
all logged right/return/double events and six-decimal metrics.

Right15962, return16292, double16622. Real blink peaks16312/16367 were both hidden
by the direction segmenter's 400 ms cooldown after the return. The classified window
16377..16622 began after both peaks. The 1.218 single/double margin compared recovery
tails, not two complete blinks. Template28 double and21 single were the competitors.
It was **lost onset context**, not the second blink running past the end of the window.

The parallel 50 Hz pulse stream observes during gaze cooldown. Pair shape, velocities,
widths, spacing, horizontal energy and a pulse-anchored template all participate;
pulse count alone cannot select. It waits through a possible third pulse. Gate still
requires a pending choice, return/arming, valid onset, unexpired content and one-shot
consumption. The identified failed interaction now selects once at16532. See
EOG_FAILED_BLINK_REPRODUCTION.md and EOG_COMMUNICATION.md.

### Direction regression: existing brittleness plus hidden Ready interval

Before the two latest direction fixes, old `ee76de4` and then-current code produced
identical **65 waveform decisions**, filtered values and phases on the same saved
89,820 raw rows and logged controls. Time in retry was68.560s. This showed the pulse
addition had not changed the direction classifier, but the inherited interaction
was still brittle. That parity report predates `000792c`; do not expect it to remain
identical after the intentional Ready fix.

A concrete defect: guided center/recovery announced Ready while EventSegmenter.reset
started another one-second blind warmup. At ready3500, positive H activity+2429 at3740
was ignored; a later negative pulse became Left4400. A second example followed
ready81976. Guided resets now mark the already-settled segmenter warmed up.

Separately, retry discarded uncertain excursion context; recovery timeout could
rearm without an observed opposite return. The return guard tracks sustained
horizontal excursions while Ready and remembers directional candidates, including
rejected ones. Quiet and timeout do not erase ownership. An opposite pulse is a
return, with completed intervals retained for late classification. Recovery rebounds
cannot seed fresh excursions. It emits no gaze or selection by itself.

The suspect Left4400 is suppressed in replay with the guard. The outbound mixed
waveform is still not converted into a confident Right. Some outward matches still
fail, and unlabeled suppressions cannot be called correct. Do not promise the whole
directional usability problem is solved. Detailed evidence: EOG_DIRECTION_REGRESSION.md.

## Evidence and limits

| Check | Result / limit |
| --- | --- |
| Current reviewed repetition holdout | 16/20 direction hits;4misses;0wrong/duplicates;3false directions/275s (.655/min); median cue→emit1.51s. |
| Pulse + return-guard confirmations, reviewed holdout | 0negative-phase confirmations; intended confirmation misses unknown because these were acquisition protocols. |
| Frozen full-profile communication replay | 0negative-phase selections in sessions4/5/6;2selections in double-blink movement cues. Legacy earlier policy had2negative selections. |
| Raw pulse detection, session6 | 3/5 cue pairs found,2misses; baseline/unlabeled pair candidates also occur. |
| Exact historical explicit interaction | 1selection instead of a miss; no other selection inside that identified interval. |
| Saved new live recording before direction fixes | 4selections,7accepted directions; no per-attempt intention labels, so confirmation misses/false totals are not scoreable. Wearer reports directional usability failure. |
| Audit verification before direction fixes | All89,820 saved samples,86classified decisions and8resets replayed exactly with the then-current source. |
| Audit verification after direction fixes | A snapshot of the restarted live session replayed all 18,495 samples, 12 classified decisions and 4 resets identically with source verification. This checks reproducibility, not wearer intent. |
| Software | 224tests run,223passed,1optional skip. Isolated browser check passes; no paid TTS. |

Remaining raw pair misses: session6 repetition4 has a weak second pulse (ratio~.239)
and horizontal fraction~.1513, beyond the current .25ratio/.15H bounds. Repetition5
has peaks only140ms apart with a shallow valley (~98% of smaller peak), so it is
one pulse with a bump, not two qualifying pulses. These are measured mechanisms;
do not loosen both gates merely to fit those two examples.

The comparison table in EOG_CONTINUOUS_EXPERIMENT.md includes notch/low-pass, median,
stable baseline, Haar, second-half matching, nearest-two, DTW, LDA, normalization,
crosstalk, capture extension and shorter retry/recovery. No alternative filter or
classifier was adopted. Shorter retry increased false directions. Shorter recovery
at1s added five misses. At2s it saved some blocked time but did not fix recognition.
An initial guard seeded recovery rebounds and worsened to15hits/5misses/4false; rejected.

Leave-one-session-out cannot be scored honestly: reviewed classes are concentrated
in separate sessions, so a held-out session removes its classes from training.
The Pill's actual configured analog passband is not verified numerically. Manufacturer
software filter cutoffs are not hardware cutoffs. Natural versus deliberate blink
intent is unlabelled in live logs. No calibrated confidence probability is claimed.

## Live process and restart

- URL: `http://127.0.0.1:8878`.
- Launcher: `/private/tmp/nuggies_wait_for_nano.py`, inspected and updated outside Git.
- Restarted after `8dbd864`; both `eog_pulse_confirmation=True` and
  `eog_return_guard=True` are configured. Communication was restored because it was
  active before restart. Verify actual state rather than assuming the wearer left it on.
- Fresh private raw/log stem: `recordings/live-eog-20261010T215953695117Z`.
- Tool process session74793; discover the actual listener with
  `lsof -nP -iTCP:8878 -sTCP:LISTEN` before stopping anything.
- Frozen profile: `recordings/guided-runtime-selected/candidate-profile.json`.
- Earlier raw file `live-eog-20261010T212503814387Z.csv` ends at global89819.
  Its decision log continued after record_stop: later decisions have saved windows
  but no matching raw CSV. Exact replay intentionally stops at recording_stop.
- Safe restart: authenticated state; stop guided cues, communication and recording;
  verify listener PID/command; SIGINT only that process; start wrapper from this
  checkout. New connection creates a fresh exclusive recording and logs serial_connect.
- Load `.env` through backend.envfile.load_env; never print tokens. Browser click
  enables speech. ElevenLabs is configured, cache/browser fallback remains; no paid
  provider call belongs in automated tests. Do not flash firmware without Kenneth.

## Commands and private artifacts

Python: `/Users/kennethle/Desktop/Main.Ken/Ken - Dev/Projects_2027/shtopsecret/.venv/bin/python`.
Optional offline analysis Python: `/private/tmp/nuggies-eog-venv/bin/python`.

```sh
python -m unittest discover -s tests -q
python -m scripts.browser_eog_check --profile recordings/guided-runtime-selected/candidate-profile.json --chrome '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
python -m scripts.eog_exact_replay recordings/SESSION.csv recordings/SESSION.events.jsonl --profile recordings/guided-runtime-selected/candidate-profile.json
python -m scripts.eog_signal_comparison --output recordings/NEW_REPORT --variants pulse-confirmation pulse-return-guard
python -m scripts.eog_pulse_confirmation_review --profile recordings/guided-runtime-selected/candidate-profile.json --return-guard --output recordings/NEW_CONFIRMATION_REPORT.json
python -m scripts.eog_headless --csv recordings/SESSION.csv --profile recordings/guided-runtime-selected/candidate-profile.json --pulse-confirmation --return-guard --communication
```

Exact replay verifies the source digest and profile, resets and classified decisions;
it does not reconstruct unlogged manual UI intent or prove audible speech. Use the
recorded source for historical audits; `--allow-code-mismatch` is a development
comparison, not a source-verified replay. Synthetic checkpoints include active blink
pairing and excursion state. See EOG_REPLAY.md and EOG_CONTRACT.md.

Useful private reports: failed-double-blink-reproduction.json, current-direction-parity.json,
signal-comparison-return-guard-final/report.json, pulse-confirmation-return-guard.json,
live-return-guard-comparison.json, pulse-miss-details.json. Complete arrays/windows stay private.
The source-verified post-restart snapshot is `return-guard-live-snapshot.{csv,events.jsonl}`.

## Next bounded experiment

Freeze the blink policy and latest direction fixes. Diagnose why outward windows
are rejected: leading-lobe timing, overlapping return within one-second windows,
and amplitude/template mismatch. Preserve the first directional excursion while
separately matching its return; compare candidate algorithms on reviewed folds and
the saved stress record, with blocked time and false confirmations alongside misses.
Do not silently lower the global threshold, swap filters, deploy a new classifier,
or request another blanket recording. The latest wearer complaint is a regression
case to resolve from existing evidence, not a reason to restart calibration.

The pipeline/contract/headless adapter is available for Jetson integration. The new
Nano v2 sketch adds sequence/micros/header/optional oversampling but remains uncompiled
and unflashed. Host parsing accepts legacy rows. Device metadata is observational;
live filtering still assumes nominal250Hz. ESP32 bridge is unchanged. Physical OLED,
Jetson deployment, microphone/speech routing and wearable soldering remain separate,
untested integration work.
