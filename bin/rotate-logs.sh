#!/usr/bin/env bash
# rotate-logs.sh — put a ceiling on the two append-only log sets that have no
# other bound: the daemon's launchd stdout/stderr, and the tmux pane captures
# under _state/tmux-logs/.
#
# Why this exists: measured 2026-08-17, /tmp/vibesquad-daemon-std{out,err}.log
# held 34 MB and 31 MB and _state/tmux-logs/chrono.log held 81 MB, all of it
# written by processes that never close the file and never wrap around. The
# failure mode is not hypothetical here -- _state/monitor/monitor-err.log
# already records "No space left on device", dated 2026-07-31, and
# _state/tmux-logs once reached 12 GB with a single 11.6 GB gemini.log.
#
# Size-based, not age-based, and for the same reason: pane capture volume tracks
# how much a TUI repaints, not how long it ran. A nightly age policy would still
# let one chatty pane blow the budget between two runs.
#
# Usage:
#   bin/rotate-logs.sh            # report only: what WOULD rotate (default)
#   bin/rotate-logs.sh --apply    # rotate and prune (destructive)
#
# Same flag convention as bin/prune-board-worktrees.sh: nothing is destroyed
# without --apply, and run-nightly.sh passes it explicitly.
#
# ---------------------------------------------------------------------------
# THE ONE DETAIL THAT MUST NOT BE GOT WRONG: copy-then-truncate, never move.
#
# Every file here is held open for writing by a process that outlives this
# script -- `tmux pipe-pane -o "cat >> ..."` for the pane captures, launchd's
# StandardOutPath/StandardErrorPath for the daemon. Renaming or unlinking such a
# file does NOT free its blocks and does NOT redirect the writer: the writer
# keeps appending to the same inode under its new name, the "fresh" log stays
# empty forever, and disk usage is unchanged until the process exits. So the
# archive is a COPY and the live file is truncated IN PLACE, which keeps the
# inode, frees the blocks immediately, and -- because both writers opened with
# O_APPEND -- puts the next write at offset 0 rather than leaving a sparse hole
# the size of the old file.
#
# The cost of copytruncate, stated rather than hidden: bytes appended between
# reading the file and truncating it are lost. That window is one gzip of one
# file, it is the same trade logrotate's `copytruncate` makes, and it is the
# right trade for pane scrollback and daemon chatter.
# ---------------------------------------------------------------------------

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

MODE="report"
case "${1:-}" in
    --apply)                 MODE="apply" ;;
    ""|--dry-run|--report)   MODE="report" ;;
    *) echo "rotate-logs.sh: unknown flag: $1" >&2; exit 2 ;;
esac

# Caps are deliberately well above the largest bounded READ any consumer makes.
# bin/doctor.sh's retry-storm scan tails at most DOCTOR_LOG_SCAN_BYTES (8 MB) of
# each tmux log, so a 16 MB cap always leaves that scan its full window; a cap
# below it would silently shrink a health check into a smaller one.
DAEMON_LOG_DIR="${VIBESQUAD_DAEMON_LOG_DIR:-/tmp}"
DAEMON_LOG_CAP="${VIBESQUAD_DAEMON_LOG_CAP:-16777216}"     # 16 MiB
DAEMON_LOG_KEEP="${VIBESQUAD_DAEMON_LOG_KEEP:-3}"
TMUX_LOG_DIR="${VIBESQUAD_TMUX_LOG_DIR:-${VAULT_ROOT}/_state/tmux-logs}"
TMUX_LOG_CAP="${VIBESQUAD_TMUX_LOG_CAP:-16777216}"         # 16 MiB
TMUX_LOG_KEEP="${VIBESQUAD_TMUX_LOG_KEEP:-2}"

ROTATED=0
PRUNED=0
CANDIDATES=0
SKIPPED_UNSAFE=0

file_size() {
    # BSD and GNU stat disagree on flags, so try both -- but GNU FIRST. GNU
    # `stat -f` means --file-system: given a file it writes filesystem rows to
    # STDOUT and exits 1, so the BSD-first order returned those rows glued to
    # the real size, failed every numeric guard, and silently made rotation a
    # no-op on Linux. macOS `stat -c` has no such trap: empty stdout, rc=1.
    stat -c %s -- "$1" 2>/dev/null || stat -f %z -- "$1" 2>/dev/null
}

# Delete all but the newest $2 archives of $1. The archive suffix is a UTC
# timestamp in %Y%m%dT%H%M%SZ, so lexical order IS chronological and no
# stat/mtime call is needed to rank them.
prune_archives() {
    local base="$1" keep="$2" archives=() victim
    while IFS= read -r victim; do
        [[ -n "$victim" ]] && archives+=("$victim")
    done < <(printf '%s\n' "${base}".*.gz | sort)
    # The glob is literal when nothing matches; drop that one non-existent path.
    if [[ ${#archives[@]} -eq 1 && ! -f "${archives[0]}" ]]; then
        return 0
    fi
    local excess=$(( ${#archives[@]} - keep ))
    (( excess > 0 )) || return 0
    for victim in "${archives[@]:0:excess}"; do
        if [[ "$MODE" == "apply" ]]; then
            rm -f -- "$victim" && PRUNED=$((PRUNED + 1))
        else
            PRUNED=$((PRUNED + 1))
        fi
        printf -- '- prune: %s\n' "$victim"
    done
}

rotate_file() {
    local path="$1" cap="$2" keep="$3" size archive

    # Never follow a symlink: a rotation that resolves a link would gzip and
    # then TRUNCATE whatever the link points at, which is a much larger blast
    # radius than a log file. Same reasoning as bin/system-cleanup.sh's report
    # symlink guards.
    if [[ -L "$path" ]]; then
        printf -- '- skip (symlink, refused): %s\n' "$path"
        SKIPPED_UNSAFE=$((SKIPPED_UNSAFE + 1))
        return 0
    fi
    [[ -f "$path" ]] || return 0

    size="$(file_size "$path")"
    if [[ ! "$size" =~ ^[0-9]+$ ]]; then
        printf -- '- skip (size unreadable): %s\n' "$path"
        SKIPPED_UNSAFE=$((SKIPPED_UNSAFE + 1))
        return 0
    fi
    if (( size <= cap )); then
        return 0
    fi

    CANDIDATES=$((CANDIDATES + 1))
    archive="${path}.$(date -u +%Y%m%dT%H%M%SZ).gz"
    printf -- '- rotate: %s (%s bytes > %s cap) -> %s\n' "$path" "$size" "$cap" "$archive"

    if [[ "$MODE" == "apply" ]]; then
        # COPY. `gzip -c` reads and writes elsewhere; the live inode is
        # untouched until the truncate below.
        if ! gzip -c -- "$path" > "${archive}.partial" 2>/dev/null; then
            rm -f -- "${archive}.partial"
            echo "rotate-logs.sh: could not archive ${path}; leaving it alone" >&2
            return 0
        fi
        # Publish the archive only once it is complete, so an interrupted run
        # never leaves a half-written .gz that the next run counts as a kept
        # generation.
        mv -f -- "${archive}.partial" "$archive" || {
            rm -f -- "${archive}.partial"
            echo "rotate-logs.sh: could not publish ${archive}; leaving ${path} alone" >&2
            return 0
        }
        # TRUNCATE IN PLACE. Same inode, blocks freed now, O_APPEND writers
        # continue at offset 0. See the header.
        : > "$path" || {
            echo "rotate-logs.sh: archived ${path} but could not truncate it" >&2
            return 0
        }
        ROTATED=$((ROTATED + 1))
    fi

    prune_archives "$path" "$keep"
}

echo "# Log rotation — $(date -u +%FT%TZ)"
echo
echo "- mode: ${MODE}"
echo "- daemon logs: ${DAEMON_LOG_DIR} (cap ${DAEMON_LOG_CAP} bytes, keep ${DAEMON_LOG_KEEP})"
echo "- tmux logs:   ${TMUX_LOG_DIR} (cap ${TMUX_LOG_CAP} bytes, keep ${TMUX_LOG_KEEP})"
echo

for name in vibesquad-daemon-stdout.log vibesquad-daemon-stderr.log; do
    rotate_file "${DAEMON_LOG_DIR}/${name}" "$DAEMON_LOG_CAP" "$DAEMON_LOG_KEEP"
done

if [[ -d "$TMUX_LOG_DIR" ]]; then
    # `*.log` only. Archives are named `<name>.log.<stamp>.gz`, so they can
    # never be re-rotated into an archive of an archive.
    for path in "${TMUX_LOG_DIR}"/*.log; do
        [[ -e "$path" ]] || continue
        rotate_file "$path" "$TMUX_LOG_CAP" "$TMUX_LOG_KEEP"
    done
fi

echo
echo "## Summary"
echo
echo "- over cap: ${CANDIDATES}"
echo "- rotated: ${ROTATED}"
echo "- archives pruned: ${PRUNED}"
echo "- skipped as unsafe: ${SKIPPED_UNSAFE}"
if [[ "$MODE" != "apply" ]]; then
    echo "- nothing was written: re-run with --apply to rotate"
fi
