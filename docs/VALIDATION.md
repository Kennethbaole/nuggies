# Validation and remaining work

## Software checks

The latest full suite of 144 tests passed on macOS with Python 3.14, including raw CSV handling,
calibration fixtures, gesture gates, ring behavior, labeled capture, API access
boundaries and mocked speech. Both browser JavaScript modules pass syntax checks.

13 browser acceptance checks pass using installed Google Chrome through
Playwright: labeling, navigation, explicit selection, phone mirror, shared HUD,
stationary ring, More, spelling, Back, speech fallback invocation, silent
highlight changes, mobile overflow and browser exceptions. Speech synthesis is
spied in this check; audible output is not measured. Generated desktop and mobile
screenshots use the temporary Nuggies name.

```sh
python3 -m unittest discover -s tests -v
node --check frontend/app.js
node --check frontend/hud.js
```

For browser checks, start the app and install requirements-dev.txt. Install
Playwright Chromium with `python3 -m playwright install chromium`, or pass
`--chrome` with an installed Chrome executable:

```sh
python3 -m scripts.browser_check --chrome /path/to/chrome
```

The browser check writes screenshots into artifacts/ and changes the running
demo session. Use an isolated local session without cloud credentials.

## Hardware status and next milestones

Two-channel 250 Hz Nano R4 acquisition and labeled eye-movement recordings have
been exercised with both Pills. Offline paired-glance and double-blink prototypes
exist. Live experimental radial hover is implemented, but the user reports that
its directions do not reliably match actual movements. Do not interpret passing
software tests as validated EOG control.

Isolated browser checks additionally fed synthetic ADC samples through app ingest
for all eight directions, previously verified underline-only feedback, return/stop clearing,
and no gaze activation. These ad hoc checks do not measure biological accuracy.

Next: use existing labeled recordings to improve continuous temporal detection
and recovery, then verify a measured improvement with a targeted fresh trial. Add diagonal
classification and blink rejection after cardinal directions work. Biological
confirmation remains offline; physical OLED/optics, target-device behavior and
real service audio require separate validation. See [Current status and next
session](PROJECT_STATUS.md) for the detailed handoff.

## Optional container

Dockerfile packages the Python app as a non-root user. Supply APP_TOKEN at runtime
because the container binds beyond loopback. The build context excludes private
data. Docker build/runtime has not been tested; do not treat packaging as verified
deployment or production hardening.

```sh
docker build -t nuggies .
docker run --rm -p 8765:8765 --env APP_TOKEN nuggies
```

The server uses in-memory state and requires one process for a shared session.

## Offline sequence experiment

The optional experiment evaluates supervised temporal models on reviewed local
recordings. Tests cover allowlisted runs/classes, exclusion of skipped classes,
metadata alignment, duplicate trials, repetition assignment and confusion
accounting. [Experiment documentation](EOG_SEQUENCE_EXPERIMENT.md) defines the
split, reproducible commands, measured outcomes and limits. UI gaze highlighting
is removed; status/readouts remain.
