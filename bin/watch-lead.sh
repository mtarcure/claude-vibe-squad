#!/bin/bash
# Watch a Lead — multi-rate dashboard widget. v2 design (per GPT-5.5 consult, 2026-05-02).
#
# Layout (5 rows, ~42-80 cols wide):
#   ┌● CODING  WORKING ⠹  2m ago   ▆▇█▆▃     ┐
#   │ Focus: fixing auth retry edge case     │
#   │ Last: patched tests; checking failure  │
#   │ Mail  i:02  a:01  o:03   SLA 04m       │
#   └ pulse ▁▃▅▆█▇▆▄▂  clear          14:32  ┘
#
# Multi-rate refresh — different fields update at different cadences so the
# eye perceives smooth motion (spinner) without ever blinking the whole tile:
#   spinner  : 150ms  (just rotates 1 char)
#   state    : 1s     (mtime checks, cheap)
#   counts   : 2s     (file counts)
#   summaries: 5s     (only re-parses when newest mtime changes)
#
# Renders with cursor positioning + clear-to-EOL — no full-screen clear.
#
# Usage: bin/watch-lead.sh <lead> [width]   (width auto-detected if omitted)

set -uo pipefail

LEAD="${1:-}"
WIDTH="${2:-}"

if [[ -z "${LEAD}" ]]; then
    echo "usage: $0 <coding|security|content|sysmgmt|research> [width]"
    exit 1
fi

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
DEPT="${VAULT_ROOT}/departments/${LEAD}"
LOG="${VAULT_ROOT}/_state/tmux-logs/${LEAD}.log"

case "${LEAD}" in
    coding)   CLI="Codex" ; ACCENT_FG=214 ;;  # amber  — build/code
    security) CLI="Claude"; ACCENT_FG=203 ;;  # coral  — alert/security
    content)  CLI="Gemini"; ACCENT_FG=213 ;;  # pink   — creative
    sysmgmt)  CLI="Claude"; ACCENT_FG=84  ;;  # mint   — ops/healthy
    research) CLI="Kimi"  ; ACCENT_FG=117 ;;  # sky    — deep/analytic
    *) echo "unknown lead: ${LEAD}"; exit 1 ;;
esac
ACCENT=$'\033[1;38;5;'${ACCENT_FG}$'m'  # bold + lead-specific 256-color
UPPER=$(echo "${LEAD}" | tr '[:lower:]' '[:upper:]')

[[ -z "${WIDTH}" ]] && WIDTH=$(tput cols 2>/dev/null || echo 42)
[[ ${WIDTH} -lt 30 ]] && WIDTH=30
INNER=$((WIDTH - 2))

# ─── ANSI colors (256-color palette) ──────────────────────────────
BORD=$'\033[38;5;240m'   # dim gray border
ON=$'\033[38;5;46m'      # working dot — bright green
OFF=$'\033[38;5;240m'    # idle dot — dim
WORK=$'\033[38;5;45m'    # WORKING text — cyan
IDLE=$'\033[38;5;245m'   # idle gray
BLOCK=$'\033[38;5;214m'  # amber
ERR=$'\033[38;5;196m'    # red
LBL=$'\033[38;5;244m'    # labels
TXT=$'\033[38;5;252m'    # body text
DIM=$'\033[38;5;240m'    # dim
B=$'\033[1m'             # bold
RST=$'\033[0m'
# In-place positioning
HOME_CUP=$'\033[H'
CLR_EOL=$'\033[K'

# ─── Frame state (for selective updates) ───────────────────────────
SPINNERS=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
spinner_idx=0
prev_state=''; prev_age=''; prev_focus=''; prev_last=''; prev_counts=''; prev_pulse=''
last_state_check=0; last_counts_check=0; last_summary_check=0
focus_text=''; last_text=''; sparkline=''; pulse=''; status_word='clear'
sla_str='—'; counts_inbox=0; counts_active=0; counts_outbox=0

# ─── Helper functions ──────────────────────────────────────────────
human_age() {
    local mtime="$1"
    local age=$(( $(date +%s) - mtime ))
    if   [[ ${age} -lt 60 ]];     then printf '%ds' "${age}"
    elif [[ ${age} -lt 3600 ]];   then printf '%dm' $((age / 60))
    elif [[ ${age} -lt 86400 ]];  then printf '%dh' $((age / 3600))
    else                               printf '%dd' $((age / 86400))
    fi
}

newest_mtime_in_dir() {
    find "$1" -maxdepth 1 -type f -name 'TASK-*' 2>/dev/null \
        | xargs -I{} stat -f '%m' {} 2>/dev/null | sort -rn | head -1
}

oldest_mtime_in_dir() {
    find "$1" -maxdepth 1 -type f -name 'TASK-*' 2>/dev/null \
        | xargs -I{} stat -f '%m' {} 2>/dev/null | sort -n | head -1
}

# Parse newest active task for Focus line
read_focus() {
    local f
    f=$(find "${DEPT}/active" -maxdepth 1 -type f -name 'TASK-*.md' 2>/dev/null \
        | xargs -I{} stat -f '%m %N' {} 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    [[ -z "$f" || ! -f "$f" ]] && { echo ""; return; }
    awk '/^---$/{c++; if(c==2){flag=1; next}} flag && NF{print; exit}' "$f"
}

# Parse newest outbox response for Last line.
# Strategy: take first non-meta body line. Meta openers (e.g. "This TASK is...",
# "This response leads with...", "Our inter-departmental workflows now...") are
# filler that gets truncated mid-sentence and tells the operator nothing useful.
# Prefer a real H1 if present, else first non-filler paragraph line.
read_last() {
    local f
    f=$(find "${DEPT}/outbox" "${DEPT}/archive" -maxdepth 1 -type f -name 'TASK-*-response.md' 2>/dev/null \
        | xargs -I{} stat -f '%m %N' {} 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    [[ -z "$f" || ! -f "$f" ]] && { echo ""; return; }

    # First pass: prefer a real H1 (# Heading) — it's authored as a summary.
    local h1
    h1=$(awk '/^---$/{c++; if(c==2){flag=1; next}} flag && /^# /{sub(/^# */,""); print; exit}' "$f" \
        | sed 's/[`*_]//g')
    if [[ -n "${h1}" ]]; then
        echo "${h1}"
        return
    fi

    # Second pass: first non-filler paragraph line. Skip lines that begin with
    # known meta openers — they're verbose context, not deliverable summaries.
    awk '
        /^---$/{c++; if(c==2){flag=1; next}}
        flag && NF && !/^#/ {
            line=$0
            if (line ~ /^(This TASK|This response|Our inter-departmental|The following|Below is|Here is the response|I have completed|I will|I am)/) next
            sub(/^[`*_]+/,"",line); sub(/[`*_]+$/,"",line)
            print line; exit
        }
    ' "$f"
}

detect_state() {
    # Mailbox is the source of truth — squad's operator-only-talks-to-chrono
    # model means a Lead is "working" iff there's a task in active/.
    if [[ ${counts_active} -gt 0 ]]; then echo "working"; return; fi
    if [[ ${counts_inbox}  -gt 0 ]]; then echo "pending"; return; fi
    # Error state ONLY if the newest outbox response's frontmatter declares it
    # (e.g., `status: failed` or `status: error`). Don't grep the body — it
    # produces false positives on legitimate work like threat modeling that
    # naturally discusses error scenarios.
    local of
    of=$(find "${DEPT}/outbox" -maxdepth 1 -type f -name 'TASK-*-response.md' 2>/dev/null \
         | xargs -I{} stat -f '%m %N' {} 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [[ -n "$of" ]]; then
        # Read only the frontmatter (between the first two `---` lines)
        local frontmatter
        frontmatter=$(awk '/^---$/{c++; if(c==2) exit; next} c==1' "$of" 2>/dev/null)
        if echo "$frontmatter" | grep -qiE '^status:[[:space:]]*(failed|error|blocked)\b'; then
            echo "error"; return
        fi
    fi
    echo "idle"
}

# Build a sparkline from N timestamp buckets over a window. Reads the 4 mailbox
# dirs + log for any mtime activity, buckets into N equal time-slices.
build_pulse() {
    local n=10 mins=60
    local now=$(date +%s)
    python3 -c "
import os, glob, math, time
n=${n}; mins=${mins}; now=${now}
buckets=[0]*n
window=mins*60
for d in ('inbox','active','outbox','archive'):
    p=os.path.join('${DEPT}', d)
    if not os.path.isdir(p): continue
    for f in os.listdir(p):
        if not f.startswith('TASK-'): continue
        try: mt=os.path.getmtime(os.path.join(p,f))
        except OSError: continue
        age=now-mt
        if 0<=age<=window:
            idx=min(n-1, max(0, int(((window-age)/window)*n)))
            buckets[idx]+=1
mx=max(buckets) or 1
chars='▁▂▃▄▅▆▇█'
print(''.join(chars[min(len(chars)-1, int(round((c/mx)*(len(chars)-1))))] if c else '_' for c in buckets))
" 2>/dev/null || echo '__________'
}

# ─── Initial paint ──────────────────────────────────────────────────
trap 'printf "\033[?25h%s" "${RST}"' EXIT INT TERM
printf '\033[?25l\033[2J%s' "${HOME_CUP}"

# ─── Truncate-and-pad helper ────────────────────────────────────────
fit() {
    local s="$1" max="$2"
    if [[ ${#s} -gt ${max} ]]; then
        printf '%s' "${s:0:$((max - 1))}…"
    else
        printf '%s%*s' "$s" $((max - ${#s})) ''
    fi
}

# ─── Main loop ──────────────────────────────────────────────────────
TICK=0
while true; do
    # spinner rotates every iteration (150ms)
    spinner_idx=$(((spinner_idx + 1) % 10))
    spinner="${SPINNERS[$spinner_idx]}"

    NOW=$(date +%s)

    # Refresh state + counts at 1s rate (every 7th tick if 150ms loop)
    if [[ $((NOW - last_state_check)) -ge 1 ]]; then
        last_state_check=$NOW
        counts_inbox=$(ls "${DEPT}/inbox" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
        counts_active=$(ls "${DEPT}/active" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
        counts_outbox=$(ls "${DEPT}/outbox" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
        state=$(detect_state)

        # "Age" = time since last MEANINGFUL squad activity (a TASK file moved,
        # response written, etc.) — NOT log mtime, because pipe-pane logs update
        # constantly from TUI redraw bytes even when the Lead is idle.
        newest=0
        for sub in inbox active outbox archive; do
            t=$(newest_mtime_in_dir "${DEPT}/${sub}")
            [[ -n "$t" && "$t" -gt $newest ]] && newest=$t
        done
        if [[ $newest -gt 0 ]]; then
            age_str="$(human_age $newest)"
        else
            age_str="—"
        fi

        # SLA = age of OLDEST item in inbox
        sla_t=$(oldest_mtime_in_dir "${DEPT}/inbox")
        if [[ -n "${sla_t}" ]]; then
            sla_str="$(human_age $sla_t)"
        else
            sla_str="—"
        fi
    fi

    # Refresh focus + last + sparkline at 5s rate
    if [[ $((NOW - last_summary_check)) -ge 5 ]]; then
        last_summary_check=$NOW
        focus_text=$(read_focus)
        last_text=$(read_last)
        pulse=$(build_pulse)
        sparkline="${pulse: -5}"  # last 5 chars as mini sparkline for header

        # GPT-5.5 v3 design: per-tile run-health line — surfaces deliverable
        # health rather than just activity. Resolves run-id from active task,
        # falls back to most recent archive task; reads vibecoding verdict from
        # _state/vibecoding-check/<run-id>.md if present.
        run_id_short=""
        vc_verdict=""
        latest_task=$(find "${DEPT}/active" "${DEPT}/archive" -maxdepth 1 -type f -name 'TASK-*.md' 2>/dev/null \
                      ! -name '*-response.md' \
                      | xargs -I{} stat -f '%m %N' {} 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
        if [[ -n "${latest_task}" ]]; then
            run_id=$(basename "${latest_task}" .md)
            run_id_short="${run_id##*-}"  # last 8 chars after last dash
            vc_file="${VAULT_ROOT}/_state/vibecoding-check/${run_id}.md"
            if [[ -f "${vc_file}" ]]; then
                verdict=$(awk -F': ' '/^verdict:/{print $2; exit}' "${vc_file}" 2>/dev/null)
                case "${verdict}" in
                    PASS|PASS-AFTER-AUTOFIX) vc_verdict='ok' ;;
                    RETRY-NEEDED) vc_verdict='retry' ;;
                    OPERATOR-SURFACE) vc_verdict='surf' ;;
                    *) vc_verdict='?' ;;
                esac
            else
                vc_verdict='—'  # no vibecoding check yet
            fi
        fi
        # Status word
        case "$state" in
            error)   status_word="${ERR}error${RST}" ;;
            blocked) status_word="${BLOCK}blocked${RST}" ;;
            pending) status_word="${BLOCK}waiting${RST}" ;;
            working) status_word="${WORK}active${RST}" ;;
            *)       status_word="${IDLE}clear${RST}"   ;;
        esac
    fi

    # ─── Repaint (cursor home, line-by-line) ───
    printf '%s' "${HOME_CUP}"

    # State color + dot
    case "$state" in
        working) state_col="${WORK}"; dot="${ON}●${RST}"; state_label="WORKING ${spinner}" ;;
        pending) state_col="${BLOCK}"; dot="${BLOCK}○${RST}"; state_label="WAITING ${spinner}" ;;
        error)   state_col="${ERR}"; dot="${ERR}●${RST}"; state_label="ERROR" ;;
        *)       state_col="${IDLE}"; dot="${OFF}○${RST}"; state_label="idle" ;;
    esac

    # Line 1: top border with embedded status — use ─ to fill to right corner
    # Plain-text length used for padding (strip ANSI escapes for length calc)
    head_plain=$(printf "%s %s %s %s %s" "●" "${UPPER}" "${state_label}" "${age_str}" "${sparkline:0:5}")
    head_visible_len=${#head_plain}
    # Width budget: WIDTH cols total, ┌ + space + content + ─ filler + ┐ = WIDTH chars
    fill_count=$(( WIDTH - head_visible_len - 4 ))
    [[ $fill_count -lt 0 ]] && fill_count=0
    fill_dashes=$(printf '─%.0s' $(seq 1 $fill_count))
    printf "%s┌%s %s %s%-8s%s %s%s%s %s   %s%s%s %s%s%s%s\n" \
        "${BORD}" "${RST}" \
        "${dot}" "${ACCENT}" "${UPPER}" "${RST}" \
        "${state_col}" "${state_label}" "${RST}" "${age_str}" \
        "${DIM}" "${sparkline:0:5}" "${RST}" \
        "${BORD}${fill_dashes}┐${RST}" "${RST}" "${RST}" "${CLR_EOL}"

    # Line 2: Focus (left │ … right │)
    f_short=$(echo "${focus_text}" | head -1)
    [[ -z "${f_short}" ]] && f_short="(no active task)"
    f_padded=$(fit "${f_short}" $((WIDTH - 11)))
    printf "%s│%s %sFocus:%s %s%s%s %s│%s%s\n" \
        "${BORD}" "${RST}" "${LBL}" "${RST}" \
        "${TXT}" "${f_padded}" "${RST}" \
        "${BORD}" "${RST}" "${CLR_EOL}"

    # Line 3: Last
    l_short=$(echo "${last_text}" | head -1)
    [[ -z "${l_short}" ]] && l_short="(no recent reply)"
    l_padded=$(fit "${l_short}" $((WIDTH - 11)))
    printf "%s│%s %sLast:%s  %s%s%s %s│%s%s\n" \
        "${BORD}" "${RST}" "${LBL}" "${RST}" \
        "${TXT}" "${l_padded}" "${RST}" \
        "${BORD}" "${RST}" "${CLR_EOL}"

    # Line 4: Mail counts + SLA + Run / VC verdict (deliverable health)
    out_color="${LBL}"
    [[ ${counts_outbox} -gt 0 ]] && out_color="${ON}"
    # Build with VC verdict color depending on outcome
    case "${vc_verdict}" in
        ok)    vc_col="${ON}"  ; vc_label="ok"   ;;
        retry) vc_col="${BLOCK}"; vc_label="retry" ;;
        surf)  vc_col="${ERR}" ; vc_label="surf"  ;;
        '—'|'') vc_col="${LBL}" ; vc_label="${vc_verdict:-—}" ;;
        *)     vc_col="${LBL}" ; vc_label="${vc_verdict}" ;;
    esac
    if [[ -n "${run_id_short}" ]]; then
        mail_plain=$(printf "i:%02d a:%02d o:%02d  Run %s  VC %s  SLA %s" \
            "${counts_inbox}" "${counts_active}" "${counts_outbox}" \
            "${run_id_short}" "${vc_label}" "${sla_str}")
    else
        mail_plain=$(printf "Mail  i:%02d  a:%02d  o:%02d   SLA %s" \
            "${counts_inbox}" "${counts_active}" "${counts_outbox}" "${sla_str}")
    fi
    mail_padded=$(fit "${mail_plain}" $((WIDTH - 4)))
    printf "%s│%s %s%s%s %s│%s%s\n" \
        "${BORD}" "${RST}" "${LBL}" "${mail_padded}" "${RST}" \
        "${BORD}" "${RST}" "${CLR_EOL}"

    # Line 5: pulse sparkline + status word + clock — bottom border
    clock=$(date '+%H:%M:%S')
    bot_plain=$(printf " pulse %s   %s   %s " "${pulse}" "$(printf '%s' "${status_word}" | sed 's/\x1b\[[0-9;]*m//g')" "${clock}")
    bot_visible_len=${#bot_plain}
    bot_fill=$(( WIDTH - bot_visible_len - 2 ))
    [[ $bot_fill -lt 0 ]] && bot_fill=0
    bot_dashes=$(printf '─%.0s' $(seq 1 $bot_fill))
    printf "%s└ %spulse%s %s%s%s   %s   %s%s%s %s%s┘%s%s\n" \
        "${BORD}" "${LBL}" "${RST}" \
        "${DIM}" "${pulse}" "${RST}" "${status_word}" \
        "${LBL}" "${clock}" "${RST}" \
        "${BORD}" "${bot_dashes}" "${RST}" "${CLR_EOL}"

    # Pad to bottom of pane (clear any residual)
    printf '\033[J'

    sleep 0.15
done
