# EOG development handoff — 2026-10-10

## Start here

- Working checkout: `/private/tmp/nuggies`; remote: `Kennethbaole/nuggies`.
- Active branch: `experiment/eog-continuous-detection`. Continue here; do not merge to main without an explicit decision.
- Read `NUGGET.md`, `docs/EOG_COMMUNICATION.md`, and `docs/PROJECT_STATUS.md`.
- Kenneth authorizes implementation, experiments, incremental commits and pushes. Update documentation with each meaningful change. Preserve private recordings and credentials; do not commit them.
- Current priority: reliable gaze → return to center → deliberate double blink → exactly one word/utility selection. Four cardinal directions; no gaze highlighting. Do not ask for another generic calibration session before analyzing existing recordings.

## What works / current blocker

Both BioAmp EXG Pills stream through Arduino Nano R4 (A0 horizontal, A1 vertical; 250 Hz, 14-bit). Positive horizontal corresponds to right; positive vertical to up for this wearer. Red IN+, black IN−, yellow REF. Soldering is paused for supplies. Jetson deployment and physical OLED behavior remain unvalidated.

The communication gate holds a fresh gaze choice for 10 seconds. An observed opposite return plus ~250 ms quiet signal can arm confirmation during recovery. Blink activity then preserves the armed state. A new movement, fault, retry, expiry or changed choice cancels it. Confirmation is one-shot. This recovery fix was pushed as `ee76de4`.

Kenneth's latest explicit trial was **right → center → double blink**. Private log `recordings/live-eog-20261010T194946508017Z.events.jsonl` records:

| Global sample | Result |
| --- | --- |
| 15962 | Right accepted, onset 15732 |
| 16292 | Opposite return recognized, onset 16062 |
| 16622 | Double blink recognized, onset 16392; confirmation rejected |

Double-blink distance was 0.005388, horizontal fraction 0.05591, direction margin 6.903104, but other-label margin only 1.218038. The gate requires 1.5 at that distance. It was armed: this particular failure is ambiguous single-versus-double template matching, not a missing gaze.

## Latest change and its limits

`backend/blink_shape.py` measures positive vertical lobes in each existing 50 Hz waveform window: number of completed pulses, half-height widths, peak separation, amplitude ratio and inter-pulse valley. `WaveformProfile.classify` attaches these numeric diagnostics to events. They **do not change acceptance or trigger selection** yet. Width/gap limits are engineering starting points, not paper-derived or independently validated wearer limits.

Synthetic tests distinguish two separated lobes from a single lobe and sustained upward shift. Reused recordings also produced two-lobe shapes in some single-blink and direction windows. Thus pulse count alone is unsafe as an override. A potential narrowly scoped rule would require an existing double-blink label, excellent distance, strong separation from directions, low horizontal energy, valid two-pulse shape, and the existing armed-choice/recovery protections. Evaluate before enabling it.

Diagnostic logging now translates `confirmation_armed_sample` to the same global application sample coordinate as onset/emitted sample. Earlier logs left that field detector-local: do not compare it directly with global onset.

## Immediate analysis tasks

1. Reproduce the exact latest event at sample 16622 before tuning the gate. Its timestamp `1791661853003` matches CSV row 16622 (verified). A naive replay starting at the first enabled transition (4060) did not reproduce it. Runtime detector resets/recentering and filter state must be accounted for; this is unresolved. Do not report that replay as a valid regression.
2. Capture the actual classified 50-frame window or log detector reset indices/configuration. Reconstruct the same causal filter baseline and rest offset. Then inspect whether two completed blink pulses really fall inside that window. Consider window boundaries/split events rather than merely lowering margins.
3. Replay reviewed labeled runs plus single blinks, upward gaze, return-to-center and baseline intervals. Report false confirmations as well as misses. Existing live logs are not fully intention-labeled; no accuracy percentage can be justified from them.
4. Only enable a targeted confirmation change after these checks; keep waveform/recovery/context safeguards. Add regression cases for the observed failure and accidental single-blink selection.
5. Run one short live interaction check with speech off, then enable speech after correct selection. Kenneth has already run many recordings; use them first.

Private analysis outputs: `recordings/blink-shape-audit.json`, `confirmation-regression-review.json`, `blink-policy-review.json`. These are exploratory reused-data results, not independent validation. Temporary scripts `/private/tmp/nuggies_shape_audit.py`, `/private/tmp/nuggies_recovery_check.py`, `/private/tmp/nuggies_confirmation_regression.py` may help but have alignment assumptions; review before reuse. The legacy `backend/double_blink.py` pulse detector is not wired live and previously performed poorly; do not plug it in blindly.

## Live environment and safe restart

- Web: `http://127.0.0.1:8878`.
- Server started with `/private/tmp/nuggies_wait_for_nano.py`; this temporary wrapper waits for Nano serial and starts a new timestamped recording automatically. Inspect it before restarting; it is outside the repo.
- Python: `/Users/kennethle/Desktop/Main.Ken/Ken - Dev/Projects_2027/shtopsecret/.venv/bin/python`.
- Frozen private runtime profile: `recordings/guided-runtime-selected/candidate-profile.json`.
- Verify the actual listener with `lsof -nP -iTCP:8878 -sTCP:LISTEN`; don't kill unrelated processes. Flush current recording with authenticated `record_stop` before restart. Load `.env` through `backend.envfile.load_env()`; never print tokens.
- Authenticated POST `/api/action`: JSON action/value/event_id. Relevant actions: `record_stop`, `guided_stop`, `wheel_test`, `eog_communication`, `eog_recenter`.
- After restart explicitly enable EOG communication if connected; reconnect may disable wheel testing. A browser refresh defaults speech off. The latest instrumentation is on disk; an existing Python process does not hot-reload it.
- Preserve established body-electrode battery-only laptop protocol; disconnect body electrodes and power before soldering.

## Validation

Run from the checkout with the Python above:

```sh
python -m unittest discover -s tests -q
python -m scripts.browser_eog_check --profile recordings/guided-runtime-selected/candidate-profile.json --chrome '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

Tests need local HTTP socket permission. Browser checks validate software behavior, not live EOG accuracy. Avoid paid speech API calls in automated tests. The optional NumPy test may skip in this environment.

## Product constraints / later work

Bigger, organized UI is implemented; pending choice is shown above the wheel and readiness explicitly says when to double blink. Homepage cardinal layout: up/right replies, left More, down Back. Diagonals disabled during communication. No auto-select on dwell. Browser speech requires explicit enablement. Companion phone displays confirmed content.

Local detector and canonical state should remain responsive; remote sentence generation is optional with preset fallback. No remote model server has been provisioned. Jetson Orin Nano is separate from the Arduino Nano R4. Do not conflate their roles or claim physical OLED/Jetson success from browser tests.

Latest full-suite result for this change: **186 tests, 185 passed, one optional skip**. The first sandboxed run could not bind local test sockets; the permitted rerun passed.
