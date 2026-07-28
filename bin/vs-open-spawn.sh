#!/usr/bin/env bash
# DoubleClick handler for the SPECIALIST SWARM dashboard pane.
#
# Maps the pane-relative click (mouse_y, mouse_x) to the spawn card under it via the
# hit-map the dashboard writes each frame (bin/vs-board-dashboard.py -> VS_DASH_HITMAP)
# and opens that spawn's live streaming log in a new tmux window — the board-native
# equivalent of the old "double-click a lane to open its CLI". Board spawns are
# detached, so "opening the CLI" means tailing the live log the supervisor streams.
set -u
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
MY="${1:-}"
MX="${2:-}"
MODE="${3:-any}"   # 'history' = single-click (toggle only) · 'card' = double-click (open only)
HITMAP="${VS_DASH_HITMAP:-/tmp/vs-dash-hitmap.tsv}"

if [ -z "$MY" ] || [ -z "$MX" ] || [ ! -f "$HITMAP" ]; then
  exit 0
fi

while IFS=$'\t' read -r y0 y1 x0 x1 task log; do
  [ -z "${y0:-}" ] && continue
  if [ "$MY" -ge "$y0" ] && [ "$MY" -lt "$y1" ] && [ "$MX" -ge "$x0" ] && [ "$MX" -lt "$x1" ]; then
    if [ "$task" = "@HISTORY" ]; then
      [ "$MODE" = "card" ] && exit 0   # single-click owns the history toggle
      HIST_STATE="${VS_DASH_HISTSTATE:-/tmp/vs-dash-history.state}"
      if [ "$(cat "$HIST_STATE" 2>/dev/null)" = "open" ]; then
        printf 'closed\n' > "$HIST_STATE"
      else
        printf 'open\n' > "$HIST_STATE"
      fi
      exit 0
    fi
    # a specialist card — opening its CLI is a DOUBLE-click action
    [ "$MODE" = "history" ] && exit 0
    # Harden against command injection: only a sanitized short name is ever displayed,
    # and the log path must be a board-dispatch .log containing no shell metacharacters
    # before it is embedded in the window command.
    short="$(printf '%s' "$task" | tr -cd 'A-Za-z0-9._-' | tail -c 24)"
    case "$log" in
      */_state/board-dispatch/*.log) : ;;
      *) tmux display-message "swarm: unrecognized log path"; exit 0 ;;
    esac
    case "$log" in
      *[!A-Za-z0-9._/-]*) tmux display-message "swarm: log path rejected"; exit 0 ;;
    esac
    if [ -f "$log" ]; then
      # Ephemeral POPUP viewer (overlay) — not a window, so it never lingers in the
      # status bar or duplicates; it dismisses the moment you close it (Ctrl-C then
      # Enter), returning you to Chrono. Formatted live CLI + a labeled Stop.
      tmux display-popup -E -w 90% -h 85% \
        -T " ${short} · live CLI — Ctrl-C then Enter to close " \
        "env VAULT_ROOT='$VAULT_ROOT' bash '$VAULT_ROOT/bin/vs-watch-spawn.sh' '$log'"
    else
      tmux display-message "specialist ${short} has no log yet"
    fi
    exit 0
  fi
done < "$HITMAP"

tmux display-message "no specialist card under that click"
exit 0
