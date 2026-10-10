> 2026-10-10 update: A separate opt-in experimental communication mode now connects
> gaze, recovered-center readiness, and double-blink confirmation to the existing
> phrase/speech pipeline. Diagnostic eye-wheel mode still cannot confirm or speak.
> See [communication flow](EOG_COMMUNICATION.md). No live confirmation accuracy is claimed.

# Guided EOG diagnostic test

Updated 2026-10-10. Branch: `experiment/eog-continuous-detection`.
This is the first integrated waveform test mode, enabled explicitly with a
private `--eog-profile`. Starting the app alone does not start eye control.

## What is implemented

- Pure-Python, frozen two-channel waveform matching; no NumPy, Torch or external
  service is required for live inference. Profile arrays/settings are validated
  before starting. The default event window remains one second.
- Three clean seconds of instructed straight-ahead setup, following a one-second
  filter warmup. Blinks/activity mask clean samples and stale clean history expires.
- Continuous causal DC removal plus a separate robust resting residual estimate.
  The residual updates slowly only in ready/stable intervals, never while a
  candidate, blink, retry or movement recovery is active. This is electrical drift
  handling, not absolute gaze tracking or automatic polarity/gain calibration.
- Cardinal classification only: up=slot0, right=2, down=4, left=6. Diagonals are
  not validated. Frozen profiles assume the verified two-Pill wiring/polarity.
- Rejection for distant matches, overlap with blink templates, or competing
  directions. An unfamiliar blink-labelled waveform with substantial horizontal
  energy also enters retry: this catches a missed excursion whose return could
  otherwise become a false opposite command. Ordinary blink-labelled events are
  silent and never confirm anything.
- Five clean seconds of `Look center / Retry` recovery. Poor-quality samples
  are excluded. Prolonged waits show contact/recenter guidance; an explicit
  Recenter button remains available. Quiet readings cannot prove physical center.
- After acceptance, suppress further directions during recovery. Opposite return
  evidence plus quiet can release recovery; otherwise the bounded four-second
  interval plus quiet permits another attempt. Waiting remains visible if not quiet.
- ADC clipping, timestamp reversal/gaps >500ms and stale input inhibit commands
  and require new centering. Missing samples are reflected in the UI after one
  second. The driver may stop acquisition after its existing five-second timeout;
  restart the launcher after an actual serial disconnection if necessary.
- Prominent center-of-wheel instructions/detected direction, progress, reasons,
  counters and browser HUD status. Gaze highlighting is removed, including the
  HUD. Phone conversation text still shows actual communicated words.
- Optional private JSONL transitions/decisions alongside raw CSV and cue sidecars.
  Logs retain settings and profile identity for reproducibility. New paths are exclusive; earlier recordings/logs are never overwritten.
- A short live protocol with two attempts per cardinal direction, single blink
  and double blink. Nominal length157s (2m37s), plus any recovery waits. Prepare
  cues pause until the detector is Ready. Cues do not enter the detector.

The mode only focuses wheel state. It does not activate items, change screens,
confirm phrases or speak. Blink labels are observations, not a validated
intentional double-blink confirmation detector. Keyboard/manual controls remain
separate. Existing legacy and calibrated modes are unchanged without the flag.

## Existing-recording comparison

Five same-session repetition folds on the reviewed manifest, with the exact
runtime used by the app. Initial setup/quality/recovery also run continuously;
cue labels fit templates and score held-out regions only.

| Variant | Correct /20 | Wrong / duplicates | False candidates /275s |
| --- | --- | --- | --- |
| Earlier offline waveform rejection |16|0 /0|6|
| Guided, without uncertain horizontal blink handling |16|0 /0|4|
| **Selected guided default** |**16**|**0 /0**|**3**|
| Guided, three-second retry |16|0 /0|4|
| Reject all distant blink matches |13|0 /0|2|
| Guided plus weak Haar contrast |16|0 /0|4|
| Guided plus medium Haar contrast |15|0 /0|3|
| Guided plus stronger Haar contrast |14|0 /0|2|

Selected median cue-to-emission is1.51s, including wearer reaction. The selected
false candidates comprise two cue-boundary-ambiguous early up/right events and
one up event during a reviewed double-blink rest. Strict scores remain unchanged;
this is not proof that only one genuine error would occur live. Left4 becomes
uncertain/retry instead of emitting its false right return; right4 is also missed
while recovering. Recordings contain no wearer responding to retry prompts.

Haar here is adjacent200ms window contrast on50Hz normalized vertical samples,
not a replication of a paper's fixed wavelet scale. Larger weights trade recall
for fewer triggers; it is disabled in the selected mode. Rejecting every
unfamiliar blink also costs too many movements. Keep these alternatives documented.

Reports: private `recordings/guided-runtime-selected/report.json`.
All-data profile: `recordings/guided-runtime-selected/candidate-profile.json`.
The profile is not used for fold scoring. These reused-data development results
are not independent or cross-session validation. The short upcoming live session
must retain fixed settings and be assessed separately.

## Start the live session

Use battery-only laptop operation, disconnected from the charger and other
mains-connected equipment while body electrodes are attached, as in prior tests.
Keep the verified wiring and electrode placements; this change needs no rewiring
or firmware upload. Nano:250Hz,115200baud; A0horizontal,A1vertical,14-bit ADC.

From the repo with its pyserial environment active:

```sh
python -m scripts.start_eog_test
```

The launcher identifies a uniquely named Nano/Arduino port, validates the private
profile and starts `http://127.0.0.1:8878`. It records a new timestamped raw CSV,
labels/trials sidecars and `.events.jsonl` under Git-ignored `recordings/`.
If identification is ambiguous, explicitly provide the Nano port:

```sh
python -m scripts.start_eog_test --serial-port /dev/cu.YOUR_NANO
```

It opens no device with `--dry-run`. The launcher does not choose a random USB
port. Close other applications holding the Nano port before starting.

1. Open the webpage and select **Start experimental eye wheel test**.
2. Look straight ahead, blink normally and wait for **Ready**.
3. Open Signal workspace. Choose **Live detector check**, then **Start guided test**.
4. Follow the large center instructions. Make the instructed movement, return
   to center and wait. A retry means stay centered; prepare instructions wait
   automatically. Single/double blinks should not select a wheel item.
5. After completion, stop the eye wheel test, then stop recording. Preserve all
   files together. Stop the launcher with Ctrl+C.

Recenter during the guided check stops that check to avoid misleading labels.
Stopping eye control also stops diagnostic cues. The acquisition-only longer
protocols remain mutually exclusive with eye control.

Judge this session by intended direction versus detected direction, false
movements during blinks/rest, retries, return behavior and waiting time. Do not
adjust thresholds mid-session or use these trials immediately as new training
while calling them held-out validation. The next decision is whether cardinal
control is usable enough to proceed to confirmation, or whether a specific
failure needs further offline analysis.

## OLED status

The browser HUD is integrated and tested. The physical ESP32 OLED adapter is
implemented but untested on hardware:

```sh
python -m scripts.eog_hud_bridge --url http://127.0.0.1:8878 --port /dev/cu.YOUR_ESP32
```

Use the ESP32's separate port, never the Nano acquisition port. It sends only
existing `T:` status messages, refreshed every0.5s. Retry displays
`! Look center / Retry`. It does not sync wheel geometry/options, send selection
or highlight commands, or flash firmware. Full physical HUD synchronization
remains separate work.

## Reproduce without a wearer

Model fitting/comparison uses optional requirements-eog.txt; live inference and
raw-only replay use only the base environment.

```sh
python -m scripts.eog_guided_experiment \
  --manifest recordings/reviewed-runs.json \
  --output recordings/guided-runtime-selected

python -m scripts.eog_guided_replay recordings/trial.csv \
  --profile recordings/guided-runtime-selected/candidate-profile.json \
  --output recordings/new-guided-replay.json

python -m scripts.browser_eog_check \
  --profile recordings/guided-runtime-selected/candidate-profile.json
```

The raw-only CLI opens no sidecars or hardware and emits no application commands.
A sidecar-free68,873sample replay completed in0.316s on the development Mac;
this is local processing evidence, not Jetson performance or physiological latency.
Browser checks intentionally simulate states against the real HTTP/UI wiring;
algorithm evidence comes from the separate continuous replay. Normal desktop/mobile
navigation and browser speech fallback also passed regression checks with cloud
speech disabled for deterministic browser-speech testing.

## Remaining boundaries

One blink-related up candidate persists. Thresholds, confidence ratios, per-axis
scales and recovery durations are exploratory settings. Electrode/contact failure
cannot always be distinguished from a quiet valid channel. There is no independent
absolute-center reference, IMU fusion, calibrated probability, validated diagonal
control, fast prefix classifier or tested physical OLED. Larger LSTMs and adding
features alone did not improve the available development comparison. A short live
check is now more useful than another broad calibration recording.

## Verification record

167 base tests run:166 passed, one optional NumPy test skipped. The optional
temporal tests passed in the experiment environment. Headless Chrome checks
passed for actual HTTP/UI wiring with simulated states, including guided center,
retry, manual recenter, stale input, HUD rendering, readiness-aware cues, absent
gaze highlighting, speech inhibition and no automatic confirmation. Raw-only
replay and seven exact-runtime comparisons completed. No live wearer, Jetson or
physical OLED test has been performed.


## First live manual check and homepage speed test

The first live recording (2026-10-10,193.178s,48,295samples) had no guided cue
labels. The wearer/operator subsequently confirmed that intended cardinal
movements triggered and an upper-left diagonal produced retry. This is useful
qualitative confirmation, not a measured accuracy percentage or validated
diagonal classifier. Logs show5accepted directions,3rejections,8blink-family
labels and6suppressed recovery events. A clear left/right/up/down sequence
appears near129–149s. Active monitoring also recorded6clipping resets in two
brief periods; these were not six USB disconnects. No >500ms receipt gaps were
found, and nominal sampling was approximately250Hz. Preserve this recording
without adding it to training before separate assessment.

For the next session use **Start recorded wheel speed check** on the homepage.
This single button enables eye monitoring, centers first and then starts12
cardinal cues (three each, varied order) on the wheel. It requires live recording;
it does not need the hidden Signal workspace controls. Nominal cue duration is
130s plus centering/recovery waits. Return to center when prompted.

The wheel preview displays the detected direction/target and response time;
the homepage also shows completed attempts, matches and median response time.
These values are separate:

- Cue-to-detection uses the server's instructed cue start. It includes reaction
  time and browser cue-delivery delay; it is not pure algorithm latency.
- Candidate-to-decision uses the fixed nominal250Hz sample indices. The current
  one-second capture typically gives about920ms from candidate onset; it does
  not establish physiological eye-onset timing.
- Candidates beginning before the cue are marked early and excluded from the
  response median. Matched counts alone do not establish valid latency.

All decisions and available timing fields are saved with the raw/cue records.
Missed/wrong attempts remain in speed_results rather than being silently
dropped. No classifier thresholds, model weights, speech or confirmation were
changed for this speed experiment. Unit/HTTP suite169run:168passed,1optional
skip; the homepage single-button flow passed headless browser checks.
