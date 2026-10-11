#!/usr/bin/env bash
# Start the companion on the Jetson with the Nano on USB and eye control ready.
# Used by nuggies-app.service (docs/JETSON_HANDOFF.md section 7); safe to run by hand.
#
#   - Finds the Nano by its stable /dev/serial/by-id name, so a replug that renames
#     ttyACM0 -> ttyACM1 still works. Override with NANO_PORT=/dev/ttyACM0.
#   - Adds the eye-control flags only when the private waveform profile is present.
#     Without it the app still starts (website, phrases, keyboard), monitor-only, and
#     says so; a missing profile must never take the whole demo down.
#   - Never records: without --record the app reopens the port every 2 s after an unplug.
#
# Environment (all optional; .env is NOT read here, the app loads it itself):
#   NANO_PORT      Serial device for the Arduino Nano R4.
#   EOG_PROFILE    Profile path. Default recordings/guided-runtime-selected/candidate-profile.json
#   EOG_DEMO=0     Drop --eog-demo-tolerance (stricter direction matching).
#   EOG_LOG=1      Also write a private decision log under recordings/ (new file per start).
#   APP_HOST       Default "::" (IPv4 + IPv6 on the LAN; needs APP_TOKEN in .env).
#   APP_PORT       Default 8765.
#   DRY_RUN=1      Print the command instead of running it.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
PROFILE="${EOG_PROFILE:-recordings/guided-runtime-selected/candidate-profile.json}"

port="${NANO_PORT:-}"
if [ -z "$port" ]; then
  for candidate in /dev/serial/by-id/*Arduino* /dev/serial/by-id/*Nano* /dev/serial/by-id/*Renesas*; do
    if [ -e "$candidate" ]; then port="$candidate"; break; fi
  done
fi
if [ -z "$port" ]; then
  port=/dev/ttyACM0
  echo "Nano not found under /dev/serial/by-id; using $port. The app retries every 2 s until it appears." >&2
fi

args=(-m backend.app --host "${APP_HOST:-::}" --port "${APP_PORT:-8765}" --serial-port "$port")
if [ -f "$PROFILE" ]; then
  args+=(--eog-profile "$PROFILE" --eog-pulse-confirmation --eog-return-guard)
  [ "${EOG_DEMO:-1}" = 1 ] && args+=(--eog-demo-tolerance)
  if [ "${EOG_LOG:-0}" = 1 ]; then
    mkdir -p recordings
    args+=(--eog-log "recordings/jetson-eog-$(date -u +%Y%m%dT%H%M%SZ).events.jsonl")
  fi
  echo "Eye control available: profile $PROFILE, Nano on $port" >&2
else
  echo "NO EYE CONTROL: $PROFILE is missing. Copy it from the laptop (see docs/JETSON_HANDOFF.md section 7). Starting monitor-only." >&2
fi

if [ "${DRY_RUN:-0}" = 1 ]; then printf '%q ' "$PYTHON" "${args[@]}"; echo; exit 0; fi
exec "$PYTHON" "${args[@]}"
