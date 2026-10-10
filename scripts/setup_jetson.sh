#!/usr/bin/env bash
# One-shot host setup for the Jetson Orin Nano Super Developer Kit.
#
# Run from the repository root as the user who will run the app (not root):
#
#   bash scripts/setup_jetson.sh
#
# Steps: apt packages, project venv + requirements.txt, dialout group for the
# Nano's USB serial port, MAXN SUPER power mode, Ollama + model, Piper + voice,
# whisper.cpp (built for the GPU) + speech-to-text model.
# Re-running is safe; finished steps are skipped or repeated harmlessly.
#
# Overrides (environment variables):
#   OLLAMA_MODEL   Ollama model to pull       (default: llama3.2:3b)
#   PIPER_VOICE    Piper voice to download    (default: en_US-lessac-medium)
#   PIPER_DIR      Where Piper voices go      (default: .cache/piper, Git-ignored)
#   WHISPER_MODEL  whisper.cpp model          (default: small.en; base.en is faster)
#   WHISPER_REF    whisper.cpp release tag    (default: v1.9.5)
#   WHISPER_DIR    whisper.cpp checkout       (default: .cache/whisper.cpp, Git-ignored)
#   SKIP_POWER=1   Leave the current nvpmodel power mode alone
#
# NVIDIA firmware/OS/JetPack provisioning comes first and is not done here;
# see docs/JETSON_HANDOFF.md. The app does not call Ollama, Piper or whisper.cpp
# yet; this only installs them so they can be integrated and tested on the device.

set -euo pipefail

OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:3b}"
PIPER_VOICE="${PIPER_VOICE:-en_US-lessac-medium}"
PIPER_DIR="${PIPER_DIR:-.cache/piper}"
WHISPER_MODEL="${WHISPER_MODEL:-small.en}"
WHISPER_REF="${WHISPER_REF:-v1.9.5}"
WHISPER_DIR="${WHISPER_DIR:-.cache/whisper.cpp}"
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
    alsa-utils ffmpeg \
    build-essential cmake

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

# --- 7. whisper.cpp + model --------------------------------------------------

step "Building whisper.cpp $WHISPER_REF in $WHISPER_DIR"
if [[ ! -d "$WHISPER_DIR/.git" ]]; then
    git clone --depth 1 --branch "$WHISPER_REF" https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
fi

cuda_flags=()
if [[ -x /usr/local/cuda/bin/nvcc ]]; then
    export PATH="/usr/local/cuda/bin:$PATH"
    # 87 = Orin's GPU architecture.
    cuda_flags=(-DGGML_CUDA=1 -DCMAKE_CUDA_ARCHITECTURES=87)
    echo "Building with CUDA ($(nvcc --version | tail -n 1))"
else
    warn "CUDA compiler not found; building CPU-only (slower). Install with: sudo apt-get install nvidia-jetpack"
fi

if [[ -x "$WHISPER_DIR/build/bin/whisper-cli" && -x "$WHISPER_DIR/build/bin/whisper-server" ]]; then
    echo "whisper.cpp already built (delete $WHISPER_DIR/build to rebuild)"
else
    echo "This can take 15+ minutes with CUDA."
    cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" -DCMAKE_BUILD_TYPE=Release "${cuda_flags[@]}"
    # Limit parallel jobs: CUDA compiles can exhaust the Orin Nano's shared 8 GB.
    cmake --build "$WHISPER_DIR/build" --config Release -j 4 --target whisper-cli whisper-server
fi

step "Downloading whisper.cpp model $WHISPER_MODEL"
sh "$WHISPER_DIR/models/download-ggml-model.sh" "$WHISPER_MODEL" "$WHISPER_DIR/models"

# --- 8. Smoke checks ---------------------------------------------------------

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

if transcript="$("$WHISPER_DIR/build/bin/whisper-cli" -m "$WHISPER_DIR/models/ggml-$WHISPER_MODEL.bin" \
        -f "$WHISPER_DIR/samples/jfk.wav" -nt 2>/dev/null)" && [[ -n "${transcript//[[:space:]]/}" ]]; then
    echo "whisper.cpp transcribed the sample:$(echo "$transcript" | tr -s '[:space:]' ' ')"
else
    warn "whisper.cpp did not transcribe the sample"
fi

# --- Summary -----------------------------------------------------------------

step "Done"
sudo nvpmodel -q 2>/dev/null || true
echo "Ollama model: $OLLAMA_MODEL"
echo "Piper voice:  $PIPER_DIR/$PIPER_VOICE.onnx"
echo "Whisper:      $WHISPER_DIR/build/bin/whisper-server -m $WHISPER_DIR/models/ggml-$WHISPER_MODEL.bin"
[[ "$RELOGIN_NEEDED" -eq 0 ]] || echo "* Log out and back in so the dialout group applies."
[[ "$REBOOT_NEEDED" -eq 0 ]] || echo "* Reboot to finish switching to MAXN SUPER."
echo "Next: follow docs/JETSON_HANDOFF.md section 3 (verify the host-only app)."
