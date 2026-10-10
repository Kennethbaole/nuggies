# Nuggies

An eye-movement communication prototype using two BioAmp EXG Pills, an Arduino
Nano R4 and a Python host, with phrase selection and speech output.

Requires Python 3.10+. Components are being implemented incrementally; empty
scaffold files are not functional features. Hardware control, biological blink
detection and physical display operation are not yet validated.

Private recordings, voice samples, local profiles, credentials and environments
are excluded from Git. Never commit real API keys or participant recordings.

Implementation and usage documentation will grow with each working component.

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
See [Speech](docs/SPEECH.md). Credentials use exported environment variables;
automatic .env loading and microphone recording are not implemented.

## Run the companion

```sh
python3 -m backend.app
```

Open http://127.0.0.1:8765. Left/Right navigates; Space confirms; B twice
simulates blinks. Browser speech requires Enable speech. Companion, phone and
silent HUD share state. Nuggies is the temporary product name.
See [Application and labeled capture](docs/APPLICATION.md).

Live EOG, biological blink detection, physical optics and target-device operation
remain unverified. AI suggestions, microphone recording, automatic .env loading
and Jetson provisioning are not implemented. The terminal tools require macOS/Linux.

## Validation and next milestones

38 unit/API tests and 13 browser acceptance checks pass on macOS.
See [Validation](docs/VALIDATION.md) for commands, evidence limits and the
next hardware milestones. Optional container packaging is supplied but untested.
