# Validation and remaining work

## Software checks

38 unit/API tests pass on macOS with Python 3.14, including raw CSV handling,
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

## Hardware milestones

1. Identify exact Pill revisions, connectors, electrode leads and power setup.
2. Choose and document acquisition timing; the included sketch is a slow bench
   check, not final physiological acquisition firmware.
3. Collect labeled raw EOG on the laptop without sensor actions enabled.
4. Evaluate calibration on separate trials, including drift, saturation, held
   gaze, returns, spontaneous blinks and intentional blinks.
5. Implement biological blink detection, then verify navigation, confirmation,
   false activations and latency end to end.
6. Evaluate target-device audio, physical display and optics separately.

No live EOG, biological blink detector, Jetson setup, physical OLED driver,
optical legibility or real cloud synthesis was verified during these checks.
The voltage bench fixture is transport evidence only.

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
