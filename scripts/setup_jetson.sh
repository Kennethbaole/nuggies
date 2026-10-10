#!/usr/bin/env bash
# One-shot host setup for the Jetson Orin Nano Super Developer Kit.
#
# Run from the repository root as the user who will run the app (not root):
#
#   bash scripts/setup_jetson.sh
#
# Steps: apt packages, project venv + requirements.txt, dialout group for the
# Nano's USB serial port, MAXN SUPER power mode, Ollama + model, Piper + voice,
# Qwen3-ASR speech-to-text (GPU torch + qwen-asr in its own venv) + model.
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
#   ASR_MODEL      Qwen speech-to-text model  (default: Qwen/Qwen3-ASR-0.6B; 1.7B is more accurate)
#   ASR_VENV       Venv for torch + qwen-asr  (default: .venv-asr, Git-ignored)
#   TORCH_INDEX_URL  CUDA torch wheels        (default by L4T release: R36/JetPack 6 uses
#                    https://pypi.jetson-ai-lab.io/jp6/cu126; R38+/JetPack 7 uses PyTorch's
#                    CUDA 13 aarch64 wheels, https://download.pytorch.org/whl/cu130)
#   SKIP_POWER=1   Leave the power mode alone; the summary reports it as SKIPPED
#
# NVIDIA firmware/OS/JetPack provisioning comes first and is not done here;
# see docs/JETSON_HANDOFF.md. The app reaches Qwen through backend.asr_server
# (ASR_URL); Piper is installed but not wired into the app yet.

set -euo pipefail

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:1.7b}"
PIPER_VOICE="${PIPER_VOICE:-en_US-lessac-medium}"
PIPER_DIR="${PIPER_DIR:-.cache/piper}"
ASR_MODEL="${ASR_MODEL:-Qwen/Qwen3-ASR-0.6B}"
ASR_VENV="${ASR_VENV:-.venv-asr}"
# JetPack 7 (L4T R38+) has CUDA 13, which runs PyTorch's standard aarch64 wheels;
# JetPack 6 (R36) needs NVIDIA's Jetson builds.
L4T_MAJOR="$(sed -n 's/^# R\([0-9]*\).*/\1/p' /etc/nv_tegra_release 2>/dev/null || true)"
if [[ "${L4T_MAJOR:-0}" -ge 38 ]]; then
    TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu130}"
else
    TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://pypi.jetson-ai-lab.io/jp6/cu126}"
fi
SKIP_POWER="${SKIP_POWER:-0}"
VENV=".venv"

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
    alsa-utils ffmpeg sox libsndfile1 \
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

# --- 7. Qwen3-ASR speech-to-text ---------------------------------------------

step "Creating $ASR_VENV for Qwen3-ASR (Jetson torch + qwen-asr)"
# A separate venv: torch and qwen-asr's pinned transformers are large, and the
# app's own venv stays light. PyPI's aarch64 torch has no CUDA, so torch comes
# from a CUDA index first (see TORCH_INDEX_URL), and that index stays available while
# qwen-asr installs so pip cannot swap in a CPU-only build.
[[ -x "$ASR_VENV/bin/python" ]] || python3 -m venv "$ASR_VENV"
"$ASR_VENV/bin/python" -m pip install --upgrade pip
"$ASR_VENV/bin/python" -m pip install torch --index-url "$TORCH_INDEX_URL"
"$ASR_VENV/bin/python" -m pip install --extra-index-url "$TORCH_INDEX_URL" -r requirements-asr.txt
"$ASR_VENV/bin/python" -c "import qwen_asr" || die "qwen_asr does not import from $ASR_VENV"
if "$ASR_VENV/bin/python" -c "import sys, torch; sys.exit(not torch.cuda.is_available())"; then
    record PASS "torch CUDA" "torch $("$ASR_VENV/bin/python" -c 'import torch; print(torch.__version__)')"
else
    die "torch in $ASR_VENV cannot see the GPU; delete $ASR_VENV and re-run with another TORCH_INDEX_URL (JetPack 6: https://pypi.jetson-ai-lab.io/jp6/cu129; JetPack 7: https://download.pytorch.org/whl/cu132)"
fi

step "Downloading $ASR_MODEL"
"$ASR_VENV/bin/python" -c "import sys; from huggingface_hub import snapshot_download; print(snapshot_download(sys.argv[1]))" \
    "$ASR_MODEL" || die "could not download $ASR_MODEL from Hugging Face"

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

# Qwen transcribes the Piper clip above ("Setup complete."), so check the words.
if [[ -s "$piper_wav" ]] && asr_out="$(timeout 600 "$ASR_VENV/bin/python" -m backend.asr_server \
        --model "$ASR_MODEL" --self-test "$piper_wav" 2>"$LOG_DIR/asr.log")" \
        && grep -Eqi "set ?up" <<<"$asr_out"; then
    record PASS "Qwen ASR transcribe" "$(tail -n 1 <<<"$asr_out" | cut -c 1-60)"
else
    record FAIL "Qwen ASR transcribe" "wrong or empty transcript; see $LOG_DIR/asr.log"
fi

# --- Summary -----------------------------------------------------------------

step "Summary"
printf '%s\n' "${RESULTS[@]}"
echo
echo "Ollama model: $OLLAMA_MODEL"
echo "Piper voice:  $PIPER_MODEL_FILE"
echo "Qwen ASR:     $ASR_VENV/bin/python -m backend.asr_server --model $ASR_MODEL"
echo
echo "Not checked by this script: audible speaker output, microphone input,"
echo "Nano USB acquisition, the ASR tunnel to the laptop, and the app using Piper (not wired in yet)."

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
