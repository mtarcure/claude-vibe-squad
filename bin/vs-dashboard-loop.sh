#!/usr/bin/env bash
# Live board-native dashboard pane: re-render the spawn-card view every interval.
# Replaces the old 4-lane watch-lane.sh render. Sized to the live pane width.
set -u
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
export VAULT_ROOT
INTERVAL="${VS_DASH_INTERVAL:-1}"  # 1s so the idle hourglass animation doesn't skip frames
PYBIN="${PYBIN:-python3}"

# Flicker-free: hide the cursor and clear ONCE, then repaint in place every frame
# (the renderer homes the cursor + erases each line + clears below in VS_DASH_INPLACE
# mode). A full \033[2J per frame is what caused the blink. Restore cursor on exit.
printf '\033[?25l\033[2J'
trap 'printf "\033[?25h\033[2J\033[H"' EXIT INT TERM
while true; do
  size="$(tmux display -p -t "${TMUX_PANE:-}" '#{pane_width} #{pane_height}' 2>/dev/null)"
  cols="${size%% *}"
  rows="${size##* }"
  [ -z "$cols" ] && cols="$(tput cols 2>/dev/null || echo 80)"
  [ -z "$rows" ] && rows="$(tput lines 2>/dev/null || echo 40)"
  VS_DASH_INPLACE=1 VS_DASH_WIDTH="$cols" VS_DASH_HEIGHT="$rows" \
    VS_DASH_CAPACITY="${VS_DASH_CAPACITY:-10}" \
    "$PYBIN" "$VAULT_ROOT/bin/vs-board-dashboard.py" </dev/null 2>&1
  sleep "$INTERVAL"
done
