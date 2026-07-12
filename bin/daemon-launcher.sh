#!/usr/bin/env bash
# Sources operator secrets (VIBESQUAD_DAEMON_TOKEN + others) before launching
# the daemon. launchd doesn't inherit shell env, so this wrapper is required.
set -euo pipefail

# Source secrets so VIBESQUAD_DAEMON_TOKEN and other env vars are available
if [[ -f "$HOME/.config/shell/secrets.zsh" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.config/shell/secrets.zsh"
fi

REPO="/Users/user/Obsidian-Claude-Vibe-Squad"
cd "$REPO"

exec "$REPO/.venv/bin/python" -m daemon.main
