#!/usr/bin/env bash
# One-shot host setup for the Jetson Orin Nano Super Developer Kit.
#
# Run from the repository root as the user who will run the app (not root):
#
#   bash scripts/setup_jetson.sh
#
# Steps: apt packages, project venv + requirements.txt, dialout group for the
# Nano's USB serial port, MAXN SUPER power mode, Ollama + model, Piper + voice.
# Re-running is safe; finished steps are skipped or repeated harmlessly.
#
# Overrides (environment variables):
#   OLLAMA_MODEL   Ollama model to pull       (default: llama3.2:3b)
#   PIPER_VOICE    Piper voice to download    (default: en_US-lessac-medium)
#   PIPER_DIR      Where Piper voices go      (default: .cache/piper, Git-ignored)
#   SKIP_POWER=1   Leave the current nvpmodel power mode alone
#
# NVIDIA firmware/OS/JetPack provisioning comes first and is not done here;
# see docs/JETSON_HANDOFF.md. The app does not call Ollama or Piper yet; this
# only installs them so they can be integrated and tested on the device.

set -euo pipefail

OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:3b}"
PIPER_VOICE="${PIPER_VOICE:-en_US-lessac-medium}"
PIPER_DIR="${PIPER_DIR:-.cache/piper}"
VENV=".venv"
REBOOT_NEEDED=0
RELOGIN_NEEDED=0

step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- Preflight ---------------------------------------------------------------

[[ -f requirements.txt && -d backend ]] || die "run from the repository root"
[[ "$(id -u)" -ne 0 ]] || die "run as your normal user; the script uses sudo where needed"
[[ "$(uname -m)" == "aarch64" ]] || die "expected an aarch64 Jetson, found $(uname -m)"
if [[ -f /etc/nv_tegra_release ]]; then
    echo "L4T: $(head -n 1 /etc/nv_tegra_release)"
else
    warn "/etc/nv_tegra_release not found; this may not be a JetPack install"
fi
sudo -v

# --- 1. System packages ------------------------------------------------------

step "Installing system packages"
sudo apt-get update
sudo apt-get install -y \
    git curl ca-certificates \
    python3 python3-venv python3-pip \
    alsa-utils

python3 - <<'EOF' || die "Python 3.10+ is required (see docs/JETSON_HANDOFF.md)"
import sys
print("Python", sys.version.split()[0])
sys.exit(sys.version_info < (3, 10))
EOF

# --- 2. Project virtualenv + requirements ------------------------------------

step "Creating $VENV and installing requirements.txt"
[[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r requirements.txt

# --- 3. Serial port access ---------------------------------------------------

step "Granting $USER access to USB serial devices (dialout)"
if id -nG "$USER" | tr ' ' '\n' | grep -qx dialout; then
    echo "$USER is already in dialout"
else
    sudo usermod -aG dialout "$USER"
    RELOGIN_NEEDED=1
    echo "Added $USER to dialout; takes effect after logging out and back in"
fi

# --- 4. MAXN SUPER power mode -----------------------------------------------

step "Setting MAXN SUPER power mode"
if [[ "${SKIP_POWER:-0}" == "1" ]]; then
    echo "Skipped (SKIP_POWER=1)"
elif ! command -v nvpmodel >/dev/null; then
    warn "nvpmodel not found; skipping power mode"
else
    # Mode IDs differ between modules/JetPack releases, so look up the ID by name.
    maxn_id="$(sed -nE 's/.*POWER_MODEL[[:space:]]+ID=([0-9]+)[[:space:]]+NAME=MAXN_SUPER.*/\1/p' \
        /etc/nvpmodel.conf 2>/dev/null | head -n 1)"
    if [[ -z "$maxn_id" ]]; then
        warn "no MAXN_SUPER mode in /etc/nvpmodel.conf; JetPack 6.2+ is required for Super modes"
        sudo nvpmodel -q || true
    elif sudo nvpmodel -q 2>/dev/null | grep -q 'MAXN_SUPER'; then
        echo "Already in MAXN_SUPER (mode $maxn_id)"
    else
        # nvpmodel may ask to reboot; answer "no" here and report it at the end.
        echo no | sudo nvpmodel -m "$maxn_id" || true
        if sudo nvpmodel -q 2>/dev/null | grep -q 'MAXN_SUPER'; then
            echo "Now in MAXN_SUPER (mode $maxn_id)"
        else
            REBOOT_NEEDED=1
            echo "MAXN_SUPER (mode $maxn_id) applies after reboot"
        fi
    fi
fi

# --- 5. Ollama + model -------------------------------------------------------

step "Installing Ollama"
if command -v ollama >/dev/null; then
    echo "Ollama already installed: $(ollama --version 2>/dev/null | tail -n 1)"
else
    # The official installer detects JetPack and installs the matching GPU build.
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "Waiting for the Ollama server"
if ! curl -fsS --retry 15 --retry-delay 2 --retry-connrefused \
        http://127.0.0.1:11434/api/version >/dev/null; then
    sudo systemctl start ollama 2>/dev/null || true
    curl -fsS --retry 15 --retry-delay 2 --retry-connrefused \
        http://127.0.0.1:11434/api/version >/dev/null \
        || die "Ollama server is not responding on 127.0.0.1:11434"
fi

step "Pulling Ollama model $OLLAMA_MODEL"
ollama pull "$OLLAMA_MODEL"

# --- 6. Piper + voice --------------------------------------------------------

step "Installing Piper into $VENV"
"$VENV/bin/python" -m pip install piper-tts

step "Downloading Piper voice $PIPER_VOICE into $PIPER_DIR"
mkdir -p "$PIPER_DIR"
if [[ -f "$PIPER_DIR/$PIPER_VOICE.onnx" && -f "$PIPER_DIR/$PIPER_VOICE.onnx.json" ]]; then
    echo "Voice already present"
else
    "$VENV/bin/python" -m piper.download_voices "$PIPER_VOICE" --download-dir "$PIPER_DIR"
fi

# --- 7. Smoke checks ---------------------------------------------------------

step "Smoke checks"
"$VENV/bin/python" -m scripts.doctor || warn "doctor reported a problem"

tmp_wav="$(mktemp --suffix=.wav)"
if echo "Setup complete." | "$VENV/bin/python" -m piper \
        -m "$PIPER_DIR/$PIPER_VOICE.onnx" -f "$tmp_wav" >/dev/null 2>&1 \
        && [[ -s "$tmp_wav" ]]; then
    echo "Piper synthesized a test clip; play it with: aplay $tmp_wav"
else
    warn "Piper did not produce audio"
fi

if ollama run "$OLLAMA_MODEL" "Reply with the single word: ready" >/dev/null 2>&1; then
    echo "Ollama model $OLLAMA_MODEL answered"
else
    warn "Ollama model $OLLAMA_MODEL did not answer"
fi

# --- Summary -----------------------------------------------------------------

step "Done"
sudo nvpmodel -q 2>/dev/null || true
echo "Ollama model: $OLLAMA_MODEL"
echo "Piper voice:  $PIPER_DIR/$PIPER_VOICE.onnx"
[[ "$RELOGIN_NEEDED" -eq 0 ]] || echo "* Log out and back in so the dialout group applies."
[[ "$REBOOT_NEEDED" -eq 0 ]] || echo "* Reboot to finish switching to MAXN SUPER."
echo "Next: follow docs/JETSON_HANDOFF.md section 3 (verify the host-only app)."
