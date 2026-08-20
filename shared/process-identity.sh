#!/usr/bin/env bash
# Exact-positional process identity predicates, shared by every entry point that
# has to answer "is the process at this PID really ours?".
#
# One home for one fact (CLAUDE.md rule 10): the vs-lane-status.sh poller's
# invocation shape is asserted by two scripts with opposite jobs --
# bin/squad-stop.sh must not KILL a PID that is no longer the poller, and
# bin/launch-squad.sh must not SPAWN a duplicate when a live poller exists that
# its pidfile does not name. If those two copies of the shape ever drift, the
# launcher adopts a poller the stopper then refuses to reap, and the leak this
# file exists to close comes straight back.
#
# Requires VAULT_ROOT (shared/repo-root.sh) to be set by the sourcing script.
#
# This file is sourced, never executed, so it deliberately declares no `set -e`
# / `set -u` / `set -o pipefail` of its own: those would mutate the CALLER's
# shell. bin/squad-stop.sh in particular runs `set -uo pipefail` without -e on
# purpose -- a stopper that aborts on the first non-zero command would abandon
# the rest of its cleanup. The pre-commit format check greps every *.sh for
# `set -` and warns here; shared/repo-root.sh and shared/namespaces.sh are
# sourced libraries in the same position.
#
# Why exact positional matching, never `pgrep -f` / substring / token-anywhere:
# a specialist's entire compiled prompt is its own argv -- 41,008 bytes measured
# on a live `codex exec` -- and it is plain text that can contain any filename
# this repo greps for as ordinary prose. Substring matching a process list is
# how the operator's live watcher fleet got killed by a regression test
# (Plan B Tasks 1 and 8).

# Args: $1 pid. True only if the live process at $1 is, structurally, the
# vs-lane-status.sh poller: exactly two argv elements, argv[0] named `bash`, and
# argv[1] equal to THIS root's poller path. That is the one shape
# bin/launch-squad.sh's "Live status poller" section ever spawns -- identical
# across both its token/file-mode branches, since the mode is carried in the
# environment rather than in argv. A different checkout's poller, a wrapper with
# an extra flag, and a 41KB prompt that merely quotes the path all fail it.
#
# Known limit, for the same reason: what the mode carries in the environment,
# this predicate cannot see. VIBESQUAD_STATUS_DIR never appears in argv, so the
# match is VAULT_ROOT-scoped but NOT status-dir-scoped -- two launches of the
# SAME checkout pointed at different status dirs would each see the other's
# poller as a valid candidate. Not reachable today (the only override path also
# isolates VAULT_ROOT), and closing it would mean putting the status dir in the
# poller's argv, which is a change to the spawn shape, not to this file.
#
# `ps -o args=` prints the kernel's argv space-joined and re-adds NO quoting,
# so it cannot be tokenized back into argv unambiguously. This compares the
# whole tail against the ONE expected string instead of re-splitting it. The
# previous `read -r -a tokens` split on IFS, which made the predicate "two
# whitespace-separated WORDS" rather than "two argv elements": any VAULT_ROOT
# containing a space -- `~/Library/Mobile Documents/...`, `~/Google Drive/My
# Drive/...`, `~/Obsidian Vaults/...`, all ordinary macOS clone locations for
# what is itself an Obsidian vault -- tokenized to 3+ and failed. It broke
# identity in BOTH directions: bin/launch-squad.sh never adopts, so it spawns
# a duplicate poller and orphans the previous one on every `squad up`; and
# bin/squad-stop.sh refuses to kill, prints "alive but no longer identifies as
# ... (stale/recycled PID)" -- a confident, specific, wrong diagnosis -- then
# deletes the only record of a live process it just declined to reap.
#
# Exact string equality on the tail preserves everything the token form
# guaranteed: the tail must be the poller path and nothing else, so a third
# argv element (which would append " <element>") cannot match, and a 41KB
# prompt cannot either.
pid_is_vs_lane_status_poller() {
    local pid="$1" expected_script="${VAULT_ROOT}/bin/vs-lane-status.sh" args executable rest
    args="$(ps -o args= -p "${pid}" 2>/dev/null)"
    [[ -n "${args}" ]] || return 1
    executable="${args%% *}"
    rest="${args#* }"
    # No space at all means a single argv element -- argv[1] does not exist.
    [[ "${executable}" != "${args}" ]] || return 1
    [[ "$(basename -- "${executable}")" == "bash" ]] || return 1
    [[ "${rest}" == "${expected_script}" ]] || return 1
    return 0
}

# Print the PID of every live poller belonging to THIS root, one per line.
# Candidates come from the kernel's own executable name (`ps -o comm=`), which
# no argv text can forge, and each candidate is then confirmed by the exact
# positional argv check above -- never a substring scan of the process list.
#
# Lives here rather than in bin/launch-squad.sh because two entry points now ask
# it the same question from opposite ends: the launcher asks "may I spawn one?"
# and bin/doctor.sh asks "is there exactly one?". A `pgrep -c` in the health
# check would have been a second, weaker answer to a question this file already
# answers correctly -- and would have re-created the argv-substring defect that
# killed the operator's live watcher fleet.
find_live_vs_lane_status_pollers() {
    local pid comm
    while read -r pid comm; do
        [[ "$pid" =~ ^[0-9]+$ ]] || continue
        [[ "$(basename -- "$comm")" == "bash" ]] || continue
        pid_is_vs_lane_status_poller "$pid" || continue
        printf '%s\n' "$pid"
    done < <(ps -eo pid=,comm= 2>/dev/null)
}
