#!/bin/bash
# Install the Claude-Vibe-Squad nightly routine via launchd LaunchAgent.
#
# Usage: bash ~/Obsidian-Claude-Vibe-Squad/bin/install-routines.sh
#
# To uninstall: launchctl unload ~/Library/LaunchAgents/com.claudevibesquad.nightly.plist
#               rm ~/Library/LaunchAgents/com.claudevibesquad.nightly.plist

set -euo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
SOURCE_PLIST="${VAULT_ROOT}/launchd/com.claudevibesquad.nightly.plist"
TARGET_PLIST="${HOME}/Library/LaunchAgents/com.claudevibesquad.nightly.plist"

# Ensure source exists
if [[ ! -f "${SOURCE_PLIST}" ]]; then
    echo "ERROR: source plist not found at ${SOURCE_PLIST}"
    exit 1
fi

# Make scripts executable
chmod +x "${VAULT_ROOT}/bin/"*.sh 2>/dev/null || true
chmod +x "${VAULT_ROOT}/scripts/python/"*.py 2>/dev/null || true
chmod +x "${VAULT_ROOT}/scripts/"*.sh 2>/dev/null || true

# Pre-warm the uv ephemeral env cache for vibecoding-check + content-processing.
# Without this, the first run from a sandboxed CLI (Codex's workspace-write,
# launchd's restricted env) hangs on DNS while uv tries to fetch deps.
# Operator can override the cache location with $UV_CACHE_DIR.
echo "Pre-warming uv cache..."
if command -v uv >/dev/null 2>&1; then
    UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" uv run --quiet --no-project \
        --with pyyaml --with httpx --with feedparser --with trafilatura \
        python -c "import yaml, httpx, feedparser, trafilatura" 2>/dev/null \
        && echo "  ✓ pyyaml, httpx, feedparser, trafilatura cached" \
        || echo "  ⚠ uv cache pre-warm failed (network issue?) — first script run will fetch"
fi

# Ensure LaunchAgents dir exists
mkdir -p "${HOME}/Library/LaunchAgents"

# Copy plist with __VAULT_ROOT__ substituted to the absolute resolved vault path
# (so the squad works whether the repo is cloned at the default name or any other)
sed "s|__VAULT_ROOT__|${VAULT_ROOT}|g" "${SOURCE_PLIST}" > "${TARGET_PLIST}"

# Load it
if launchctl list | grep -q "com.claudevibesquad.nightly"; then
    echo "Already loaded. Reloading..."
    launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
fi
launchctl load "${TARGET_PLIST}"

echo "✓ Installed Claude-Vibe-Squad nightly routine"
echo "  Plist: ${TARGET_PLIST}"
echo "  Schedule: daily at 03:00"
echo "  Logs: /tmp/claudevibesquad-nightly-stdout.log, /tmp/claudevibesquad-nightly-stderr.log"
echo "  Per-phase logs: ${VAULT_ROOT}/_state/"
echo ""
echo "To test now: bash ${VAULT_ROOT}/bin/run-nightly.sh"
echo "To uninstall: launchctl unload ${TARGET_PLIST} && rm ${TARGET_PLIST}"
