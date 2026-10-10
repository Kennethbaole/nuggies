#!/usr/bin/env bash
# Deploy new commits on origin/main to this Jetson. Run by nuggies-update.timer
# every 2 minutes (see docs/JETSON_HANDOFF.md); safe to run by hand.
#
# Policy:
#   - Only acts when ~/nuggies has main checked out with no edits to tracked
#     files. On any other branch, or with local edits, it logs and does nothing,
#     so hands-on work on the Jetson is never overwritten.
#   - Runs the test suite on the new commit in a separate worktree first. If it
#     fails, the Jetson stays on the current commit and that commit is not
#     retried; the next push to main gets a fresh try.
#   - On success, fast-forwards and restarts nuggies-app (and nuggies-asr if it
#     is running and backend/asr_server.py changed).
#   - Pause: touch .cache/auto-update.pause (Git-ignored). Remove it to resume.
#   - Offline: a failed fetch is logged and skipped.
#
# Logs: journalctl --user -u nuggies-update
set -euo pipefail

REPO="${NUGGIES_DIR:-$HOME/nuggies}"
cd "$REPO"
PAUSE=.cache/auto-update.pause
FAILED=.cache/auto-update.failed

if [ -e "$PAUSE" ]; then echo "Paused: remove $REPO/$PAUSE to resume"; exit 0; fi
branch=$(git symbolic-ref --short -q HEAD || true)
if [ "$branch" != main ]; then echo "Skipping: on '${branch:-detached HEAD}', not main"; exit 0; fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then echo "Skipping: uncommitted edits to tracked files"; exit 0; fi
if ! git fetch --quiet origin main; then echo "Skipping: fetch failed (offline?)"; exit 0; fi

old=$(git rev-parse HEAD)
new=$(git rev-parse FETCH_HEAD)
[ "$old" = "$new" ] && exit 0
if ! git merge-base --is-ancestor "$old" "$new"; then echo "Skipping: local main has commits not on origin/main"; exit 0; fi
[ "$(cat "$FAILED" 2>/dev/null || true)" = "$new" ] && exit 0

tmp=$(mktemp -d)
trap 'git worktree remove --force "$tmp" >/dev/null 2>&1 || rm -rf "$tmp"' EXIT
git worktree add --quiet --detach "$tmp" "$new"
if ! git diff --quiet "$old" "$new" -- requirements.txt; then
  echo "requirements.txt changed; installing into .venv"
  .venv/bin/pip install --quiet -r "$tmp/requirements.txt"
fi
echo "Testing $(git log -1 --format='%h %s' "$new")"
if ! (cd "$tmp" && "$REPO/.venv/bin/python" -m unittest discover -s tests -q); then
  mkdir -p .cache && echo "$new" > "$FAILED"
  echo "Tests failed; staying on $(git log -1 --format='%h' "$old")"
  exit 1
fi

git merge --quiet --ff-only "$new"
rm -f "$FAILED"
systemctl --user restart nuggies-app
echo "Deployed $(git log -1 --format='%h %s')"
if systemctl --user is-active --quiet nuggies-asr && ! git diff --quiet "$old" "$new" -- backend/asr_server.py; then
  systemctl --user restart nuggies-asr
  echo "Restarted nuggies-asr"
fi
