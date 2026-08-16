#!/usr/bin/env bash
# Launches a persistent Chrome with CDP on :9222 so agents can reuse the
# operator's authenticated sessions.
#
# TRUST ASSUMPTION, stated because it is not obvious: anything able to reach
# 127.0.0.1:9222 controls this browser completely -- every cookie, every
# logged-in session, authenticated requests as the user. CDP has no
# authentication. That is a deliberate trade for agent access, and it means the
# machine's local process boundary IS the security boundary.
#
# `--remote-allow-origins=*` was removed 2026-08-05. That flag exists
# specifically to relax the WebSocket origin validation Chrome added to stop web
# PAGES connecting to a local debugging port; setting it to `*` removed the
# mitigation wholesale. Local tooling that speaks raw CDP sends no browser
# Origin header and does not need it. If a tool breaks without it, fix the tool's
# Origin rather than reinstating a blanket bypass.
set -euo pipefail
PROFILE_DIR="$HOME/.chrono/chrome-persistent-profile"
mkdir -p "$PROFILE_DIR"
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --user-data-dir="$PROFILE_DIR" \
    --remote-debugging-port=9222 \
    --no-first-run \
    --no-default-browser-check \
    --restore-last-session
