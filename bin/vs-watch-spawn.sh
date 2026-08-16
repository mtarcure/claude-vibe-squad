#!/usr/bin/env bash
# Human-readable live view of a board spawn, shown in a tmux POPUP when the operator
# double-clicks a card. Streams the spawn's activity formatted like a CLI (not raw JSON).
# Always dismissable: press q/Esc to close (returns to Chrono), or s to stop the spawn
# (reliable process-tree cancel). Exiting this script closes the popup.
set -u
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
LOG="${1:-}"
[ -n "$LOG" ] || { echo "no log path"; sleep 2; exit 0; }

BASE="${LOG%.log}"
DISPATCH="${BASE}.dispatch.json"
read_json() { python3 -c "import json,sys,os;p='$1';print(json.load(open(p)).get('$2','') if os.path.exists(p) else '')" 2>/dev/null; }
TASK="$(read_json "$DISPATCH" task_id)"; [ -n "$TASK" ] || TASK="spawn"

printf '\033[H\033[2J'
printf '\033[1;38;5;45m── %s · live CLI ──\033[0m   press \033[1mq\033[0m to close · \033[1;38;5;203ms\033[0m to stop\n\n' "$TASK"

# Stream the readable log in the BACKGROUND so the foreground can watch for a quit key.
tail -n +1 -f "$LOG" 2>/dev/null | python3 "$VAULT_ROOT/bin/vs-format-events.py" &
STREAM=$!
cleanup() { kill "$STREAM" 2>/dev/null; }
trap 'cleanup; exit 0' INT TERM HUP

# q/Esc close the popup; s stops the spawn; the loop also exits when the stream dies
# (spawn finished). read -t 1 keeps it responsive to both keys and stream death.
while kill -0 "$STREAM" 2>/dev/null; do
  if IFS= read -rsn1 -t 1 key 2>/dev/null; then
    case "$key" in
      q|Q|$'\033') break ;;
      s|S)
        cleanup
        printf '\n\033[1;38;5;203mstopping specialist…\033[0m\n'
        env VAULT_ROOT="$VAULT_ROOT" bash "$VAULT_ROOT/bin/vs-cancel-spawn.sh" "$LOG"
        printf '\033[2mpress any key to close\033[0m'; IFS= read -rsn1 _ 2>/dev/null
        break ;;
    esac
  fi
done
cleanup
# on exit the popup closes and returns you to Chrono
