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
