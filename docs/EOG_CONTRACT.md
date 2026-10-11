# EOG contract v1

`backend.eog_pipeline.EOGPipeline` is the shared transport-free path used by the
application and headless entry point. It wraps filtering, segmentation, optional
independent blink pairing, guided recovery and confirmation. It imports no HTTP,
ring, browser, serial, speech or machine-learning framework. The application adapter
supplies current choices and executes returned selections under its existing lock.

## Inputs and coordinates

`process(horizontal, vertical, timestamp_ms, sample_index=..., communication=...)`
accepts raw 14-bit ADC counts at nominal 250 Hz. Filtered processing is 50 Hz.
`timestamp_ms` remains host receipt time for legacy serial; it is not MCU time.
`sample_index` is the zero-based global acquisition index, including samples while
control is disabled. The adapter supplies it; headless replay starts at zero.
Control events before the first sample use -1. Event onset/peak/end indices use that
same coordinate. Physiological gaze position is not measured.

`set_choices({slot: {id, label, enabled}}, selected)` supplies presentation-independent
choice context. `id` must identify the complete choice and its revision/context;
change it when text, contact, action or page changes. IDs must be JSON serializable.
The application uses its existing screen/contact/slot/action/value/text identity.
A display adapter must not infer selection from a changed highlighted slot.

## Outputs

Each result has `state` and ordered `events`. Both contain `schema_version: 1`.
Every event has a monotonically increasing process-local `event_id`, `type`, and
`sample_index`. Persist a host/session identifier with event IDs across restarts.

| Event type | Meaning / additional fields |
| --- | --- |
| gaze_candidate | Rejected/uncertain waveform; `decision` preserves reason and metrics |
| gaze_accepted | Cardinal accepted; `slot`, `decision` with direction/onset/emission |
| return | Recovery waveform; no new navigation command |
| blink | Single-blink template event; never a selection |
| double_blink | Template or pulse evidence; `decision.source` distinguishes pulse stream |
| selection | One consumed confirmation; `slot`, `choice_id`, `onset_sample`, confirmation=double_blink |
| fault | Input interruption, clipping or timing fault; `reason` |
| reset | Deliberate reset; `cause` |
| pause | Reading pause toggled by a centred double blink with no pending choice; `paused` boolean. While paused no `gaze_accepted` or `selection` is emitted |

Slots are fixed: **up=0, right=2, down=4, left=6**. No diagonal selections.
`decision` can include distances, energy fractions and pulse timing in milliseconds;
these are diagnostic values, not calibrated probabilities. Consumers execute only
`selection`, never `blink`, `double_blink`, or `gaze_accepted` as a confirmation.

State includes phase/reason, filtered horizontal/vertical ADC counts, pending,
armed, armed_sample, expires_sample, confirmation prompt, selected_slot, nominal
sample rates, profile digest and settings. Only explicit accepted gaze creates a
pending choice. It arms after return/settling, expires after 2500 raw samples,
and is consumed before emitting selection. Uncertain pulse matching permits retry
without extending expiry. Ordinary retry and later return events preserve the
choice but suspend arming until recovery settles. Faults, recenter, early blinks
and changed choices clear it. Electrical settling is not proof of physically looking center.

## Application and adapters

`/api/state` adds `eog_schema_version` and the last 64 `eog_events`. Existing fields
remain: `eog_engine`, `eog_communication`, `eog_choice_pending`,
`eog_confirmation_ready`, `eog_confirmation`, `gaze_hover`, `wheel_test`,
`connected`, `input_error`. Repeated polls can contain the same events: deduplicate
by application `session_id` plus event ID. The adapter owns RingState and speech;
the pipeline never speaks or sends a hardware command.

```sh
python -m scripts.eog_headless --csv recordings/SESSION.csv \
  --profile recordings/PROFILE.json --pulse-confirmation --communication
python -m scripts.eog_headless --serial-port PORT \
  --profile recordings/PROFILE.json --pulse-confirmation --communication
```

Stdout is JSON Lines: `kind=event` for contract events, `kind=state` for changed
status. Errors go to stderr plus a fault event. Default headless choices are slot
identities for diagnostics; an integrating backend must supply its actual choice
IDs/text through the Python API. This CLI does not automatically forward samples
or selections to an existing app. Only one process may own Nano USB.

The same Python object can run on laptop or Jetson. An ESP32 adapter should render
canonical app state and deduplicate selections; it must not run a second independent
wheel. `hud_bridge.py` is unchanged. Jetson deployment, serial routing, physical
ESP32 protocol/optics, audio routing and reconnect behavior across hosts remain
untested. Topology questions belong in the handoff before hardware integration.

The optional `excursion_guard` setting (`--eog-return-guard` in the application,
`--return-guard` in the headless CLI) adds a navigation veto. A `return` decision
with reason `remembered_excursion` consumes an opposite pulse reserved by an
earlier excursion, including an unaccepted one. It is never `gaze_accepted` and
must not change the adapter's selected slot. Quiet alone does not clear ownership.
