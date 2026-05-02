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
