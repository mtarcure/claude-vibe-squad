#!/usr/bin/env bash
set -euo pipefail
PROFILE_DIR="$HOME/.chrono/chrome-persistent-profile"
mkdir -p "$PROFILE_DIR"
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --user-data-dir="$PROFILE_DIR" \
    --remote-debugging-port=9222 \
    --remote-allow-origins=* \
    --no-first-run \
    --no-default-browser-check \
    --restore-last-session
