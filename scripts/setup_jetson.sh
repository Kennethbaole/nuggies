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
# Failure policy:
#   - Unsupported hardware (not a Jetson, no MAXN SUPER mode) stops the script
#     before anything is installed.
#   - Every install/download/build is checked for its expected files right
#     away; a missing or empty artifact stops the script.
#   - Smoke checks then run each tool for real. All of them run, the summary
#     lists PASS / FAIL / PENDING per item, and any FAIL exits with status 1.
#
# Overrides (environment variables):
#   OLLAMA_MODEL   Ollama model to pull       (default: qwen3:1.7b)
#   PIPER_VOICE    Piper voice to download    (default: en_US-lessac-medium)
#   PIPER_DIR      Where Piper voices go      (default: .cache/piper, Git-ignored)
#   WHISPER_MODEL  whisper.cpp model          (default: small.en; base.en is faster)
#   WHISPER_REF    whisper.cpp release tag    (default: v1.9.5)
#   WHISPER_DIR    whisper.cpp checkout       (default: .cache/whisper.cpp, Git-ignored)
#   SKIP_POWER=1   Leave the power mode alone; the summary reports it as SKIPPED
#
# NVIDIA firmware/OS/JetPack provisioning comes first and is not done here;
# see docs/JETSON_HANDOFF.md. The app calls Ollama for reply suggestions; Piper
# and whisper.cpp are installed so they can be integrated and tested on the device.

set -euo pipefail

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:1.7b}"
PIPER_VOICE="${PIPER_VOICE:-en_US-lessac-medium}"
PIPER_DIR="${PIPER_DIR:-.cache/piper}"
WHISPER_MODEL="${WHISPER_MODEL:-small.en}"
WHISPER_REF="${WHISPER_REF:-v1.9.5}"
WHISPER_DIR="${WHISPER_DIR:-.cache/whisper.cpp}"
SKIP_POWER="${SKIP_POWER:-0}"
VENV=".venv"

WHISPER_BIN="$WHISPER_DIR/build/bin"
WHISPER_MODEL_FILE="$WHISPER_DIR/models/ggml-$WHISPER_MODEL.bin"
WHISPER_SAMPLE="$WHISPER_DIR/samples/jfk.wav"
PIPER_MODEL_FILE="$PIPER_DIR/$PIPER_VOICE.onnx"
LOG_DIR="$(mktemp -d)"

RESULTS=()
FAILED=0

step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# record STATUS NAME DETAIL: STATUS is PASS, FAIL, PENDING, WARN or SKIPPED.
record() {
    RESULTS+=("$(printf '%-8s %-22s %s' "$1" "$2" "$3")")
    [[ "$1" != "FAIL" ]] || FAILED=1
    printf '%s: %s (%s)\n' "$1" "$2" "$3"
}

# require_file PATH MIN_BYTES WHAT: stop unless PATH exists and is big enough.
require_file() {
    local size
    [[ -f "$1" ]] || die "$3 is missing: $1"
    size="$(stat -c %s "$1")"
    [[ "$size" -ge "$2" ]] || die "$3 looks incomplete ($size bytes): $1"
}

in_maxn_super() { sudo nvpmodel -q 2>/dev/null | grep -q 'MAXN_SUPER'; }

# --- Preflight: stop on unsupported hardware before installing anything -------

[[ -f requirements.txt && -d backend ]] || die "run from the repository root"
[[ "$(id -u)" -ne 0 ]] || die "run as your normal user; the script uses sudo where needed"
[[ "$(uname -m)" == "aarch64" ]] || die "expected an aarch64 Jetson, found $(uname -m)"
[[ -f /etc/nv_tegra_release ]] || die "/etc/nv_tegra_release not found; flash JetPack first (docs/JETSON_HANDOFF.md)"
echo "L4T: $(head -n 1 /etc/nv_tegra_release)"
sudo -v

MAXN_ID=""
if [[ "$SKIP_POWER" != "1" ]]; then
    command -v nvpmodel >/dev/null \
        || die "nvpmodel not found; this is not a supported JetPack install (SKIP_POWER=1 to bypass)"
    # Mode IDs differ between modules/JetPack releases, so look up the ID by name.
    MAXN_ID="$(sed -nE 's/.*POWER_MODEL[[:space:]]+ID=([0-9]+)[[:space:]]+NAME=MAXN_SUPER.*/\1/p' \
        /etc/nvpmodel.conf 2>/dev/null | head -n 1)"
    [[ -n "$MAXN_ID" ]] \
        || die "no MAXN_SUPER mode in /etc/nvpmodel.conf; needs an Orin Nano Super on JetPack 6.2+ (SKIP_POWER=1 to bypass)"
fi

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
    record PASS "dialout group" "$USER is a member"
else
    sudo usermod -aG dialout "$USER"
    getent group dialout | grep -qw "$USER" || die "failed to add $USER to dialout"
    record PENDING "dialout group" "added; log out and back in to apply"
fi

# --- 4. MAXN SUPER power mode -----------------------------------------------

step "Setting MAXN SUPER power mode"
if [[ "$SKIP_POWER" == "1" ]]; then
    record SKIPPED "power mode" "SKIP_POWER=1; current: $(sudo nvpmodel -q 2>/dev/null | head -n 1 || echo unknown)"
elif in_maxn_super; then
    record PASS "power mode" "MAXN_SUPER (mode $MAXN_ID) active"
else
    # nvpmodel may ask to reboot; answer "no" so the script can finish, then
    # check the actual state instead of trusting the exit code.
    echo no | sudo nvpmodel -m "$MAXN_ID" || true
    if in_maxn_super; then
        record PASS "power mode" "MAXN_SUPER (mode $MAXN_ID) active"
    else
        record PENDING "power mode" "MAXN_SUPER requested, not active; reboot and re-run to confirm"
    fi
fi

# --- 5. Ollama + model -------------------------------------------------------

step "Installing Ollama"
if ! command -v ollama >/dev/null; then
    # The official installer detects JetPack and installs the matching GPU build.
    curl -fsSL https://ollama.com/install.sh | sh
fi
command -v ollama >/dev/null || die "ollama is not on PATH after install"
echo "Ollama $(ollama --version 2>/dev/null | tail -n 1)"

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
ollama show "$OLLAMA_MODEL" >/dev/null 2>&1 || die "Ollama does not list $OLLAMA_MODEL after pulling"

# --- 6. Piper + voice --------------------------------------------------------

step "Installing Piper into $VENV"
"$VENV/bin/python" -m pip install piper-tts
"$VENV/bin/python" -c "import piper" || die "piper does not import from $VENV"

step "Downloading Piper voice $PIPER_VOICE into $PIPER_DIR"
mkdir -p "$PIPER_DIR"
if [[ -s "$PIPER_MODEL_FILE" && -s "$PIPER_MODEL_FILE.json" ]]; then
    echo "Voice already present"
else
    "$VENV/bin/python" -m piper.download_voices "$PIPER_VOICE" --download-dir "$PIPER_DIR"
fi
require_file "$PIPER_MODEL_FILE" 1000000 "Piper voice model"
require_file "$PIPER_MODEL_FILE.json" 100 "Piper voice config"

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
    record PASS "whisper.cpp GPU build" "CUDA $(nvcc --version | sed -nE 's/.*release ([0-9.]+).*/\1/p')"
else
    record WARN "whisper.cpp GPU build" "nvcc missing; CPU-only build (sudo apt-get install nvidia-jetpack)"
fi

if [[ -x "$WHISPER_BIN/whisper-cli" && -x "$WHISPER_BIN/whisper-server" ]]; then
    echo "whisper.cpp already built (delete $WHISPER_DIR/build to rebuild)"
else
    echo "This can take 15+ minutes with CUDA."
    cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" -DCMAKE_BUILD_TYPE=Release "${cuda_flags[@]}"
    # Limit parallel jobs: CUDA compiles can exhaust the Orin Nano's shared 8 GB.
    cmake --build "$WHISPER_DIR/build" --config Release -j 4 --target whisper-cli whisper-server
fi
for bin in whisper-cli whisper-server; do
    [[ -x "$WHISPER_BIN/$bin" ]] || die "whisper.cpp build did not produce $WHISPER_BIN/$bin"
done

step "Downloading whisper.cpp model $WHISPER_MODEL"
sh "$WHISPER_DIR/models/download-ggml-model.sh" "$WHISPER_MODEL" "$WHISPER_DIR/models"
require_file "$WHISPER_MODEL_FILE" 10000000 "whisper.cpp model"
require_file "$WHISPER_SAMPLE" 10000 "whisper.cpp sample audio"

# --- 8. Smoke checks: run each tool for real ---------------------------------

step "Smoke checks (logs in $LOG_DIR)"

if "$VENV/bin/python" -m scripts.doctor >"$LOG_DIR/doctor.log" 2>&1; then
    record PASS "doctor" "dependencies and serial ports listed"
else
    record FAIL "doctor" "see $LOG_DIR/doctor.log"
fi

piper_wav="$LOG_DIR/piper.wav"
if echo "Setup complete." | "$VENV/bin/python" -m piper -m "$PIPER_MODEL_FILE" -f "$piper_wav" \
        >"$LOG_DIR/piper.log" 2>&1 \
        && [[ -s "$piper_wav" && "$(head -c 4 "$piper_wav")" == "RIFF" ]]; then
    record PASS "Piper synthesis" "WAV written; listen with: aplay $piper_wav"
else
    record FAIL "Piper synthesis" "no valid WAV; see $LOG_DIR/piper.log"
fi

if reply="$(timeout 300 ollama run "$OLLAMA_MODEL" "Reply with the single word: ready" 2>"$LOG_DIR/ollama.log")" \
        && [[ -n "${reply//[[:space:]]/}" ]]; then
    record PASS "Ollama generation" "$OLLAMA_MODEL replied: $(echo "$reply" | tr -s '[:space:]' ' ' | cut -c 1-40)"
else
    record FAIL "Ollama generation" "$OLLAMA_MODEL gave no reply within 300 s; see $LOG_DIR/ollama.log"
fi

# The sample is JFK's "ask not what your country can do for you", so check the words.
if transcript="$("$WHISPER_BIN/whisper-cli" -m "$WHISPER_MODEL_FILE" -f "$WHISPER_SAMPLE" -nt \
        2>"$LOG_DIR/whisper.log")" && grep -qi "country" <<<"$transcript"; then
    record PASS "whisper.cpp transcribe" "sample transcribed correctly"
else
    record FAIL "whisper.cpp transcribe" "wrong or empty transcript; see $LOG_DIR/whisper.log"
fi

# --- Summary -----------------------------------------------------------------

step "Summary"
printf '%s\n' "${RESULTS[@]}"
echo
echo "Ollama model: $OLLAMA_MODEL"
echo "Piper voice:  $PIPER_MODEL_FILE"
echo "Whisper:      $WHISPER_BIN/whisper-server -m $WHISPER_MODEL_FILE"
echo
echo "Not checked by this script: audible speaker output, microphone input,"
echo "Nano USB acquisition, and the app using Ollama/Piper/whisper.cpp (not wired in yet)."

if [[ "$FAILED" -ne 0 ]]; then
    echo
    die "setup incomplete: fix the FAIL items above and re-run"
fi
if printf '%s\n' "${RESULTS[@]}" | grep -q '^PENDING'; then
    echo
    echo "Installed and checked, with PENDING items: reboot (or log out and back in), then re-run to confirm."
else
    echo
    echo "Setup complete. Next: docs/JETSON_HANDOFF.md section 3 (verify the host-only app)."
fi
