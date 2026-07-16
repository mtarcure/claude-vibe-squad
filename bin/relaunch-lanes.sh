#!/bin/bash
# relaunch-lanes.sh — relaunch the 4 model-lane CLIs in place with the CURRENT
# launch-squad.sh model pins, WITHOUT a full squad restart (keeps the chrono
# coordinator session + watchers alive).
#
# Why this exists: Chrono (the coordinator Claude session) cannot relaunch lanes
# that use --dangerously-bypass-approvals-and-sandbox / --permission-mode
# bypassPermissions — its auto-mode safety classifier (correctly) refuses to
# spawn unsandboxed autonomous agents without operator authorization. Run after
# a model-version bump:
#
#   bash bin/relaunch-lanes.sh            # all four lanes
#   bash bin/relaunch-lanes.sh gemini     # a single lane
#
# The lane shells already hold the PATH/auth env from the original squad launch,
# so this only exits the running CLI and re-runs the new command.
# (macOS /bin/bash 3.2 compatible — no associative arrays.)
set -uo pipefail

SESSION="squad"
VR="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

cmd_for() {
  case "$1" in
    gpt-codex) echo "codex --dangerously-bypass-approvals-and-sandbox -c model_reasoning_effort=high" ;;
    claude)    echo "claude --permission-mode bypassPermissions --model claude-fable-5 --fallback-model claude-opus-4-8,claude-sonnet-5 --effort xhigh --add-dir ${VR}" ;;
    gemini)    echo "gemini --yolo --skip-trust --model gemini-3.5-flash --include-directories ${VR}" ;;
    kimi)      echo "kimi --yolo --thinking --model kimi-code/kimi-for-coding --agent-file ${VR}/model-lanes/kimi/main.yaml --add-dir ${VR}" ;;
    *)         echo "" ;;
  esac
}

if [ "$#" -gt 0 ]; then LANES="$*"; else LANES="gpt-codex claude gemini kimi"; fi

at_shell() {
  local last short_hostname
  last="$(tmux capture-pane -p -t "${SESSION}:$1" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -1)"
  short_hostname="$(hostname -s)"
  case "$last" in *"${short_hostname}"*%*) return 0 ;; *) return 1 ;; esac
}

for lane in $LANES; do
  c="$(cmd_for "$lane")"
  [ -z "$c" ] && { echo "!! unknown lane: $lane"; continue; }
  echo "== ${lane} =="
  # Exit the running CLI to the shell (idempotent; up to 3 C-c for 'press twice' TUIs).
  for _ in 1 2 3; do
    at_shell "$lane" && break
    tmux send-keys -t "${SESSION}:${lane}" C-c; sleep 1
  done
  if ! at_shell "$lane"; then
    echo "  WARN: ${lane} not at a shell prompt after C-c — relaunch by hand:"
    echo "        tmux send-keys -t ${SESSION}:${lane} '$c' C-m"
    continue
  fi
  tmux send-keys -t "${SESSION}:${lane}" "$c" C-m
  echo "  -> $c"
  sleep 6
done

echo
echo "Verify models:"
for w in gpt-codex claude gemini kimi; do
  echo "-- $w --"; tmux capture-pane -p -t "${SESSION}:$w" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -3
done
