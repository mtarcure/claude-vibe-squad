#!/bin/bash
# System cleanup (light) — runs nightly. Brew/npm/pip caches, /tmp, old runs.
# Heavy cleanup (deep KG, stale instinct purge) runs Sunday in run-weekly.sh.

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
DATE="$(date -u +%Y-%m-%d)"
LOG="${VAULT_ROOT}/_state/cleanup-logs/${DATE}-system.md"

mkdir -p "$(dirname "${LOG}")"

# Track freed space
DISK_BEFORE=$(df -k ~ | awk 'NR==2 {print $4}')

cat > "${LOG}" <<EOF
# System Cleanup — ${DATE}

Run at: $(date -u +%FT%TZ)

## Caches

EOF

# brew cleanup (silent if not installed)
if command -v brew >/dev/null 2>&1; then
    brew_freed=$(brew cleanup -n 2>/dev/null | tail -1 || echo "(none)")
    brew cleanup >/dev/null 2>&1 || true
    echo "- brew cleanup: ${brew_freed}" >> "${LOG}"
fi

# npm cache
if command -v npm >/dev/null 2>&1; then
    npm cache verify >/dev/null 2>&1 || true
    echo "- npm cache verified" >> "${LOG}"
fi

# pip cache
if command -v pip >/dev/null 2>&1; then
    pip cache purge >/dev/null 2>&1 || true
    echo "- pip cache purged" >> "${LOG}"
fi

# /tmp cleanup (files >7 days old)
TMP_FILES_REMOVED=$(find /tmp -type f -atime +7 2>/dev/null | wc -l | tr -d ' ')
find /tmp -type f -atime +7 -delete 2>/dev/null || true
echo "" >> "${LOG}"
echo "## Filesystem" >> "${LOG}"
echo "- /tmp: ${TMP_FILES_REMOVED} files >7d removed" >> "${LOG}"

# Run archival: completed runs older than 30 days → archive/
ARCHIVE_DIR="${VAULT_ROOT}/runs/_archive"
mkdir -p "${ARCHIVE_DIR}"
ARCHIVED=0
if [[ -d "${VAULT_ROOT}/runs" ]]; then
    for run in "${VAULT_ROOT}"/runs/*/; do
        if [[ -d "${run}" ]] && [[ "${run}" != *"_archive"* ]]; then
            # Check if run is >30 days old (mtime)
            if find "${run}" -maxdepth 0 -mtime +30 2>/dev/null | grep -q .; then
                target="${ARCHIVE_DIR}/$(date +%Y-%m)/$(basename "${run}")"
                mkdir -p "$(dirname "${target}")"
                mv "${run}" "${target}"
                ARCHIVED=$((ARCHIVED + 1))
            fi
        fi
    done
fi
echo "- Run folders archived (>30d old): ${ARCHIVED}" >> "${LOG}"

# Disk delta
DISK_AFTER=$(df -k ~ | awk 'NR==2 {print $4}')
FREED_KB=$((DISK_AFTER - DISK_BEFORE))
FREED_MB=$((FREED_KB / 1024))
echo "" >> "${LOG}"
echo "## Summary" >> "${LOG}"
echo "- Approx. freed: ${FREED_MB} MB" >> "${LOG}"

echo "System cleanup complete. Log: ${LOG}"
exit 0
