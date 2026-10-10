# Nuggies companion application

```sh
python3 -m backend.app
```

Open http://127.0.0.1:8765. Left/Right navigates, Space confirms, B twice
simulates individual blink events, Escape goes Back. Clicking a slot only
highlights it. Enable speech on one companion for future confirmed selections.
`/phone` is the responsive companion and `/hud` is a read-only silent display.
Synthetic and replay sources are identified in the interface.

## Record labeled trials

```sh
mkdir -p recordings
.venv/bin/python -m scripts.doctor
.venv/bin/python -m backend.app --serial-port PORT --record recordings/trial-01.csv
```

Discover PORT, close Serial Monitor and use a fresh recording name. Set the
Signal workspace trial label before each intended gesture. The app writes raw
CSV plus a matching .labels.csv sidecar, defaulting to unlabeled. Labels are
intentions, not predictions. The trace is raw ADC counts. Without calibration
and --enable-sensor-actions the app only monitors; it does not navigate from
raw signals unless the opt-in experimental eye wheel test is enabled. That mode
uses independent fixed thresholds and is not yet reliable directional control. Read [Signals](SIGNALS.md) and [Acquisition](ACQUISITION.md).

```sh
python3 -m backend.app --replay examples/nano_r4_bench.csv
```

The voltage fixture verifies transport only. Real calibration needs independent
trial evaluation. Biological blink confirmation is not integrated into the live app, so sensor input
cannot currently confirm a phrase. Disconnects pause input; restart after fixing
the port. Manual and replay modes remain available.

## Shared state and API

The browser polls every 250 ms; ring.py owns navigation and confirmation.
GET /api/health and /api/state expose the session and shared snapshot.
POST /api/action accepts an action and a unique event_id, with validated values.
Supported actions include left, right, select, back, reset, focus, contact,
repeat, demo, label, simulated blink, wheel_test, guided_start, guided_stop,
and record_stop. Recent event IDs are deduplicated in
memory. POST /api/speech requires session_id and a confirmed selection_id;
duplicate claims return 409. Only confirmation changes the spoken selection.

Non-loopback hosting requires exported APP_TOKEN. API requests use bearer auth;
cross-origin writes are rejected. Tokens are entered in the companion and kept
in session storage. State is in memory, one shared session per server process.
This standard-library server is a development prototype, not a hardened public
production service. Reply suggestions, .env loading and browser microphone
transcription adapters are implemented; Windows terminal controls remain unsupported.

## Display

The browser HUD and optional backend.hud renderer consume the same state. Pillow
can export a monochrome image while the app is running:

```sh
python3 -m backend.hud /tmp/nuggies-hud.png
```

This does not drive an OLED or establish optical legibility. Physical controller,
resolution, power and optics must be identified and tested separately.

## Experimental gaze feedback and current issue

The eye wheel test underlines the detected directional slot without activating it.
It requires live serial input and excludes guided tests/calibrated navigation.
Speech is disabled during the test. Detection remains inaccurate in live use;
see [Current status and next session](PROJECT_STATUS.md) for the exact logic,
limitations, and calibration plan. Raw traces remain available in Signal workspace.
