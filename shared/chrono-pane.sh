#!/usr/bin/env bash
# One home for "is the coordinator actually listening in that tmux pane?"
#
# Why this exists: both notifiers asked the question and both got it wrong, in
# different directions.
#
#   * outbox-watcher.sh compared `#{pane_current_command}` to the literal
#     "claude". The real value is the VERSIONED executable name -- measured
#     2026-08-16 on a live pane: "2.1.233". So the guard skipped even while
#     Chrono was running, every time, printing "no notification lost" as it
#     dropped the nudge. That is why board notifications went unseen for a whole
#     session.
#   * squad-monitor.sh had no check at all and typed alerts into whatever held
#     the pane. With Chrono exited that is a shell, which EXECUTES them:
#     "zsh: command not found: git", "zsh: no matches found: (26418 bytes)".
#
# Fixing one and leaving the other is how they drifted apart in the first place,
# so the rule lives here and both source it.
#
# The check is deliberately not a name match. tmux reports the FOREGROUND
# process name, which changes with every Claude release, so any literal is a
# time bomb. `#{pane_pid}` is the pane's shell; Claude runs as its child. Look
# at the children's real command lines instead -- version-independent.

# chrono_pane_has_coordinator <tmux-target>
# Returns 0 when the coordinator CLI is the live foreground process there.
chrono_pane_has_coordinator() {
    local target="$1" pane_pid="" child="" cmd=""
    local tmux_bin="${TMUX_BIN:-tmux}"

    pane_pid="$("$tmux_bin" display-message -p -t "$target" '#{pane_pid}' 2>/dev/null)" || return 1
    [[ -n "$pane_pid" ]] || return 1

    for child in $(pgrep -P "$pane_pid" 2>/dev/null); do
        cmd="$(ps -o command= -p "$child" 2>/dev/null)"
        # Match the executable path, not a bare word, so an unrelated process
        # that merely mentions "claude" in an argument cannot pass.
        [[ "$cmd" == */claude* ]] && return 0
    done

    # Direct exec (no wrapping shell) still reports a usable name.
    cmd="$("$tmux_bin" display-message -p -t "$target" '#{pane_current_command}' 2>/dev/null)"
    [[ "$cmd" == "claude" ]] && return 0
    return 1
}

# chrono_pane_observed_command <tmux-target>
# What is actually there, for a diagnosable skip message.
chrono_pane_observed_command() {
    local target="$1"
    "${TMUX_BIN:-tmux}" display-message -p -t "$target" '#{pane_current_command}' 2>/dev/null \
        || printf 'unavailable'
}
