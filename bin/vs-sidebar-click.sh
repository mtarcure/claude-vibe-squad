#!/usr/bin/env bash
# Handle clicks on the Chrono sidebar dashboard. Bound to mouse events by
# sidebar.sh, guarded to the sidebar pane. Single-click toggles an in-place live
# preview of a lane; double-click jumps to that lane's full window. State lives
# in a focus file that watch-lane.sh reads each frame.
set -uo pipefail

SESSION="${SQUAD_SESSION:-squad}"
FOCUS=/tmp/vs-sidebar-focus
LANES=(gpt-codex claude gemini kimi)

action="${1:-single}"
mouse_y="${2:-0}"
pane_h="${3:-40}"
[[ "$mouse_y" =~ ^[0-9]+$ ]] || mouse_y=0
[[ "$pane_h" =~ ^[0-9]+$ ]] || pane_h=40

# Which lane card sits under this row? Mirrors watch-lane's layout: row 0 is the
# MODEL LANES header, row 1 blank, then 4 cards of (card_h + 1) rows each.
lane_from_y() {
    local y="$1" ph="$2" card_h idx
    card_h=$(( (ph - 8) / 4 )); (( card_h < 7 )) && card_h=7
    idx=$(( (y - 2) / (card_h + 1) ))
    (( idx < 0 )) && idx=0
    (( idx > 3 )) && idx=3
    printf '%s' "${LANES[$idx]}"
}

focus=""
[[ -f "$FOCUS" ]] && focus="$(cat "$FOCUS" 2>/dev/null || true)"

case "$action" in
    single)
        if [[ -n "$focus" ]]; then
            : > "$FOCUS"                                    # previewing → back to cards
        else
            lane_from_y "$mouse_y" "$pane_h" > "$FOCUS"     # card → preview that lane
        fi
        ;;
    double)
        lane="$focus"
        [[ -z "$lane" ]] && lane="$(lane_from_y "$mouse_y" "$pane_h")"
        : > "$FOCUS"                                        # collapse preview
        tmux select-window -t "${SESSION}:${lane}" 2>/dev/null || true
        ;;
esac

touch "$FOCUS" 2>/dev/null || true                         # bump mtime → instant redraw
