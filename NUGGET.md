> 2026-10-10 update: A separate opt-in experimental communication mode now connects
> gaze, recovered-center readiness, and double-blink confirmation to the existing
> phrase/speech pipeline. Diagnostic eye-wheel mode still cannot confirm or speak.
> See [communication flow](docs/EOG_COMMUNICATION.md). No live confirmation accuracy is claimed.

# NUGGET — project truth and agent handoff

Updated: 2026-10-10. Repository audited at `b1ceaa0216426cba830f387c474bec8e05c9c3b8`.

Latest experimental implementation: `12342a4` on
`experiment/eog-continuous-detection`. Guided EOG live-check instructions and
current evidence: [EOG_LIVE_CHECK](docs/EOG_LIVE_CHECK.md). Base suite167run,
166passed,1optional skip; guided and normal desktop/mobile browser checks passed.
No new wearer or physical OLED result is claimed.

Read this before changing the project. This is the central reference for project intent, implementation boundaries, evidence, unresolved gaps, and the next work. Detailed guides remain useful, but their known stale statements are listed below. A feature being present in code does not establish that it works on the intended hardware or for the intended users.

## Contents

- [1. Purpose and team direction](#1-purpose-and-team-direction)
- [2. What is established](#2-what-is-established)
- [3. Architecture and ownership](#3-architecture-and-ownership)
- [4. Rules future changes must preserve](#4-rules-future-changes-must-preserve)
- [5. Signal acquisition and detector paths](#5-signal-acquisition-and-detector-paths)
- [6. Communication, speech, and personalization](#6-communication-speech-and-personalization)
- [7. API and state contracts](#7-api-and-state-contracts)
- [8. Running and integrating the project](#8-running-and-integrating-the-project)
- [9. Hackathon work order and integration checks](#9-hackathon-work-order-and-integration-checks)
- [10. Open implementation gaps](#10-open-implementation-gaps)
- [11. Documentation contradictions](#11-documentation-contradictions)
- [12. Repository map](#12-repository-map)
- [13. Verification record](#13-verification-record)
- [14. Decisions still open](#14-decisions-still-open)
- [15. Keeping this document true](#15-keeping-this-document-true)

## 1. Purpose and team direction

Nuggies is the temporary project name. The intended users are people affected by ALS who want to communicate through intentional eye movements. The intended device is wearable EOG-based glasses connected to a communication interface with spoken output.

The team is working within a **36-hour hackathon**. The remaining time and exact submission time have not been recorded. Prioritize a repeatable, demonstrable communication path and the tests that expose integration failures. Broader product features should follow that path.

### Owner-confirmed context

The project owner clarified the following on 2026-10-10:

- Reliable EOG navigation and Jetson integration are parallel priorities; part of the team is working separately on them.
- The Jetson should carry most model computation and background work.
- The computer should primarily display the website and acquire microphone audio.
- The Jetson works, EOG is being tested, and the glasses are not fully built.
- The software side works according to the team. The audit below identifies specific remaining failures and limits within that broad report.

These are team reports and product direction, not measurements of EOG accuracy, speech latency, or complete wearable operation. No evidence of testing with intended ALS users was supplied in this audit.

### Working target architecture

Use **one Jetson-hosted application backend and shared state**, with the computer as browser/microphone client, as the working interpretation of the owner's direction. This is the target deployment; it has not been demonstrated end to end by this audit.

“Application state” means the current contact, screen, phrase page, highlighted slot, spelling draft, confirmed phrase, recent utterances, input mode, recording status, and current signal feedback. Keeping one owner of this state makes the companion, phone, and display agree.

The physical Nano connection, final audio-output device, and ESP32 integration route remain open. Do not silently assume that moving the model to the Jetson also moves serial acquisition, speech playback, or application state there.

## 2. What is established

Use these evidence labels when discussing progress:

- **Implemented:** inspected code contains the behavior.
- **Software checked:** a reproducible software check exercised it; identify real, synthetic, or mocked inputs.
- **Team reported:** the team says it worked; retain the scope and date of that report.
- **Target:** intended behavior, not completed integration.
- **Open:** a decision, defect, or missing evidence remains.

| Area | Current truth | Evidence boundary |
| --- | --- | --- |
| Communication UI | Browser navigation, phrase selection, Needs, spelling, shared phone/HUD views are implemented. | Unit checks pass; earlier browser checks are documented. Browser acceptance was not rerun in this audit. |
| Nano acquisition | Two raw channels, serial parsing, recording/replay, labeling and guided protocols are implemented. | Earlier docs report live two-Pill acquisition. This audit had no serial devices. |
| EOG navigation | Calibrated left/right navigation and a separate experimental spatial hover mode exist. | The last specific live report says hover did not reliably match intended gaze. The owner says EOG remains under test. |
| Confirmation | Manual selection and simulated double-blink pairing work in the companion. | The newer biological double-blink detector is offline only. A different older detector can issue SELECT in the standalone ESP32 bridge. |
| Reply generation | Ollama/Qwen produces preview suggestions from text. | Code and mocked tests checked. No Jetson inference measurements were captured here. |
| Speech recognition | Browser microphone → application → Qwen ASR service is implemented. | Client/service tests use fake inference. Real CLI helper currently has a broken import. |
| Speech output | ElevenLabs with cache and browser fallback are implemented. | Mocked checks pass. Audible output and real provider behavior were not tested here. Piper is installation-only. |
| Contact personalization | Chat import, local profiles, example retrieval, and People UI are implemented. | Unit checks pass. This is retrieval and prompting, not model training. |
| Jetson | Owner reports the device works. | Exact software stack, service status, simultaneous model memory use, and full communication loop are not recorded. |
| Glasses and physical HUD | ESP32 SH1106 firmware and a standalone serial bridge exist. | Glasses are unfinished; optical readability, fit, and final integrated display operation remain open. |
| Packaging | A non-root Dockerfile and Jetson setup script exist. | Neither was executed during this audit. |

## 3. Architecture and ownership

### Current companion flow

```text
Nano raw CSV / recorded CSV / synthetic samples
    -> Application.ingest()
    -> monitor only, calibrated left/right gate, OR experimental live hover
    -> RingState
    -> /api/state
    -> companion / phone / browser HUD / optional image renderer

Computer browser microphone
    -> /api/suggest (or API-only /api/transcribe)
    -> RemoteTranscriber -> ASR_URL -> Qwen3-ASR service
    -> transcript -> OllamaSuggestions -> OLLAMA_URL
    -> preview phrases in RingState
    -> explicit confirmation -> /api/speech
    -> ElevenLabs audio or browser speech -> browser's audio device
```

`backend/app.py` owns a single `Application` per server process. An `RLock` protects most shared application operations. `backend/ring.py` owns the companion's navigation and phrase-confirmation rules. Separate locks limit speech and suggestion/transcription work. The web server is a stdlib `ThreadingHTTPServer`.

The frontend is vanilla HTML/CSS/JavaScript with no build step. It polls every 250 ms. There is no WebSocket server, database, persistent conversation session, or multi-user account system.

### Target device responsibilities

| Component | Working target responsibility | Existing implementation / outstanding work |
| --- | --- | --- |
| Computer | Browser rendering, microphone acquisition, user/caregiver controls; browser audio output for the current demo. | Already implemented as browser behavior. Verify microphone origin and audible output on the demo machine. |
| Jetson | Host `backend.app`, `RingState`, profiles, suggestions and Qwen ASR; process EOG if serial reaches it. | Services exist. Deployment, serial placement, resource measurements and joint operation need verification. |
| Nano R4 | Acquire A0/A1 and send raw counts. | Current 250 Hz sketch exists. It does not classify gestures. |
| ESP32/display | Eventually display the authoritative application state. | Current firmware is a separate command-driven wheel, not an adapter to `RingState`. |
| Speech provider | Convert confirmed text into audio. | ElevenLabs is optional cloud TTS; browser fallback plays on the computer. Piper is not connected. |

ASR and Ollama URLs are resolved by the machine running the Python application. If that application moves to the Jetson, `127.0.0.1` refers to the Jetson, not the computer.

### The separate ESP32 prototype

`backend/hud_bridge.py` does **not** consume `Application.state()` or `RingState`. It runs `EOGEventDetector` or keyboard/scenario input, sends serial commands to the ESP32, receives `SELECTED:<slot>:<label>`, and speaks a sentence from `config/hud_phrases.json` using host `say`/`espeak` when available.

The firmware owns its own selection index and labels. Its default utility labels and placement differ from the companion; Spell and More are labels without the companion's spelling/pagination logic. Back reports a selection/status, and the bridge suppresses its speech; it does not execute companion Back behavior.

Serial protocol: `O:<comma-separated labels>`, `H:<slot>`, `T:<status>`, `n`, `p`, `s`. Firmware labels are bounded to ten characters. There are no session/revision IDs, acknowledgements establishing application agreement, or confirmed-utterance IDs in this protocol.

Wi-Fi support is compiled off (`USE_WIFI=0`). Enabling its WebSocket client does not make it compatible with `backend.app`, even though both mention port 8765. A matching backend adapter/protocol is missing.

## 4. Rules future changes must preserve

1. **Preview and confirmation are different actions.** Moving focus, receiving a suggestion, or detecting a hover must not speak or activate a utility. In the current companion, selecting Home Back intentionally confirms “Give me a moment.” and opens Needs.
2. **Default to monitoring for real raw input.** Companion calibrated navigation requires explicit configuration. Experimental hover is separately enabled and defaults off after restart. Keep guided capture separate from sensor navigation.
3. **Name the exact detector path.** A fix to calibration, `events.py`, or `double_blink.py` does not automatically change live hover. See the table below.
4. **Keep raw data and intended labels separate.** Cue labels describe instructions, not measured movement onset or proof of intent. Do not feed labels into detectors being evaluated.
5. **Preserve evidence limits.** Synthetic tests are software checks. Team reports, fresh real recordings, audible playback, Jetson benchmarks, and wearable testing are separate evidence.
6. **Keep private data private.** Use the documented ignored locations. `.gitignore` does not protect arbitrary filenames or directories; verify new output paths before adding files to Git.
7. **Keep models off the confirmation path.** Suggestions remain optional. An unavailable model must leave manual communication and curated phrases usable; check that a failure actually preserves the intended fallback.
8. **Do not duplicate canonical state when integrating the Jetson.** All companion clients should connect to the same backend. Any ESP32 synchronization must explicitly bridge to that backend.
9. **Record behavior changes with tests and this handoff.** Especially document changes to polarity, timing, units, slot mapping, confirmation, data destinations, and service responsibilities.

These rules describe intended project constraints. Known implementation exceptions are listed in section 10 rather than hidden behind these statements.

Before body-connected acquisition, follow the setup/electrode/power verification in [ACQUISITION](docs/ACQUISITION.md). This document does not establish a validated body-connected or clinical system.

## 5. Signal acquisition and detector paths

### Acquisition contract

- A0 is horizontal and A1 is vertical. Both are raw 14-bit counts, range `0..16383`.
- USB serial is 115200 baud. Header: `horizontal,vertical`; subsequent rows: two integer counts.
- `nano_r4_eog_250hz.ino` schedules an A0/A1 pair every 4 ms. The reads are sequential, not simultaneous.
- `nano_r4_two_channel.ino` is the roughly 10 Hz bench sketch; it is unsuitable for the current waveform timing assumptions.
- `ADCSample.timestamp_ms` is host wall-clock receipt time, not device sampling time. USB buffering can produce repeated timestamps and uneven gaps.
- There is no device sequence number, MCU timestamp, or stream metadata identifying the running sketch/rate. Dropped samples cannot currently be counted directly.
- `SerialADCSource` bounds partial-line buffering, ignores invalid rows, and raises after five seconds without a valid sample. The UI reports stale serial input after two seconds. Serial failures end the worker; there is no automatic reconnect.
- Raw CSV columns, in required order: `timestamp_ms,horizontal_adc,vertical_adc,source,units`. Units are `adc_counts`. Replay accepts equal timestamps but rejects decreasing timestamps.
- The browser keeps only 300 recent samples; at nominal 250 Hz this represents about 1.2 seconds. Its trace is autoscaled and plotted by sample order, not a calibrated physical-gaze plot.

### Separate processing paths

| Path | Consumer | Configuration/time basis | What it actually does |
| --- | --- | --- | --- |
| `Calibration` → optional `ExponentialSmoother` → `ThresholdClassifier` → `GestureGate` | Companion serial/replay with `--enable-sensor-actions` | Calibration JSON; gate uses receipt timestamps. | Normalize counts, choose dominant cardinal axis, issue left/right after hold/rearm. No biological SELECT. |
| `LiveWheelTest` | Companion experimental eye-wheel toggle | Fixed 250 Hz sample-count assumptions and hardcoded raw thresholds. | Spatial focus among eight slots; no Select/Back activation. Calibration files do not configure it. |
| `EOGEventDetector` | `backend.detect` and standalone `hud_bridge` | `DetectorConfig`, default 250 Hz; sample index/fs. | NEXT/PREV on threshold onset; double-blink SELECT and long-blink BACK under exploratory rules. Can issue real bridge commands. |
| `PairedGlanceDetector` | `backend.review_glances` | Default 250 Hz; sample index/fs. | A0-only outbound/return/settling pattern; emits PREV/NEXT after recovery. Not currently wired into companion hover. |
| `DoubleBlinkDetector` | `backend.review_blinks` | Default 250 Hz, 20 ms smoothing; sample index/fs. | Two-channel SELECT candidates after pulse-shape and quiet-recovery checks. Offline, not live confirmation. |
| `DoubleBlinkGate` | Companion simulated `blink` commands | Monotonic event timing. | Pairs already-detected/simulated blink events. It never detects a biological blink from ADC counts. |
| `vertical_features` | Offline analysis | Explicit analysis fs, smoothing, peak threshold/gap. | Measures waveform features; does not classify intent or send commands. |

`EOGEventDetector` does not pass through the companion's `GestureGate`. Its horizontal event fires before the return; the paired-glance prototype waits for the return. Its long-blink rule can confuse vertical gaze with Back. Avoid general claims that all paths share the same safeguards.

### Current live-hover behavior

`LiveWheelTest` smooths 15 samples, warms up for 250 samples, and counts 15 consecutive samples with at least one axis at least 1500 counts from baseline. The count does not require a consistent direction. At trigger time, subthreshold axes are zeroed and the vector maps to the nearest of eight slots:

| Slot | Direction | Initial companion item |
| --- | --- | --- |
| 0 | Up | Hello |
| 1 | Up-right | Thanks |
| 2 | Right | Listen |
| 3 | Down-right | Stay |
| 4 | Down | Back |
| 5 | Down-left | Love |
| 6 | Left | More |
| 7 | Up-left | Spell |

Positive A0 assumes right; positive A1 assumes up. The hover latches until an opposite projection below -1000 counts lasts ten samples, or 2000 samples pass (eight seconds at 250 Hz). Release requires 100 quiet samples below 600 counts, followed by a reset/warmup. Clipping resets it. The app also resets it when a received sample gap exceeds 500 ms.

Gaze visualization was subsequently removed; the companion exposes detector status/readouts. The ring's keyboard focus can remain at the last enabled slot after hover clears. Browser/Pillow HUD renderers use `selected` and do not implement the companion's separate hover styling. A hover aimed at a disabled slot can differ from the ring's retained selection.

The last specific live result was inaccurate directional correspondence, including a repeated center/left trial. Plausible causes include polarity, channel gain differences, baseline drift, onset timing, return pulses and blinks. The repository has not isolated a cause. AC-coupled pulses are not a measurement of continuous absolute gaze position.

### Recording and calibration workflow

`backend.app --serial-port PORT --record recordings/NAME.csv` creates new files only:

- `NAME.csv`: raw samples.
- `NAME.labels.csv`: one `timestamp_ms,intended_label` row per raw sample.
- `NAME.trials.csv`: one `timestamp_ms,intended_label,trial_id,phase,cue,run_id` row per sample.

Files are flushed as samples are written; the three-file set is not a transactional recording. Preserve the complete set and check alignment after a failure. Stop recording keeps acquisition/server running but cannot start a new recording in that same session; restart with a fresh filename. Stop guided test leaves recording running.

Guided protocols are server-timed: horizontal 175 seconds, vertical 225 seconds, double-blink-only 75 seconds. Horizontal includes five left, five right and five single-blink trials. Vertical includes five each of up, down, single blink and double blink. Hidden pages do not pause the protocol. There is no integrated four-cardinal-direction calibration wizard.

`scripts.fit_calibration` uses medians of neutral/left/right/up/down labels, requires at least five samples per class, and rejects duplicate label timestamps. It fits baseline, scale and polarity for the normalized classifier; it does not fit a validated event detector or configure `LiveWheelTest`. Host-rate estimates can be overridden with measured MCU rate. A hold-window median may also fail to represent an AC-coupled movement pulse; review the waveform rather than treating a produced file as a successful calibration.

Two synthetic fixture systems exist: `backend.scenarios` uses replacement-suffix `.labels.csv`; `backend.eog_scenarios` uses appended `.csv.labels.json` event labels consumed by `backend.detect`. They are not interchangeable label schemas.

## 6. Communication, speech, and personalization

### Wheel rules

The companion has eight stationary slots, indexed clockwise from the top. Phrase slots are `0,1,2,3,5`; Back is `4`, More `6`, Spell `7`. Navigation skips disabled slots. Clicking a slot focuses it; Select/Space activates it. UI wording suggesting that a slot click alone confirms is inaccurate.

Home Back opens Needs and confirms “Give me a moment.” Needs Back returns Home. More advances through finite pages; it does not request another model generation. Model responses contain at most five usable suggestions, so More is normally disabled for generated replies.

Spelling recursively splits A–Z into two groups and offers local completions, Space, Delete and Speak. Drafts are bounded to 280 characters. Back first rewinds letter groups. There is no general punctuation, numeric, or multilingual spelling layout.

Each confirmation increments `selection_id`. History retains 12 utterances. Contact changes clear current suggestions/heard text and reset navigation, but retain draft, history, confirmed text and previously shown suggestions. Reset is a view/draft reset, not a deletion of all conversation context. The intended isolation policy needs a decision.

### Suggestions and transcription

- `OLLAMA_MODEL` enables `OllamaSuggestions`; default endpoint is `http://127.0.0.1:11434/api/chat`. Gemini has been removed.
- The request asks for five varied replies, uses JSON output, `think=False`, and a 30-minute keep-alive. Text validation bounds length to 280 characters and removes duplicates; it does not verify factual correctness or enforce every prompt instruction.
- Labels are derived from opening words, bounded to 14 characters. Different replies can still have indistinguishable labels; full preview text matters.
- The browser records up to 12 seconds using `MediaRecorder`. It sends base64 audio to the application; the application sends audio to `ASR_URL`, and only the resulting text goes to Ollama.
- ASR accepts bounded encoded requests, decodes through ffmpeg to 16 kHz mono, and processes at most 30 seconds of decoded audio. The client bounds audio to 2.5 MB and transcript text to 300 characters.
- Qwen is the only implemented ASR provider. An unreachable ASR service does not trigger cloud transcription.
- ASR can work without Ollama: the transcript appears while the phrase pool stays unchanged. Typed suggestion requests require Ollama.
- Model failure preserves the existing pool; after a previous successful generation, that can mean old AI suggestions rather than curated phrases. “Use sample phrases” explicitly restores curated text.
- The application has a shared nonblocking suggestion/transcription lock and a one-second minimum suggestion interval. Browser timeout is 18 seconds, ASR client default 10 seconds, Ollama timeout 60 seconds. There is no request-cancellation protocol spanning these services.
- A ring revision check rejects model results after any ring change during generation, including mere navigation. Context is captured after transcription, leaving a contact-change race during ASR.

### Speech

Speech is enabled separately on a companion browser; the browser HUD stays silent. Existing selections are not automatically spoken when a browser first joins or enables speech. `/api/speech` accepts confirmed history entries, not arbitrary frontend text.

ElevenLabs uses an authorized voice configuration and caches MP3 by text, voice, model and settings. A profile requiring verification disables it. Browser speech is the fallback when unconfigured or when an eligible cloud failure occurs. Audio is played on the browser machine, not automatically on a Jetson speaker.

Claims are remembered before synthesis completes. This reduces duplicate claims but is not a playback receipt or exactly-once audible delivery guarantee. Busy requests, quick successive selections, interrupted playback and reconnects need explicit policy and tests.

`scripts.record_voice` records WAV samples locally; `scripts.create_voice` validates by default and only uploads with `--execute --rights-confirmed`; `scripts.warm_speech` can consume provider quota. These are separate from normal app startup. Piper is installed by the Jetson setup script but has no application speech adapter.

### Personalization and data locations

`/contacts` supports adding people, inspecting a UTF-8/WhatsApp ZIP export, choosing the user's speaker name, replacing/removing a profile, and previewing retrieved examples. It does not train the model. The source export is read in memory; the derived profile stores selected text exchanges on the backend machine.

Profiles retain at most 2000 short exchange pairs and 200 openers. Turns longer than 200 characters are excluded from the short-reply extraction. Four examples are retrieved using word overlap weighted by rarity, then filled with recent exchanges. Retrieval tokenization is English-oriented. Openers are stored but not currently included in the model example context. A per-contact profile falls back to `default`; having no profile does not disable Ollama generation.

| Data | Location/lifetime | Important boundary |
| --- | --- | --- |
| Raw EOG and sidecars | `recordings/` on acquisition host | Ignored by Git; no automatic retention/deletion policy. |
| Voice samples/transcripts | `voicebank/` | Ignored; explicit upload helper can send audio to ElevenLabs. |
| Persona profiles | `config/persona.<id>.local.json` | Ignored; excerpts reach configured Ollama endpoint during generation. |
| Added contacts | `config/contacts.local.json` | Ignored; survives backend restart. |
| Calibration/voice profiles | `config/*.local.json` | Ignored; runtime configuration must be transferred privately if moving hosts. |
| Generated TTS | `.cache/tts/` in the companion | Ignored, persistent audio cache, no eviction policy. |
| Current ring/history/heard text | Backend memory | Lost on process restart; shared by connected clients. |
| Browser microphone audio | Browser/application/ASR memory in this flow | Sent across devices if backend or ASR is remote; not intentionally saved by ASR service. |
| Session token | Browser session storage and host environment | Not a per-person account or permission system. |
| Training JSONL export | User-selected CLI path | Not automatically ignored unless placed under an ignored directory. No training pipeline exists. |

“Local” means the configured machine(s), not necessarily the user's browser device. Remote `OLLAMA_URL` receives transcript, recent utterances and selected persona examples. `ASR_URL` receives audio. ElevenLabs receives confirmed text and voice configuration when enabled. Update privacy copy to reflect those destinations; the current unconditional “on this device” wording is too strong.

## 7. API and state contracts

| Route | Purpose and request requirements |
| --- | --- |
| `GET /api/health` | Backend is answering; returns schema/session. Does not establish sensor/model readiness. |
| `GET /api/state` | Shared ring plus input, recording, guided, hover, provider-configuration and recent-sample snapshot. |
| `GET /api/people` | Contacts and profile summaries, default profile, session ID. |
| `POST /api/action` | `action`, unique `event_id` (1–80 characters), optional `value`. |
| `POST /api/suggest` | `session_id`, `heard_text` or base64 audio plus MIME type. Updates preview pool/transcript. |
| `POST /api/transcribe` | `session_id`, `audio_b64`, optional `mime_type`. Returns transcript metadata without changing ring. |
| `POST /api/persona` | `session_id`, action and relevant fields. Actions: `add_contact`, `inspect`, `save`, `remove`, `preview`. |
| `POST /api/speech` | `session_id`, confirmed `selection_id`. Returns MP3 or browser-speech text; duplicate claim returns 409. |

Action names: `left`, `right`, `select`, `back`, `reset`, `focus`, `contact`, `repeat`, `demo`, `blink`, `label`, `wheel_test`, `guided_start`, `guided_stop`, `record_stop`, `suggestions_clear`.

Useful state distinctions:

- `session_id` changes on backend restart; `revision` tracks ring changes, not every signal/sample/status update.
- `selected` is keyboard/ring focus; `gaze_hover.slot` is separate experimental feedback.
- `sensor_actions` in the response is true for either calibrated navigation or experimental hover. Inspect `wheel_test` too.
- `suggest_available`, `transcribe_available`, and speech provider selection indicate configuration, not successful service health checks.
- Recent command IDs are deduplicated in a 256-entry in-memory deque; speech claims use 128 entries. Neither is durable idempotency.
- `/api/action` lacks a session ID or expected revision check. A delayed Select acts on the current server selection, which may differ from the client's earlier preview.

Default JSON body limit is 4096 bytes; suggest/transcribe allow 4 MiB and persona allows 12 MiB. Non-loopback application binding requires `APP_TOKEN`; configured API access uses bearer auth. Cross-origin POST requests with a mismatched Origin host are rejected. All authorized clients share the same capabilities; browser HUD read-only behavior is a UI property, not a separate API role.

Qwen ASR is a separate service: `GET /health`, `POST /transcribe`; it requires `ASR_TOKEN` for non-loopback binding and allows one inference at a time. Neither service is a hardened public deployment.

## 8. Running and integrating the project

Run commands from the repository root. Use the virtual environment's Python; `python3` is typical on Linux/macOS and `python` on Windows. Python 3.10+ is the stated requirement; this audit ran 3.14.3 on Windows.

### Dependencies and configuration

| File | Role |
| --- | --- |
| `requirements.txt` | pyserial 3.5; live USB acquisition. |
| `requirements-dev.txt` | Playwright 1.63.0; browser acceptance. |
| `requirements-display.txt` | Pillow; image HUD rendering. |
| `requirements-voice.txt` | sounddevice; local microphone recording tools. |
| `requirements-asr.txt` | qwen-asr 0.0.6; separate ASR environment also needs compatible torch and ffmpeg. |

`.env` is loaded relative to the working directory by the app and provider helpers. Nonempty file values fill absent environment variables; existing shell values win. Do not print or commit credentials.

Main variables: `APP_TOKEN`; `OLLAMA_MODEL`, `OLLAMA_URL`; `ASR_URL`, `ASR_TOKEN`, `ASR_TIMEOUT_S`; service-side `ASR_MODEL`, `ASR_DEVICE`, `ASR_LANGUAGE`, `ASR_HOST`, `ASR_PORT`; `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`, `VOICE_PROFILE_PATH`, `SPEECH_CACHE_DIR`. The companion currently passes an explicit cache path and therefore ignores `SPEECH_CACHE_DIR`; standalone speech tools can honor it.

### Basic commands

```sh
python -m scripts.doctor
python -m backend.app
python -m backend.app --serial-port PORT
python -m backend.app --serial-port PORT --record recordings/trial-01.csv
python -m backend.app --replay examples/nano_r4_bench.csv
python -m backend.review_glances recordings/trial-01.csv --threshold 1500
python -m backend.vertical_features recordings/trial-01.csv
python -m backend.review_blinks recordings/trial-01.csv
```

Create `recordings/` first when needed, discover the actual port, close other serial readers, and use a new output name. The bench replay is voltage-transport data, not eye data. The existing macOS port and “server left running” statements in PROJECT_STATUS are historical, not this machine's inventory.

`--calibration PATH --enable-sensor-actions` enables only the calibrated left/right path and requires serial or replay. `--lowpass-hz` also requires calibration. Do not use those flags during guided capture. Current CLI validation does not forbid recording and calibrated navigation together; the acquisition workflow requires keeping navigation off.

`python -m scripts.dev` can launch the app and local ASR from `.venv-asr` when `ASR_URL` is loopback and its health endpoint is not answering. It can instead reuse a remote/tunneled ASR. It does not launch Ollama. `--no-asr` skips ASR startup/checking; it does not erase ASR configuration from the app.

The terminal keyboard simulator now contains a Windows `msvcrt` path. This audit did not exercise physical keyboard/serial behavior on all operating systems. The old blanket “macOS/Linux only” claim is stale.

### Jetson-first integration recipe — proposed, verify on hardware

1. Record the actual Jetson model, JetPack/L4T, OS, Python, torch/CUDA and model IDs. The repository plans for an Orin Nano Super Developer Kit; the owner's “Jetson works” report did not supply that inventory.
2. Start Ollama and Qwen ASR on the Jetson. If `backend.app` is there too, configure its `OLLAMA_URL` and `ASR_URL` to those Jetson-local services. Start/warm models before the demo and measure them together.
3. Run one `backend.app` on the Jetson. Its default loopback binding can be exposed to the computer over an SSH tunnel. Connect Nano USB to the Jetson only if that is the agreed acquisition arrangement.
4. On the computer, for a Jetson app listening on port 8765, a proposed tunnel is:

   ```sh
   ssh -N -L 8765:127.0.0.1:8765 USER@JETSON
   ```

   Open `http://127.0.0.1:8765` on the computer. The local port must be free. Browser microphone acquisition still occurs on the computer, while HTTP requests reach the Jetson app.
5. Test Listen, typed suggestions, explicit selection, speech playback, `/hud`, service failure and reconnect using that exact topology. If using `APP_TOKEN`, enter it in the browser; the tunnel does not bypass application auth.

The tunnel approach is a deployment proposal, not a tested result here. Browser microphone capture requires permission and a secure context. Loopback origins are treated as potentially trustworthy; a plain `http://JETSON_LAN_IP:8765` page generally does not satisfy that requirement. Use a suitable HTTPS deployment or verify the localhost tunnel. A bearer token alone does not solve browser secure-context requirements. See [MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia) and [MDN secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts).

If the Nano stays plugged into the computer while the app moves to the Jetson, an acquisition relay is missing. `/api/action` is not a raw-sample ingest API, and the browser does not currently read Web Serial. Decide this before claiming a complete Jetson architecture.

The earlier laptop-app/Jetson-ASR topology remains a useful intermediate fallback and is described in [JETSON_HANDOFF](docs/JETSON_HANDOFF.md). Label which topology was actually demonstrated.

### Setup and packaging limits

`scripts/setup_jetson.sh` installs packages, environments, serial-group access, power mode, Ollama/model, Piper/voice and Qwen ASR dependencies, then performs tool smoke checks. It changes the machine and downloads models; reading this handoff is not a reason to rerun it on an already working Jetson. Inspect the current installation first.

Script checks do not establish audible playback, microphone access, Nano acquisition, browser integration, or optical operation. `scripts.doctor` reports dependencies/ports but does not fail merely because a dependency is missing; its exit code is not a complete readiness gate. The setup script's reported dialout membership can differ from groups active in the current login. Its optional power-check bypass and unpinned downloads also limit reproducibility.

Docker packages the companion, not the full Jetson model stack. It has no documented persistent-volume or serial-device integration recipe. Profiles/cache stored only in a disposable container can disappear with that container.

## 9. Hackathon work order and integration checks

This is a proposed execution order based on the owner's priorities, not a record of completed work. Keep the EOG and Jetson work parallel. Named owners, active branches and remaining hackathon time are not known.

### First: establish the common integration contract

- Agree which machine runs `backend.app`, where Nano USB connects, and which device plays speech.
- Choose the current demo input path explicitly: manual, calibrated left/right, or experimental spatial hover. Do not combine detector outputs without defining arbitration.
- Freeze raw units, sample-rate assumptions, slot mapping, API fields and confirmation semantics while both workstreams integrate.
- Record each team's branch/commit and any changes to shared files, especially `app.py`, `ring.py`, frontend state fields and firmware transport.

### EOG workstream

1. Capture a quiet baseline and labeled cardinal movements with distinct center returns; collect blinks and neutral periods as negative cases. Preserve setup notes and the exact raw/sidecar set.
2. Review polarity, clipping, channel noise, gain/leakage and pulse shape before changing thresholds. Fix the duplicate-timestamp calibration workflow if using that fitter.
3. Choose and configure the detector actually driving the demo. Prioritize repeatable cardinal behavior over adding more directions or visual effects.
4. Evaluate unchanged settings on fresh recordings, reporting intended trials, correct/wrong directions, misses, duplicates, false triggers and latency. Keep fitting data separate from evaluation data.
5. Only add diagonal control and deliberate biological confirmation after the preceding behavior is established. Retain an explicit manual fallback for the hackathon demonstration.

### Jetson workstream

1. Reuse the working Jetson installation and record exact versions. Bring up the application and models in the agreed topology.
2. Fix or bypass the broken transcription CLI with a documented check; establish real mic-to-transcript behavior before testing generated replies.
3. Resolve the 18-second browser/60-second model timeout mismatch. Verify that a timed-out or outdated request cannot unexpectedly replace phrases later.
4. Exercise microphone, ASR, Ollama, selection, browser audio and a second display together. Measure warm/cold latency and memory with both models loaded, rather than estimating from model names.
5. Rehearse a model outage and a server/tunnel restart. Curated/manual communication and visible errors must remain understandable.

### Joint demo gates

These are recommended checks; no numerical EOG accuracy target has been approved. A short clean demonstration is not validation for ALS use.

| Gate | Observable result to record |
| --- | --- |
| Shared state | Companion and HUD show the same screen, focus and confirmed phrase from one backend. |
| Input identity | Real, replay and synthetic modes are unmistakable. Measured rate and loaded detector configuration are recorded. |
| Navigation | Fresh repeated cardinal trials report correct, wrong, missed and duplicate movements; returns/neutral/blinks are scored too. |
| Confirmation | Hover/navigation never confirms. Every spoken phrase has an explicit confirmed selection. No unintended confirmation occurs during the demo test. |
| Experimental mode | Starting/stopping/staling the wheel test clears appropriate feedback and enforces the intended speech policy. |
| Listening | Computer mic audio reaches the intended ASR host and the resulting transcript belongs to the intended contact/request. |
| Suggestions | New replies remain previews; movement during generation and contact changes have defined results. |
| Speech | Selected text is audibly played once on the intended device; busy/failure behavior is exercised. |
| Recovery | Unavailable ASR/Ollama, disconnected serial, and backend restart show an explicit state and a usable fallback. |
| Reproducibility | Exact commands, commits, configuration IDs and remaining failures are in the handoff, without private data. |

Defer fine-tuning, additional providers, automatic voice uploads, a broad UI redesign, production multi-user deployment, and a new wireless protocol unless required for the chosen demo. Physical glasses work can continue separately, but do not make an unbuilt display a prerequisite for testing EOG or the Jetson loop.

## 10. Open implementation gaps

All entries below were open at the audited commit. **Reproduced** means a focused check confirmed the behavior. **Inspected** means the relevant code path supports the finding but no full end-to-end reproduction was run. Priorities indicate the next affected integration step, not a clinical risk ranking.

| ID | Priority / evidence | Gap, effect, and next useful check |
| --- | --- | --- |
| G01 | Jetson blocker; reproduced | `scripts/try_transcribe.py` imports nonexistent `record` from `scripts.try_suggest`. Even `--help` fails with ImportError. Restore a shared mic helper or replace the import; test all three CLI modes, including health without mic dependencies. |
| G02 | Joint integration; inspected | ESP32 wheel/bridge bypass canonical companion state, confirmation and speech claims. Either label it a separate prototype or implement an explicit state adapter; verify phrase and utility parity. Optional WebSocket firmware has no server counterpart. |
| G03 | EOG blocker; inspected | Live-hover thresholds/polarity/timing are hardcoded and disconnected from calibration. Direction consistency, blink rejection, and channel scaling remain unresolved. Test calibrated parameters on the live path, not merely the normalized classifier. |
| G04 | EOG workflow; reproduced | Replay permits duplicate receipt timestamps; calibration labels reject them. Fix alignment using sample identity/order with validation rather than guessing timestamp uniqueness. Preserve compatibility with existing recordings. |
| G05 | Jetson integration; inspected | Frontend aborts at 18 s while Ollama may run 60 s, after ASR time. Backend work can continue and apply a result after the browser reports failure. Define bounded timing and request ownership/cancellation; test slow success and late result rejection. |
| G06 | Conversation correctness; reproduced | Contact can change during ASR before request context is captured. A fake ASR callback changing Kenny to Kat resulted in Kenny's transcript displayed under Kat. Capture/check context across the entire listen-and-suggest operation. |
| G07 | Speech policy; reproduced | `wheel_test_selections` is created/read but never populated by normal command handling. A manual selection during the test could be claimed through `/api/speech` after stopping it. The existing test manually populates the deque, masking the missing production step. Decide the intended post-test policy and test normal command flow. |
| G08 | Speech delivery; inspected | Browser marks a selection seen before a busy speech request can accept it; rapid selections can be skipped. Server records a claim before checking its speech lock or completing synthesis, so a busy/failing claim may not be retryable. Define queue/latest-only/retry behavior and test two companions and rapid confirmation. |
| G09 | Preview correctness; inspected | `/api/action` has no session/revision/expected-selection guard. A delayed Select can confirm a different current item after another client or a suggestion refresh changes state. Define what the user is confirming and reject stale commands accordingly. |
| G10 | Conversation policy; reproduced | Contact changes retain draft/history/shown suggestions. Prior-contact utterances can reach a new contact's reply prompt. Decide whether this is intended global context or should be separated per contact; do not silently change it. |
| G11 | Privacy/documentation; inspected | UI/module text promises device-local conversations, but configurable remote Ollama/ASR endpoints and optional ElevenLabs change destinations. Describe actual hosts and payloads. Derived profiles and TTS cache have no retention/backup policy. |
| G12 | Data recovery; reproduced + inspected | `contacts.local.json` containing JSON `null` raises TypeError; persona validation checks only limited structure. Profile/contact writes are not atomic and all save/remove paths lack a shared persistence lock. Test malformed valid JSON and interrupted/concurrent writes without destroying existing profiles. |
| G13 | Feedback consistency; reproduced + inspected | At three seconds stale, state reported disconnected but retained hover slot/phase. Companion hides underline via `connected`; the detector clears on later samples/error. HUDs render retained `selected` rather than hover. Define focus/hover/stale display semantics across clients, including disabled slots. |
| G14 | Capture integrity; inspected | Recording and sidecars have no session manifest, sample IDs or atomic finalization. No explicit measured-rate/drop/invalid-line/clipping summary is shown. A five-second serial timeout requires restart. Add the evidence needed to distinguish transport trouble from detector trouble. |
| G15 | Hackathon usability; inspected | UI says “Double blink” despite absent companion biological confirmation; hover text says “click ... to choose” although slot click only focuses. Some setup/contact/listening controls still require ordinary interaction. Specify participant versus caregiver controls and label simulation clearly. |
| G16 | Suggestion interaction; inspected | Any ring revision during model generation invalidates replies, including focus movement. This can conflict with “navigation continues while thinking.” Use a deliberate conversation-context revision policy and test navigation during generation. |
| G17 | Configuration; inspected | Companion hardcodes `.cache/tts`, overriding advertised `SPEECH_CACHE_DIR`. `.env` is working-directory dependent, and the HUD CLI does not load it. Verify effective settings in the intended launcher/deployment without exposing secrets. |
| G18 | Deployment; inspected | Cold-start/model readiness, launcher failure cleanup, HTTPS/tunnel topology, serial permissions and persistent storage lack a demonstrated complete runbook. `scripts.dev` treats unavailable loopback ASR as a reason to start local ASR, including cases where a tunnel/auth check failed. Test the actual deployment instead of relying on startup text. |
| G19 | Data handling; inspected | Arbitrary `profiles/`, root `session.csv` and root training JSONL paths are not ignored, despite broad privacy statements. Existing paths under `recordings/`, `voicebank/` and `config/*.local.json` are ignored. Check every new data output destination. |
| G20 | Validation/reproducibility; inspected | No CI workflow is tracked. New contacts/listening flows, model timing, CLI imports, actual firmware compilation, hardware paths and physical audio are outside the passing suite's evidence. Pin the demonstrated environment and add focused checks for integration regressions. |

Additional product gaps to keep visible: no contact edit/delete UI (profile removal is different); no phrase-bank editor or schema migration; no calibration profile selection/quality UI; no recorded pass thresholds, fatigue/task-completion study, or accessibility evaluation with intended users; no authoritative wearable bill of materials/optics/power assembly record; no complete multilingual input/spelling plan. These are undocumented or incomplete in this repository, not proof the team has never discussed them.

## 11. Documentation contradictions

Resolve these using code plus dated evidence, not whichever file sounds most confident.

| Existing location | Stale or incomplete statement | Current truth |
| --- | --- | --- |
| `docs/SPEECH.md` | No automatic `.env` loading; microphone recording absent. | `.env` loading, browser mic capture and `scripts.record_voice` exist. |
| Local `AGENTS.md` | Gemini with Ollama fallback. | Audited HEAD explicitly removes Gemini; Ollama only. |
| Local `AGENTS.md` | Guided recordings have `.labels.json`. | App capture uses `.labels.csv` and `.trials.csv`; event scenarios use appended `.csv.labels.json`. |
| `docs/ACQUISITION.md`, `paired_glance.py` docstring | Paired-glance prototype is used by the live wheel toggle. | Current `Application` uses `LiveWheelTest`; paired-glance is offline in this checkout. |
| README / SIGNALS / APPLICATION / local `AGENTS.md` | Blanket unsupported Windows terminal statement. | `simulator.py` now has a Windows console implementation; hardware behavior still needs platform checks. |
| README / VALIDATION / PROJECT_STATUS | Latest suite is 133 tests on macOS. | Historical result; this audit ran 141 successfully on Windows 3.14.3. |
| `docs/JETSON_HANDOFF.md` | No Jetson was available. | Historical implementation-session limitation; owner now reports Jetson works. Exact end-to-end checks still need a record. |
| PROJECT_STATUS | Specific macOS port and server left running. | Historical session note; rediscover local devices and server state. |
| People UI / persona/suggestion module descriptions | No profile means curated phrases; everything stays on this device. | Ollama still generates without a persona. Destinations depend on backend and endpoint hosts. |
| Architecture summaries | All displays share canonical ring behavior. | True of companion-derived views; not the standalone ESP32 bridge/firmware. |
| Local `AGENTS.md` | Recording requires sensor actions off as an enforced rule; dev extras include Pillow. | Guided start enforces the action restriction; general CLI recording does not. Pillow is in `requirements-display.txt`, not `requirements-dev.txt`. |

The local `AGENTS.md` is itself Git-ignored. A fresh clone may not contain it. This tracked document and the README link are the portable handoff; do not assume local agent instructions propagate to teammates.

## 12. Repository map

All tracked source and documentation were read during the audit. This map identifies where a future change belongs.

| Files | Responsibility |
| --- | --- |
| `backend/app.py` | Application orchestration, HTTP APIs, workers, recording lifecycle, provider integration. |
| `backend/ring.py`, `config/phrases.json` | Companion interaction state, phrase/Needs banks, contacts, spelling vocabulary. |
| `backend/models.py`, `classifier.py`, `calibration.py`, `state_machine.py` | Normalized samples, cardinal classification, smoothing, navigation/blink-event gates. |
| `backend/serial_input.py`, `recording.py` | Raw acquisition, parser, CSV recording/replay. |
| `backend/guided.py`, `live_wheel.py` | Guided acquisition protocols and independent experimental spatial hover. |
| `backend/events.py`, `detect.py` | Older event detector and CLI for live/replay/scenario event reports. |
| `backend/paired_glance.py`, `review_glances.py` | A0 glance/return detector and offline reporting. |
| `backend/double_blink.py`, `review_blinks.py`, `vertical_features.py` | Offline blink candidates, reviewed-window scoring, waveform measurements. |
| `backend/scenarios.py`, `eog_scenarios.py` | Two different synthetic signal/label generators. |
| `backend/main.py`, `simulator.py` | Terminal keyboard/raw/replay tools and keyboard sample/event sources. |
| `backend/suggestions.py`, `transcribe.py`, `asr_server.py` | Ollama client, remote ASR client, Qwen/ffmpeg service. |
| `backend/persona.py`, `envfile.py`, `speech.py` | Local contact/profile storage and retrieval, env loading, ElevenLabs/cache. |
| `backend/hud.py`, `frontend/hud.js` | Snapshot image/canvas renderers. Neither drives physical optics. |
| `backend/hud_bridge.py`, `config/hud_phrases.json` | Independent serial ESP32 event/speech flow. |
| `frontend/index.html`, `app.js`, `styles.css`, `type.css`, `favicon.svg` | Companion/phone/browser-HUD shell, polling, controls, mic/audio, styling. System fonts need no download. |
| `frontend/contacts.html`, `contacts.js`, `contacts.css` | People and profile-import interface. |
| `firmware/nano_r4_eog_250hz/`, `nano_r4_two_channel/`, `esp32_hud/` | Current ADC acquisition, slow bench acquisition, SH1106 command-driven display. |
| `scripts/dev.py`, `setup_jetson.sh`, `doctor.py` | Local process launcher, target setup, dependency/port report. |
| `scripts/fit_calibration.py`, `browser_check.py` | Initial labeled calibration fitter; browser acceptance and screenshot writer. |
| `scripts/record_voice.py`, `create_voice.py`, `warm_speech.py` | Local voice capture, explicit voice upload, optional paid cache warmup. |
| `scripts/import_chat.py`, `try_suggest.py`, `try_transcribe.py` | Persona import/export/preview and provider diagnostic CLIs. |
| `config/*.example.json` | Arbitrary/example calibration and authorized-voice manifest/profile structures; not participant calibration. |
| `tests/` | 18 modules covering ring, acquisition, classifier/gates, detectors, guided capture, app/API, provider mocks, persona, voice and transcription helpers. |
| `examples/` | 20-row voltage bench fixture, 7500-row synthetic demo plus JSON labels, fictional sample chat. |
| `artifacts/` | Previously generated UI screenshots; not proof of current physical operation. |
| `Dockerfile`, `.dockerignore`, requirements files, `.env.example`, `.gitignore` | Packaging, dependencies, configuration examples and private-path exclusions. |

Detailed guides: [Acquisition](docs/ACQUISITION.md), [Signals](docs/SIGNALS.md), [Interaction](docs/INTERACTION.md), [Speech](docs/SPEECH.md), [Application](docs/APPLICATION.md), [Validation](docs/VALIDATION.md), [Jetson handoff](docs/JETSON_HANDOFF.md), [Earlier EOG status](docs/PROJECT_STATUS.md).

## 13. Verification record

Audit environment: Windows AMD64, Python 3.14.3. Git checkout initially clean at the commit above. Reviewed 102 tracked files, including 70 code/markup/style/firmware files and 57 Python modules, plus local `AGENTS.md`. Private `.env`, participant recordings, voice samples and private profiles were not audited. Prior conversations outside the supplied context were unavailable.

Checks performed:

- Full unittest discovery: **141 passed**, approximately six seconds. Service environment variables were removed from the test child process; provider behavior used test mocks.
- `node --check` passed for `frontend/app.js`, `frontend/hud.js` and `frontend/contacts.js`.
- All 57 Python modules parsed successfully. Parsing does not resolve imports; the transcription CLI failure demonstrates the distinction.
- The complete 7500-row synthetic CSV parsed and exactly matched `eog_scenarios.generate('demo', seed=0)` channel values.
- Focused isolated probes reproduced stale hover state, missing test-selection speech provenance, cross-contact ASR attribution, retained contact context, malformed contact JSON failure and duplicate-label-timestamp fitter rejection.
- `python -m scripts.try_transcribe --help` failed on the missing `record` import.
- `scripts.doctor` found pyserial and Pillow, no serial ports, and no Playwright installation in the audit interpreter.
- Existing screenshot files were structurally checked with Pillow; this was not a fresh visual/browser acceptance run.

Not rerun/verified here: browser acceptance, microphone capture, audible speech, paid APIs, real model inference, Jetson deployment/setup, Arduino compilation/flashing, live EOG, ESP32 hardware, optics, intended-user trials, Docker build/runtime. Earlier docs describe 13 browser acceptance checks and additional ad hoc synthetic hover checks; retain those as historical evidence, not new results.

Standard checks from the project root:

```sh
python -m unittest discover -s tests -v
node --check frontend/app.js
node --check frontend/hud.js
node --check frontend/contacts.js
```

Browser acceptance requires Playwright plus an installed browser and an isolated app session:

```sh
python -m scripts.browser_check --url http://127.0.0.1:8765 --chrome PATH_TO_CHROME
```

It mutates the session and writes screenshots. Use a separate demo with no real provider credentials, private profiles or active acquisition. Current tests are not comprehensively isolated from every developer environment when run individually; inspect `.env`/provider mocking before assuming no local configuration can be read.

## 14. Decisions still open

These need concrete answers when implementing the affected step; they do not prevent using this handoff now.

| Decision | Why it matters / current working approach |
| --- | --- |
| Which machine owns Nano USB? | Jetson-hosted acquisition is the simplest match to the target backend; a laptop-connected Nano needs a relay that does not exist. Physical/power setup must be reviewed separately. |
| What is the demo's successful EOG action? | Choose reliable previous/next versus direct cardinal/spatial focus before combining detectors. Current hover is experimental eight-slot focus; existing plan starts with cardinal measurements. |
| What confirms a real-user choice? | Companion biological confirmation is not integrated. Manual confirmation is the current fallback; no decision establishes a validated blink or dwell policy. |
| What numerical performance gate is acceptable? | Record accuracy/error counts, false activations per exposure time and latency. No target, evaluation duration or held-out dataset standard has been approved. |
| Where should audio play? | Current app plays in the browser. Jetson/portable speaker output requires a separate decision and potentially an adapter. |
| Is ESP32 required for this hackathon demo? | Glasses are unfinished and firmware is independent. Browser HUD can support software integration while display assembly continues. |
| What crosses a contact boundary? | History, draft, confirmed text and suggestion memory currently persist. Define isolation/retention before changing behavior. |
| What data destinations are permitted? | Jetson/LAN processing is consistent with the target; cloud TTS exists as an optional feature. No blanket offline-only or cloud-required policy was supplied. |
| Who is the operator? | Define which controls are for the communicator and which are for a caregiver/demo operator, including calibration, contacts, listening and recovery. |
| Who owns each integration boundary? | Record team members/branches and a shared tested commit. No names or active work ownership were supplied. |

## 15. Keeping this document true

For every material change, update the relevant behavior, open-gap status and verification record here. Keep detailed procedures in their domain guides and correct any contradiction introduced there. Do not duplicate long implementations into this file.

Use this compact handoff for a completed work session:

```text
Date / contributor / branch / commit:
Goal and user-visible change:
Machines and services actually used:
Input source and detector configuration:
Checks run and observed results:
Evidence location (private references only; no raw participant data):
Known failures / untested claims:
Next action / owner:
NUGGET gap IDs resolved or added:
```

A fix is complete only when its actual production path has been checked; a test that manually creates the missing state is insufficient. For a hardware/service claim, record the concrete setup and observation. For a new product decision, distinguish owner-approved direction from an agent's proposed next step.

No application, firmware or detector defects were fixed as part of this documentation audit. Keep section 10 entries open until subsequent work supplies the implementation and evidence.

### 2026-10-10 — Continuous EOG experiment branch

Branch: `experiment/eog-continuous-detection`, based on main `301cfef`.
Gaze visualization was removed before this branch; earlier underline descriptions
above are historical. Existing reviewed recordings are sufficient for current
algorithm development; do not request a blanket repeat of acquisition.

Added offline causal segmentation and continuous replay comparison. Detectors
receive raw values only, run whole files, and reset on transport gaps/clipping,
not movement cues. Labels fit training examples and score held-out repetitions.
The current live-hover comparator reproduced a stall and missed all 20 scored
cardinal trials in full replay. This differs from cue-reset window experiments.
Initial learned 1s waveforms found 11/20 with 9 false directions over 275s scored
negative exposure. Adaptive blink cooldown, bounded DC adaptation, opposite-return
suppression and uncertain-event rejection improved development replay to 16/20,
0 wrong directions during scored movements and 6 false directions over 275s.
These reused-data results remain development evidence, not independent validation.
No new detector is connected to Application or confirmation. G03 remains open.
See forthcoming continuous experiment guide for refinements and reproducibility.

### Continuous experiment refinement and final branch handoff

Compared twelve continuous variants and an alternative onset alignment using
existing recordings only. Default waveform/rejection:16/20 correct movements,
0 wrong directions during movements,0 duplicate correct events,6 false directions
over275s negative exposure; median cue-to-emission1.51s. Small LSTM:15/20 with
16false; three-layer recurrent model:14/20 with23false. These are reused-data
development comparisons, not independent validation. New explicit candidate
profile/replay CLI runs without labels; verified on68873rawsamples.149tests pass.
No app/serial/confirmation integration changed; G03 remains open. Next inspect
missed and false candidates, then opt-in diagnostic integration. Full methods,
commands, results and limits: [Continuous EOG experiments](docs/EOG_CONTINUOUS_EXPERIMENT.md).
Gaze highlighting remains removed. No further blanket acquisition requested.

### Continuous replay error review

Of four strict misses, three had correct-direction onsets12/40/180ms before the
cue (boundary ambiguous). Preserve strict16/20; do not claim19/20validated accuracy.
Fourthleftcandidate was rejected(distance0.16873>0.08); its opposite return then
emittedright because suppression tracks only accepted directions. Sixfalse counts
include those threeearlyevents, thatreturn, andtwoblink-relatedupcandidates.
Next separate scoring-boundary uncertainty from detection errors and preserve
return tracking after a rejected excursion. Detailed evidence is in the continuous
guide; no detector or scorer was changed by this inspection.


### Shape, retry and baseline follow-up (2026-10-10)

See [improvement roadmap](docs/EOG_IMPROVEMENT_ROADMAP.md) for the requested guided-center/retry design,
research assessment and implementation priorities. New opt-in replay variants:
3s retry gate15/20 with5false directions;5s gate14/20 with4false over275s.
Existing waveform rejection remains16/20 with6false. Remembering rejected
labels, extra shape features and stable-only baseline replacement did not improve
the overall result; retain them as documented comparisons, not live defaults.
No application, OLED, confirmation or speech integration changed.


### Integrated guided EOG mode — 2026-10-10

The experimental branch now has opt-in app integration using --eog-profile:
three-second guided center, hybrid DC/rest estimates, five-second retry,
recovery/return suppression, uncertain horizontal blink handling and quality
faults. Cardinal focus only; no automatic confirmation or speech. Browser HUD
shows status without gaze highlighting. Private raw/decision logs and a short
readiness-aware live protocol are available. Selected exact-runtime replay:
16/20 correct,0wrong/duplicates,3false candidates/275s (two boundary ambiguous,
one blink-related up); median cue-to-emission1.51s. Existing main behavior
without the profile flag is unchanged. Physical OLED status adapter is untested.
See [live-check guide](docs/EOG_LIVE_CHECK.md) for evidence, launch instructions and remaining
limitations. Earlier statements that no integration exists are historical.


### Homepage speed-check follow-up

First live manual check: operator confirms intended cardinal responses and
retry for an untrained diagonal; no cue labels, so no numeric accuracy claim.
A new homepage button starts a recorded12-direction speed check after center.
Cue-to-response (includes reaction/UI delay) and candidate-window timing are
reported separately; early candidates are flagged. Detector settings remain
fixed.169tests run:168pass,1optional skip; homepage flow browser-checked.
See EOG_LIVE_CHECK.md for definitions and the live recording limitations.

For the current detector investigation and continuation instructions, read [Claude development handoff](docs/CLAUDE_HANDOFF.md). Double-blink pulse-shape diagnostics are observational pending replay validation.
