#!/usr/bin/env bash
# Idempotently (re)install the swarm-dashboard mouse bindings on a LIVE tmux session.
#
# Why this exists as a standalone script rather than only inside sidebar.sh:
# bindings are installed at session start. A long-lived session therefore keeps whatever
# binding set existed when it started, and any binding added later is invisible to it.
# Measured: DoubleClick1Pane (open a spawn's live CLI) shipped 2026-07-12 20:26, a tmux
# server started before that kept running for three weeks, and double-click silently fell
# through to copy-mode word-select the whole time. Nothing was broken in the code; the
# session simply predated the feature.
#
# Safe to run repeatedly, and safe to run against a session that already has them.
#
#   bash bin/vs-ensure-bindings.sh [session]
set -u
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

SESSION="${1:-${VS_SESSION:-squad}}"

if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
    printf 'vs-ensure-bindings: no tmux session %s\n' "${SESSION}" >&2
    exit 1
fi

SIDEBAR_PANE="$(tmux display-message -p -t "${SESSION}:chrono.1" '#{pane_id}' 2>/dev/null)"
if [[ -z "${SIDEBAR_PANE}" ]]; then
    printf 'vs-ensure-bindings: could not resolve the dashboard pane in %s\n' "${SESSION}" >&2
    exit 1
fi

# single-click on the swarm pane -> toggle the recent-spawns dropdown
tmux bind-key -T root MouseUp1Pane if-shell -F "#{==:#{mouse_pane},${SIDEBAR_PANE}}" \
    "run-shell \"bash ${VAULT_ROOT}/bin/vs-open-spawn.sh #{mouse_y} #{mouse_x} history\"" \
    "send-keys -M" 2>/dev/null || true

# double-click a card -> open that spawn's live CLI view
tmux bind-key -T root DoubleClick1Pane if-shell -F "#{==:#{mouse_pane},${SIDEBAR_PANE}}" \
    "run-shell \"bash ${VAULT_ROOT}/bin/vs-open-spawn.sh #{mouse_y} #{mouse_x} card\"" \
    "select-pane -t = ; send-keys -M" 2>/dev/null || true

single=$(tmux list-keys -T root 2>/dev/null | grep -c "MouseUp1Pane.*vs-open-spawn" || true)
double=$(tmux list-keys -T root 2>/dev/null | grep -c "DoubleClick1Pane.*vs-open-spawn" || true)
printf 'vs-ensure-bindings: pane=%s single-click=%s double-click=%s\n' "${SIDEBAR_PANE}" "${single}" "${double}"
[[ "${single}" -ge 1 && "${double}" -ge 1 ]]
