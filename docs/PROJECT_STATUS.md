# Current status and next work

2026-10-11 workflow: all new work is directly on `main`, including frontend and
detector work. Feature branches have been consolidated; previous branch-only
restrictions are historical. See [agent workflow](../AGENTS.md).

2026-10-11 interface update on `feat/wheel-ui-and-left-detection`: project renamed
**Glint**, homepage tagline intentionally blank, full-width centered wheel with
stronger stage cues, and project/team tabs (including Bella Le). Detector rules
are unchanged by these frontend edits. See [interface](UI_LAYOUT.md).

The detector notes below began on `experiment/eog-continuous-detection` on
2026-10-10 and are now maintained on `main`.
The detailed continuation record is [CLAUDE_HANDOFF](CLAUDE_HANDOFF.md).

## Current user-visible result

Kenneth reports that double-blink selection is more consistent. Directional control
still requests retry too often, and returning from a rightward gaze can be interpreted
as Left. This remains an open usability problem, not a passed acceptance test.
Use the existing recordings; do not ask for another generic calibration session.

Two targeted direction fixes are implemented and loaded on the local server:

- `000792c`: Ready now starts detection immediately. A redundant one-second
  segmenter warmup was hiding outward movements after the UI announced Ready.
- `8dbd864`: opt-in return protection remembers excursions even when their command
  was rejected; an opposite pulse can be consumed as a return instead of navigating.
  Quiet alone does not erase excursion context. Blink confirmation rules are unchanged.

The guard suppresses the suspect Left at sample 4400 in saved replay. It does not
turn the uncertain outward signal into an accepted Right. Read the
[direction investigation](EOG_DIRECTION_REGRESSION.md) before further tuning.

## Working path

Two BioAmp EXG Pills → Arduino Nano R4 A0/A1, nominal 250 Hz/14-bit → pure-Python
filtering and waveform navigation → pending cardinal choice → return/arming →
independent double-blink evidence → exactly one confirmed phrase/utility.

The independent pulse stream observes during navigation cooldown, avoiding the
lost blink peaks reproduced in the historical failed confirmation. Its shape and
template checks retain no-choice, early-blink, expiry, changed-content, fault and
one-shot protections. An ambiguous armed pair can be retried without extending the
original ten-second choice expiry. Details: [communication rules](EOG_COMMUNICATION.md).

Communication has four slots: up first reply, right second reply, left More, down
Back. Gaze highlighting remains removed; full pending text and readiness stay visible.
Starting communication through the browser click enables speech on that companion.
Refresh resets speech off. ElevenLabs cache/browser fallback is configured; automated
checks never call paid TTS. Phone/HUD and model-service code remain separate adapters.

## Evidence

| Evidence | Result and limitation |
| --- | --- |
| Reviewed repetition holdout | 16 direction hits, 4 misses, 0 wrong/duplicates, 3 false directions per 275 s; median cue→emission 1.51 s. Reused development data. |
| Pulse + return-guard confirmation replay | Zero negative-phase confirmations in reviewed holdout; intended confirmation misses not inferable from acquisition protocols. |
| Frozen-profile pulse replay | Two selections during reviewed double-blink cues; zero negative-phase selections. Raw pair detection still misses 2 of 5 cues. |
| Exactly reconstructed failed interaction | One selection with the independent pulse path instead of a miss; no other selection inside that identified interval. |
| New live usability session | Four selections in the saved raw interval, but no per-attempt intention annotations; false/missed confirmations unscored. Wearer reports more consistent blinking and poor directions. |
| Software | 224 tests run, 223 passed, one optional skip; isolated browser check passes with both new flags and mocked speech. |

Before the latest direction fixes, old/current code generated identical 65 waveform
decisions and phase timing on the saved session. Its 68.56 seconds in retry exposed
existing blocking behavior. New audit logging reproduced all 89,820 saved samples,
86 decisions and eight resets exactly with the recorded source. Later events after
record_stop have windows but no raw CSV; do not treat them as complete recordings.

After loading the two direction fixes, a fresh live snapshot also replayed exactly:
18,495 samples, 12 classified decisions and four resets, with source verification.
This establishes reproducibility; it does not establish correct wearer intent.

The [comparison table](EOG_CONTINUOUS_EXPERIMENT.md) covers filters, morphology,
Haar, LDA, DTW, normalization, crosstalk and recovery alternatives. No filter/classifier
replacement was adopted. Shorter retry alone adds false directions. Cross-session
holdout is not identifiable with the current class distribution; do not invent a score.

## Local environment

`http://127.0.0.1:8878`, launched by `/private/tmp/nuggies_wait_for_nano.py`.
Restarted after `8dbd864` with pulse confirmation and return guard enabled. The Nano
was connected, communication restored and a fresh private recording started at
`recordings/live-eog-20261010T215953695117Z`. Recheck actual state before operating;
the wearer may toggle controls. No new scripted test has been requested.

Use the safe exact-PID restart procedure in the handoff. Preserve exclusive raw/log
filenames, inspect source/profile identity, and never kill unrelated processes.

## Integration and next deliverable

[EOG contract v1](EOG_CONTRACT.md) defines transport-free samples/state/events and a
headless JSONL entry point. Nano USB ownership, speech output device and ESP32 demo
participation still need team decisions. Jetson/OLED operation is not validated.
The optional [Nano v2 sketch](EOG_FIRMWARE_V2.md) is implemented but uncompiled and
unflashed; existing acquisition firmware remains in place. Soldering is paused.

Next deliverable: an offline improvement to outward-direction recognition and
retry/recovery, using the frozen blink policy and saved failure cases. Measure
misses, wrong/duplicate commands, blocked time, false directions and false
confirmations together before changing live settings again.
