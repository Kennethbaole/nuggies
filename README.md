# Glint

Project name: Glint. The source repository remains `Kennethbaole/nuggies`.

An eye-movement communication prototype using two BioAmp EXG Pills, an Arduino
Nano R4 and a Python host, with phrase selection and speech output.

Requires Python 3.10+. Components are being implemented incrementally; empty
scaffold files are not functional features. Hardware control, biological blink
detection and physical display operation are not yet validated.

Private recordings, voice samples, local profiles, credentials and environments
are excluded from Git. Never commit real API keys or participant recordings.

Implementation and usage documentation will grow with each working component.
See [Current status and next session](docs/PROJECT_STATUS.md) for the live EOG
movement mismatch, removed gaze highlighting, and calibration deliverable.

## Raw acquisition

Two-channel parsing, lossless recording/replay, a voltage bench fixture and
firmware are implemented. See [Acquisition](docs/ACQUISITION.md).

```sh
python3 -m unittest discover -s tests -v
```

## Capture and signal tools

The terminal CLI supports raw USB capture, replay and keyboard simulation.
Calibration, seeded scenarios and temporal gates are implemented and tested
with software fixtures. See [Signals and capture](docs/SIGNALS.md).

## Phrase selection

The authoritative eight-slot ring supports Needs, More, spelling and explicit
confirmation. See [Interaction](docs/INTERACTION.md).

## Speech

The ElevenLabs adapter, cache and explicit voice-upload helper are implemented.
Reply suggestions use local Qwen through Ollama; Gemini is no longer a provider.
The Community page takes a short notes file per person (pronouns, nicknames,
tone) to personalize replies without fine-tuning.
See [Speech](docs/SPEECH.md). Speech-to-text for heard replies runs Qwen3-ASR on the
Jetson, reached from the laptop through ASR_URL; see [Jetson handoff](docs/JETSON_HANDOFF.md#4-speech-to-text-link-qwen-on-the-jetson-mic-on-the-laptop). Credentials use exported environment variables;
the app supports .env loading and browser microphone recording.

## Run the companion

```sh
python3 -m backend.app
```

With Qwen speech-to-text, `python3 -m scripts.dev` starts the app and the Qwen
service together as hidden background processes in one terminal; Ctrl+C or
closing the terminal stops both.

Open http://127.0.0.1:8765. Left/Right navigates; Space confirms; B twice
simulates blinks. Browser speech requires Enable speech. Companion, phone and
silent HUD share state. Nuggies is the temporary product name.
See [Application and labeled capture](docs/APPLICATION.md).

Live two-channel EOG acquisition has been exercised. Experimental directional
hover is implemented but does not yet reliably match intended gaze. Biological
confirmation, physical optics and target-device operation remain unvalidated.
Reply suggestions and browser microphone transcription are implemented; real
service/device validation is separate. The terminal tools require macOS/Linux.

## Validation and next milestones

The latest full suite passed 144 tests on macOS. Browser checks cover companion
interactions and synthetic eight-direction gaze feedback.
See [Validation](docs/VALIDATION.md) for commands, evidence limits and the
next hardware milestones. Optional container packaging is supplied but untested.

## Offline EOG algorithm development

Existing reviewed recordings can train and evaluate temporal waveform templates
and a paper-inspired LSTM without more acquisition. See [Sequence experiment](docs/EOG_SEQUENCE_EXPERIMENT.md).
Optional experiment dependencies are separate from the app. Reports and models
remain private under recordings/. Gaze visual highlighting is currently removed.


### Guided EOG diagnostic mode (experimental branch)

An opt-in waveform detector supports instructed center, retry/recovery, quality
feedback and a short recorded live check. It focuses cardinal slots without
automatic confirmation or speech. See [the live-check guide](docs/EOG_LIVE_CHECK.md)
for private-profile preparation, startup, replay evidence and limitations.
