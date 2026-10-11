#!/usr/bin/env bash
# Give the Jetson memory headroom for Qwen ASR and Ollama at the same time.
#
# Run as the user who runs the app (not root); it asks for sudo once:
#
#   bash scripts/jetson_memory.sh
#
# Steps:
#   1. Swap file (default 8G at /swapfile), on now and at every boot via
#      /etc/fstab. Without swap, loading Ollama's model while Qwen ASR holds the
#      GPU ran the 7.4 GB of shared memory out and the Jetson reset (2026-10-10).
#      Swap moves idle CPU memory (desktop, browser, Python) to disk; GPU
#      allocations cannot be swapped, so this is a safety net, not more VRAM.
#   2. Boot to text mode (multi-user.target) instead of the GNOME desktop, which
#      with a browser open took ~2 GB. The app's user services still start at
#      boot because lingering is enabled; the script checks that too.
# Re-running is safe; finished steps are skipped.
#
# Overrides (environment variables):
#   SWAP_SIZE=8G    Swap file size (fallocate syntax)
#   SWAP_FILE=/swapfile
#   HEADLESS=0      Keep booting to the desktop; the summary reports it as SKIPPED
#
# Undo:
#   sudo systemctl set-default graphical.target    # desktop back at next boot
#   sudo swapoff /swapfile && sudo rm /swapfile     # then delete its /etc/fstab line

set -euo pipefail

SWAP_SIZE="${SWAP_SIZE:-8G}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"
HEADLESS="${HEADLESS:-1}"

RESULTS=()
FAILED=0
REBOOT=0

step() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# record STATUS NAME DETAIL: STATUS is PASS, FAIL, PENDING or SKIPPED.
record() {
    RESULTS+=("$(printf '%-8s %-16s %s' "$1" "$2" "$3")")
    [[ "$1" != "FAIL" ]] || FAILED=1
    printf '%s: %s (%s)\n' "$1" "$2" "$3"
}

[[ "$(id -u)" -ne 0 ]] || die "run as your normal user, not root; the script calls sudo itself"
[[ -f /etc/nv_tegra_release ]] || die "this is not a Jetson (no /etc/nv_tegra_release)"
sudo -v || die "sudo is needed for swap and the boot target"

step "Swap file ($SWAP_SIZE at $SWAP_FILE)"
if swapon --show=NAME --noheadings | grep -qx "$SWAP_FILE"; then
    echo "$SWAP_FILE is already active."
else
    if [[ ! -f "$SWAP_FILE" ]]; then
        need_kb=$(( $(numfmt --from=iec "$SWAP_SIZE") / 1024 ))
        free_kb="$(df --output=avail -k "$(dirname "$SWAP_FILE")" | tail -1)"
        # Keep 4 GB spare so models, recordings and updates still fit.
        (( free_kb > need_kb + 4 * 1024 * 1024 )) \
            || die "not enough disk for $SWAP_SIZE swap plus 4 GB spare ($(( free_kb / 1024 / 1024 )) GB free)"
        sudo fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
        sudo chmod 600 "$SWAP_FILE"
        sudo mkswap "$SWAP_FILE" >/dev/null
    fi
    sudo swapon "$SWAP_FILE"
fi
if ! grep -qE "^[[:space:]]*$SWAP_FILE[[:space:]]+none[[:space:]]+swap" /etc/fstab; then
    sudo cp /etc/fstab /etc/fstab.before-swap
    echo "$SWAP_FILE none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
    echo "Added to /etc/fstab (previous copy: /etc/fstab.before-swap)."
fi
if swapon --show=NAME --noheadings | grep -qx "$SWAP_FILE" \
    && grep -qE "^[[:space:]]*$SWAP_FILE[[:space:]]+none[[:space:]]+swap" /etc/fstab; then
    record PASS "swap" "$(swapon --show=NAME,SIZE --noheadings | awk -v f="$SWAP_FILE" '$1 == f {print $2}') active, on at boot"
else
    record FAIL "swap" "$SWAP_FILE is not active or not in /etc/fstab"
fi

step "Boot target"
if [[ "$HEADLESS" != "1" ]]; then
    record SKIPPED "boot target" "HEADLESS=0; still $(systemctl get-default)"
elif [[ "$(systemctl get-default)" == "multi-user.target" ]]; then
    if [[ "$(systemctl is-active graphical.target)" == "active" ]]; then
        REBOOT=1
        record PENDING "boot target" "text mode set; desktop runs until reboot"
    else
        record PASS "boot target" "text mode (no desktop)"
    fi
else
    sudo systemctl set-default multi-user.target >/dev/null
    if [[ "$(systemctl get-default)" == "multi-user.target" ]]; then
        REBOOT=1
        record PENDING "boot target" "text mode set; desktop runs until reboot"
    else
        record FAIL "boot target" "still $(systemctl get-default)"
    fi
fi

step "App services without a desktop login"
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
    sudo loginctl enable-linger "$USER"
fi
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" == "yes" ]]; then
    record PASS "lingering" "user services start at boot without login"
else
    record FAIL "lingering" "user services would wait for a login"
fi

printf '\n==> Summary\n'
printf '%s\n' "${RESULTS[@]}"
free -h | sed -n '1,3p'
if [[ "$FAILED" -ne 0 ]]; then
    exit 1
fi
if [[ "$REBOOT" -eq 1 ]]; then
    echo "Reboot to drop the desktop: sudo reboot"
    echo "Afterwards the monitor shows a text login; use SSH and http://<jetson>:8765 as before."
fi
