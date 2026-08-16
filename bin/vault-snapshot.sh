#!/usr/bin/env bash
# Snapshot the private memory vault to a verified, timestamped archive.
#
# Design spec §2.5 calls the vault "the only copy of squad memory" and puts it
# out of scope for every repo operation. On 2026-08-09 that copy had no
# protection at all: no git, no Time Machine destination, no sync container, and
# an empty backups/ directory INSIDE the vault with nothing writing to it. A
# backup stored inside the thing it protects dies with it, which is why the
# default destination here is a sibling of the vault, never a child.
#
# Non-destructive by construction: it only ever reads the vault and writes one
# new archive. It never deletes a previous snapshot -- pruning is a separate
# operator decision, because "the cleanup deleted the backups" is the failure
# this exists to prevent.
#
# Usage:
#   bin/vault-snapshot.sh                 # snapshot to the default destination
#   bin/vault-snapshot.sh --dest DIR      # snapshot elsewhere
#   bin/vault-snapshot.sh --verify FILE   # re-verify an existing archive
set -uo pipefail

VAULT="${CHRONO_VAULT_ROOT:-$HOME/Obsidian-Chrono}"
DEST="${VAULT_SNAPSHOT_DEST:-$HOME/vault-snapshots}"
MODE="snapshot"
VERIFY_TARGET=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dest) DEST="$2"; shift 2 ;;
        --verify) MODE="verify"; VERIFY_TARGET="$2"; shift 2 ;;
        --help|-h) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

note_count() { find "$1/notes" -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' '; }

verify_archive() {
    local archive="$1" expected="$2"
    [[ -f "$archive" ]] || { echo "ERROR: archive not found: $archive" >&2; return 1; }
    # Read the archive back rather than trusting the writer: a snapshot nobody can
    # restore is not a backup.
    local actual
    actual="$(tar -tzf "$archive" 2>/dev/null | grep -cE '^[^/]*/notes/.*\.md$')"
    echo "  archive notes: ${actual}"
    if [[ -n "$expected" ]]; then
        echo "  source notes : ${expected}"
        if [[ "$actual" != "$expected" ]]; then
            echo "ERROR: note count mismatch — archive is NOT a faithful copy" >&2
            return 1
        fi
    fi
    if ! tar -tzf "$archive" >/dev/null 2>&1; then
        echo "ERROR: archive does not list cleanly; treat it as corrupt" >&2
        return 1
    fi
    return 0
}

if [[ "$MODE" == "verify" ]]; then
    echo "Verifying ${VERIFY_TARGET}"
    verify_archive "$VERIFY_TARGET" "" || exit 1
    echo "OK: archive lists cleanly."
    exit 0
fi

[[ -d "$VAULT" ]] || { echo "ERROR: vault not found: $VAULT" >&2; exit 1; }
[[ -f "$VAULT/.chrono-vault" ]] || {
    echo "ERROR: $VAULT has no .chrono-vault marker; refusing to snapshot the wrong directory" >&2
    exit 1
}

# The destination must not live inside the vault. A backup that shares the
# vault's fate is not a backup, and the empty in-vault backups/ directory is
# exactly that mistake already made once.
case "$(cd "$DEST" 2>/dev/null && pwd -P || echo "$DEST")" in
    "$(cd "$VAULT" && pwd -P)"|"$(cd "$VAULT" && pwd -P)"/*)
        echo "ERROR: destination is inside the vault; a backup stored inside what it protects dies with it" >&2
        exit 1 ;;
esac

mkdir -p "$DEST" || { echo "ERROR: cannot create $DEST" >&2; exit 1; }

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
ARCHIVE="${DEST}/chrono-vault-${STAMP}.tar.gz"
SOURCE_NOTES="$(note_count "$VAULT")"

echo "Vault    : ${VAULT}"
echo "Notes    : ${SOURCE_NOTES}"
echo "Archive  : ${ARCHIVE}"

# -C the parent so the archive contains one top-level directory rather than
# absolute paths, which makes restore a plain tar -xzf anywhere.
if ! tar -czf "$ARCHIVE" -C "$(dirname "$VAULT")" "$(basename "$VAULT")" 2>/dev/null; then
    echo "ERROR: archive creation failed" >&2
    rm -f "$ARCHIVE"
    exit 1
fi

echo "Size     : $(du -h "$ARCHIVE" | cut -f1)"
echo "Verifying (reading the archive back):"
if ! verify_archive "$ARCHIVE" "$SOURCE_NOTES"; then
    echo "ERROR: verification failed; the archive is retained at ${ARCHIVE} for inspection" >&2
    exit 1
fi

echo "OK: ${SOURCE_NOTES} notes captured and verified."
cat <<RESTORE

Restore procedure (rehearsed 2026-08-09, both steps are required):

  1. tar -xzf ${ARCHIVE} -C <target-parent>
  2. CHRONO_VAULT_ROOT=<target-parent>/$(basename "$VAULT") \\
       .venv/bin/python -c "import sys;sys.path.insert(0,'plugins/chrono-vault');\\
       import index;print(index.rebuild_index())"

  Step 2 is NOT optional when restoring to a different path. The FTS index stores
  ABSOLUTE note paths, so a relocated vault fails every recall with
  "index contains a note path outside the private vault" until it is rebuilt.
  Rehearsed: restore alone -> recall broken; restore + rebuild -> 1839 indexed,
  0 quarantined, recall working. Restoring in place needs no rebuild.
RESTORE
echo
echo "Existing snapshots (none are ever auto-deleted):"
ls -1t "$DEST"/chrono-vault-*.tar.gz 2>/dev/null | head -5 | sed 's/^/  /'
