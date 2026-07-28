#!/usr/bin/env bash
# Sources operator secrets (VIBESQUAD_DAEMON_TOKEN + others) before launching
# the daemon. launchd doesn't inherit shell env, so this wrapper is required.
set -euo pipefail

# Source secrets so VIBESQUAD_DAEMON_TOKEN and other env vars are available
if [[ -f "$HOME/.config/shell/secrets.zsh" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.config/shell/secrets.zsh"
fi

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
REPO="${VAULT_ROOT}"
cd "$REPO"

exec "$REPO/.venv/bin/python" -m daemon.main
