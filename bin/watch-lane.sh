#!/bin/bash
# Watch model-lane status. Use `all` for the Chrono sidebar dashboard or pass
# a single lane for a focused tile.

set -uo pipefail

LANE="${1:-all}"
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
SESSION="${SQUAD_SESSION:-squad}"
SQUAD_WATCH_COMPACT="${SQUAD_WATCH_COMPACT:-0}"
source "${VAULT_ROOT}/shared/lead-windows.sh"

case "${LANE}" in
    all|gpt-codex|claude|gemini|kimi) ;;
    *) echo "usage: $0 all|gpt-codex|claude|gemini|kimi"; exit 1 ;;
esac

color() { printf '\033[%sm%s\033[0m' "$1" "$2"; }
c256() { printf '\033[38;5;%sm%s\033[0m' "$1" "$2"; }
hide_cursor() { printf '\033[?25l'; }
show_cursor() { printf '\033[?25h'; }
home() { printf '\033[H'; }
clear_to_end() { printf '\033[J'; }

pane_cols() {
    local cols
    if [[ -n "${TMUX_PANE:-}" ]] && command -v tmux >/dev/null 2>&1; then
        cols="$(tmux display-message -p -t "${TMUX_PANE}" '#{pane_width}' 2>/dev/null || true)"
        [[ "$cols" =~ ^[0-9]+$ ]] && { echo "$cols"; return; }
    fi
    cols="${COLUMNS:-}"
    [[ "$cols" =~ ^[0-9]+$ ]] && { echo "$cols"; return; }
    tput cols 2>/dev/null || echo 70
}

pane_rows() {
    local rows
    if [[ -n "${TMUX_PANE:-}" ]] && command -v tmux >/dev/null 2>&1; then
        rows="$(tmux display-message -p -t "${TMUX_PANE}" '#{pane_height}' 2>/dev/null || true)"
        [[ "$rows" =~ ^[0-9]+$ ]] && { echo "$rows"; return; }
    fi
    rows="${LINES:-}"
    [[ "$rows" =~ ^[0-9]+$ ]] && { echo "$rows"; return; }
    tput lines 2>/dev/null || echo 40
}

repeat_char() {
    local ch="$1" n="$2" out=""
    while [[ ${#out} -lt $n ]]; do out="${out}${ch}"; done
    printf '%s' "${out:0:$n}"
}

# Emoji we use are single CODEPOINTS but render TWO display columns; bash counts
# them as one char. Everything else in the UI is single-width. Keep this list in
# sync with any emoji used in labels/values so widths compute correctly.
#
# REJECT defect 3 fix: ❔ (U+2754, badge_department's unknown-department
# fallback) and 📜 (U+1F4DC, department_motif_glyph's research fallback,
# reachable by ANY research-department specialist without a bespoke avatar
# — e.g. the "research" specialist itself) were both missing here despite
# both being genuinely EAW=W (verified via Python's
# unicodedata.east_asian_width(), the same ground-truth metric codex's
# review used), causing dwidth('[📜]') to undercount by 1 and overflow the
# card border by exactly 1 column at every width. The other candidates
# codex's review prompted auditing here (✹ ◎ ʘ ⚔ ⚙, used in the bespoke
# avatars and other department motifs) were independently verified EAW=N
# or EAW=A (narrow in this non-East-Asian-locale codebase) and correctly
# stay OUT of this list — adding a narrow glyph would introduce the exact
# opposite (overcounting) bug.
VS_WIDE='🟢🟡🔴⚪🟠🔵🟣🧑📋🔧⚡📥🕐👤📊🎯🛠🚦🧩🎬🖼🔊🤖🧠💎🌙🟦🟩🔶⏳⛔👀✅🔒🔬🎨📝💻🧭❔📜'

# Display width of a string, counting each VS_WIDE glyph as 2 columns.
dwidth() {
    local s="$1" g t
    local w=${#s}
    # Fast path: no wide glyph present → display width == char count.
    for g in 🟢 🟡 🔴 ⚪ 🟠 🔵 🟣 🧑 📋 🔧 ⚡ 📥 🕐 👤 📊 🎯 🛠 🚦 🧩 🎬 🖼 🔊 🤖 🧠 💎 🌙 🟦 🟩 🔶 ⏳ ⛔ 👀 ✅ 🔒 🔬 🎨 📝 💻 🧭 ❔ 📜; do
        [[ "$s" == *"$g"* ]] || continue
        t="${s//$g/}"
        w=$(( w + ${#s} - ${#t} ))   # each occurrence (1 char) adds 1 extra column
    done
    printf '%s' "$w"
}

# Fit text to a fixed DISPLAY width: pad with ASCII spaces when short, truncate
# with a single-width … when long. Width is measured with dwidth() so emoji and
# other multibyte glyphs never drift the right border or overflow (which wraps).
fit() {
    local text="$1" max="$2" dw
    dw=$(dwidth "$text")
    if (( dw <= max )); then
        printf '%s%*s' "$text" "$((max - dw))" ""
        return
    fi
    if (( max <= 1 )); then
        printf '%.*s' "$max" "$text"
        return
    fi
    # Walk chars, accumulating display width, stop leaving room for the … (1 col).
    local out="" i n=${#text} c cw acc=0 lim=$((max - 1))
    for ((i = 0; i < n; i++)); do
        c="${text:i:1}"
        cw=1; [[ "$VS_WIDE" == *"$c"* ]] && cw=2
        (( acc + cw > lim )) && break
        out="$out$c"; acc=$((acc + cw))
    done
    printf '%s…%*s' "$out" "$((max - acc - 1))" ""
}

# --- Fast per-lane data (from bin/vs-lane-snapshot.py) -----------------------
# The snapshot is gathered ONCE per frame into the global `snap` var (the frame
# builder is a $() subshell, which inherits it). Each card extracts its own block
# with awk — no bash-4 associative arrays, since macOS ships bash 3.2.
snap=""

# Echo one lane's snapshot block: its @LANE line plus its @WORK/@TASK/@LAST lines.
_lane_block() {  # _lane_block LANE
    printf '%s\n' "$snap" | awk -F'\t' -v L="$1" '
        $1=="@LANE" && $2==L {inb=1; print; next}
        $1=="@LANE" && inb {exit}
        inb {print}
    '
}

# Elapsed mm:ss from a start epoch (0 → --:--; caps mm at 99).
elapsed_mmss() {
    local start="$1"
    [[ "$start" =~ ^[0-9]+$ ]] && (( start > 0 )) || { printf '%s' '--:--'; return; }
    local e=$(( $(date +%s) - start )); (( e < 0 )) && e=0
    local m=$(( e / 60 )); (( m > 99 )) && m=99
    printf '%02d:%02d' "$m" "$(( e % 60 ))"
}

# A specialist row inside a card: "│ <glyph> <specialist> <mm:ss> │" with the
# time right-aligned. Glyph is single-width (● ◐ ○), so no width surprises.
fmt_member() {  # fmt_member WIDTH GLYPH_COLOR GLYPH SPECIALIST MMSS
    local width="$1" gc="$2" g="$3" spec="$4" mmss="$5"
    local sw=$(( width - 12 )); (( sw < 4 )) && sw=4
    printf '│ \033[%sm%s\033[0m %s \033[38;5;240m%s\033[0m │' "$gc" "$g" "$(fit "$spec" "$sw")" "$mmss"
}

# Per-model logo (2-column emoji) for the idle state. Registered in VS_WIDE.
runtime_logo() {
    case "$1" in
        gpt-codex) printf '🤖' ;;
        claude)    printf '🧠' ;;
        gemini)    printf '💎' ;;
        kimi)      printf '🌙' ;;
        *)         printf '●'  ;;
    esac
}

# --- Card dashboard v2 (Task 2.7): badges, crew names/avatars, notify-into-card ---
# Design brief: docs/design/2026-07-21-swarm-card-dashboard-design.md
# Crew mapping (operator-approved, content-lane 1615):
#   _state/v2-finalization-2026-07-21-crew/crew-mapping.md
# SQUAD_CARD_ANIMATION=off freezes all pulsing/frame-cycling (reduced-motion).
_card_animation_on() { [[ "${SQUAD_CARD_ANIMATION:-on}" != "off" ]]; }

# Model badge — design brief §1 exact legend.
badge_model() {
    case "$1" in
        claude)    printf '🟦' ;;
        gpt-codex) printf '🟩' ;;
        gemini)    printf '🔶' ;;
        kimi)      printf '🟣' ;;
        *)         printf '⬜' ;;
    esac
}

# Department badge — design brief §1 legend. Three of the brief's literal
# emoji (⚙️ coding, ✍️ content, 🖥️ sysmgmt) are base+U+FE0F variation-selector
# PAIRS that would silently break dwidth()/fit()'s single-codepoint glyph
# matching (verified: len('⚙️') == 2 codepoints, not 1) and misalign every
# card's right border. Substituted with single-codepoint equivalents that
# keep the same meaning — 🔧/📝/💻 — rather than teaching dwidth() a second,
# riskier multi-codepoint glyph-matching mode for a cosmetic swap.
badge_department() {
    case "$1" in
        security)          printf '🔒' ;;
        research)          printf '🔬' ;;
        coding)            printf '🔧' ;;
        content)           printf '📝' ;;
        sysmgmt)           printf '💻' ;;
        shared)            printf '🧭' ;;
        *)                 printf '❔' ;;
    esac
}

# A specialist's department, from the canonical brief's own frontmatter (the
# same file draw_card already trusts as the single source of role-truth).
specialist_department() {
    local spec="$1" f
    for f in "${VAULT_ROOT}"/departments/*/specialists/"${spec}".md; do
        [[ -f "$f" ]] || continue
        frontmatter_field "$f" department
        return 0
    done
    if [[ -f "${VAULT_ROOT}/shared/specialists/${spec}.md" ]]; then
        printf 'shared'
    fi
    return 0
}

# REJECT defect 1 fix: this used to scan outbox response files for
# status: needs_review bounded to a 24h mtime window — a heuristic, not a
# lifecycle signal. Nothing ever rewrites an outbox response's OWN
# frontmatter after its review actually settles elsewhere, so that scan
# could never observe a review resolving; it could only age out (a live
# scan against this repo found 33/29/2/3 pending Codex/Claude/Gemini/Kimi
# items, most of them long-settled). The live task registry
# (_state/active-tasks.json) IS rewritten by the real settle mechanism
# (registry_reconciler.py's --settle-review/--close-task): status stays
# "review-required" only while a review is genuinely still open. This is
# the one authoritative source now — no file, no mtime, no window.
#
# ACTIVE_TASKS_REGISTRY is a targeted, backward-compatible test seam
# (defaults to the real path when unset) — see scripts/python/tests/
# test_watch_lane_card.py's ReviewRequiredTests for hermetic fixtures.
ACTIVE_TASKS_REGISTRY="${ACTIVE_TASKS_REGISTRY:-${VAULT_ROOT}/_state/active-tasks.json}"
_registry_review_required_counts_all_lanes() {  # tab-separated: codex claude gemini kimi
    if [[ ! -f "$ACTIVE_TASKS_REGISTRY" ]]; then
        printf '0\t0\t0\t0\n'
        return
    fi
    /usr/bin/python3 - "$ACTIVE_TASKS_REGISTRY" <<'PYEOF'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        registry = json.load(handle)
except (OSError, json.JSONDecodeError):
    print("0\t0\t0\t0")
    sys.exit(0)

lanes = ("gpt-codex", "claude", "gemini", "kimi")
counts = {lane: 0 for lane in lanes}
if isinstance(registry, dict):
    for record in registry.values():
        if not isinstance(record, dict):
            continue
        if record.get("status") != "review-required":
            continue
        lane = record.get("to_model")
        if lane in counts:
            counts[lane] += 1
print("\t".join(str(counts[lane]) for lane in lanes))
PYEOF
}

review_required_count() {  # review_required_count LANE
    local lane="$1" line idx
    line="$(_registry_review_required_counts_all_lanes)"
    case "$lane" in
        gpt-codex) idx=1 ;; claude) idx=2 ;; gemini) idx=3 ;; kimi) idx=4 ;;
        *) echo 0; return ;;
    esac
    printf '%s\n' "$line" | cut -f"$idx"
}

# Measured live against this repo's real outbox tree (hundreds of response
# files): review_required_count()/settled_recently() cost ~2s EACH, per lane
# — spawning a stat+awk subprocess per candidate file. Called 4x per frame
# (once per lane) inside draw_card(), that is ~8s/frame against this
# codebase's own explicit ~0.02–0.04s/frame design goal (the very regression
# its comments say the batched Python snapshot was built to eliminate — see
# "Fast per-lane data snapshot... Replaces the old ~11s/frame per-card file
# scanning" above).
#
# A single pass (tag every file's lane once, not 4 redundant passes) plus a
# synchronous 5s TTL cache was tried first and MEASURED at ~5.4s for that one
# pass — still a visible once-per-TTL-window freeze, not a fix. The real fix,
# matching this codebase's own existing async-collector idiom
# (vs-lane-snapshot.py as a separate process, /tmp/vs-*.status files as the
# IPC surface) rather than reimplementing it (out of write scope): the scan
# runs in a DETACHED background subshell that writes to a temp file, and the
# render loop only ever does a fast, non-blocking read of whatever is
# currently on disk — never blocks on the scan itself, at the cost of the
# badge lagging by up to one TTL window (5s) after a real status change.
REVIEW_SNAP=""

# REJECT defect 4 fix: REVIEW_SNAP_FILE/REVIEW_SNAP_LOCK used to be fixed,
# predictable, world-writable-/tmp names (/tmp/vs-review-snapshot.tsv,
# .lock) — verified live: pre-creating "${REVIEW_SNAP_FILE}.tmp" as a
# symlink to a victim file let the background writer's `>` redirect follow
# it, overwriting the victim's real content. Fixed with three layers: (1) a
# private, mode-0700, per-uid+session+repo cache DIRECTORY, so another
# local user cannot even create a same-named entry inside it without
# already having write access; (2) verify ownership/type of that directory
# before trusting it (handles a directory that already existed); (3)
# mktemp for the actual write target (an unpredictable name closes the
# symlink-preplant window entirely) followed by mv/rename to the final
# name — rename() REPLACES whatever is at the destination, including a
# symlink, it never follows one the way `>` redirection does.
_repo_id="$(printf '%s' "$VAULT_ROOT" | shasum -a 256 2>/dev/null | cut -c1-16)"
[[ -z "$_repo_id" ]] && _repo_id="norepo"
REVIEW_CACHE_DIR="${TMPDIR:-/tmp}/vs-watch-lane.$(id -u).${SESSION}.${_repo_id}"
REVIEW_SNAP_FILE="${REVIEW_CACHE_DIR}/review-snapshot.tsv"
REVIEW_SNAP_LOCK="${REVIEW_CACHE_DIR}/review-snapshot.lockdir"

_ensure_private_cache_dir() {
    if [[ ! -e "$REVIEW_CACHE_DIR" ]]; then
        mkdir -m 700 "$REVIEW_CACHE_DIR" 2>/dev/null
    fi
    [[ -L "$REVIEW_CACHE_DIR" ]] && return 1
    [[ -d "$REVIEW_CACHE_DIR" ]] || return 1
    local owner perm
    owner=$(stat -f '%u' "$REVIEW_CACHE_DIR" 2>/dev/null) || return 1
    perm=$(stat -f '%Lp' "$REVIEW_CACHE_DIR" 2>/dev/null) || return 1
    [[ "$owner" == "$(id -u)" ]] || return 1
    [[ "$perm" == "700" ]] || return 1
    return 0
}

# Writes CONTENT to REVIEW_SNAP_FILE via mktemp + atomic rename inside the
# verified-private cache directory — never a fixed intermediate name.
_write_review_snapshot_safely() {  # _write_review_snapshot_safely CONTENT
    _ensure_private_cache_dir || return 1
    local tmp_snap
    tmp_snap="$(mktemp "${REVIEW_CACHE_DIR}/review-snapshot.XXXXXX" 2>/dev/null)" || return 1
    printf '%s' "$1" > "$tmp_snap"
    mv -f "$tmp_snap" "$REVIEW_SNAP_FILE"
}

_refresh_review_snapshot() {  # writes the TSV snapshot to stdout; caller redirects
    local f task_id task_file to_model ns d age now mtime lane
    local -a rc=(0 0 0 0) rs=(0 0 0 0)  # indices: gpt-codex claude gemini kimi
    now=$(date +%s)
    # rs[] (settled-recently): still sourced from outbox file mtime — a
    # fresh WRITE is a legitimate "just completed" signal on its own and
    # this half was never disputed by the review (only rc[]'s review-state
    # source was).
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/outbox"/TASK-*-response.md; do
            [[ -f "$f" ]] || continue
            mtime=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
            age=$(( now - mtime ))
            (( age > 90 )) && continue
            task_id="$(basename "$f" | sed 's/-response.md$//')"
            task_file=""
            for d in inbox active archive; do
                [[ -f "${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md" ]] && task_file="${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md"
            done
            lane=""
            [[ -n "$task_file" ]] && lane="$(frontmatter_field "$task_file" to_model)"
            [[ -z "$lane" ]] && continue
            local idx=-1
            case "$lane" in
                gpt-codex) idx=0 ;; claude) idx=1 ;; gemini) idx=2 ;; kimi) idx=3 ;;
            esac
            (( idx < 0 )) && continue
            rs[idx]=1
        done
    done
    # rc[] (review-required): the live registry — see
    # _registry_review_required_counts_all_lanes above (defect 1 fix).
    local reg_line a b c d
    reg_line="$(_registry_review_required_counts_all_lanes)"
    IFS=$'\t' read -r a b c d <<< "$reg_line"
    rc[0]="${a:-0}"; rc[1]="${b:-0}"; rc[2]="${c:-0}"; rc[3]="${d:-0}"
    printf 'gpt-codex\t%s\t%s\nclaude\t%s\t%s\ngemini\t%s\t%s\nkimi\t%s\t%s\n' \
        "${rc[0]}" "${rs[0]}" "${rc[1]}" "${rs[1]}" "${rc[2]}" "${rs[2]}" "${rc[3]}" "${rs[3]}"
}

# Non-blocking: kicks off a background refresh at most once every 5s (mutex
# via a lock DIRECTORY so a slow scan never overlaps itself), then does a
# fast read of whatever the last completed scan wrote. Never waits on the
# scan.
_maybe_refresh_review_snapshot() {
    local file_age now lock_age
    _ensure_private_cache_dir || { REVIEW_SNAP="$(cat "$REVIEW_SNAP_FILE" 2>/dev/null || true)"; return; }
    now=$(date +%s)
    if [[ -f "$REVIEW_SNAP_FILE" ]]; then
        file_age=$(( now - $(stat -f '%m' "$REVIEW_SNAP_FILE" 2>/dev/null || echo 0) ))
    else
        file_age=999999
    fi
    # Ownership/lease-bearing reclaim (REJECT defect 4's lock half): a
    # PRESENT owner.pid naming a dead process is genuinely abandoned and is
    # reclaimed immediately via a real liveness check, never guessed from
    # age alone. A lock dir with NO owner file yet is "busy, just acquired"
    # (the narrow window between mkdir() and the owner-file write below),
    # not stale — only a bounded age fallback reclaims THAT case, matching
    # the busy-vs-stale distinction already built (and mutation-tested)
    # this session in coordination.py and held_action_gate.py.
    if [[ -d "$REVIEW_SNAP_LOCK" ]]; then
        local owner_pid
        owner_pid="$(cat "${REVIEW_SNAP_LOCK}/owner.pid" 2>/dev/null)"
        if [[ "$owner_pid" =~ ^[0-9]+$ ]]; then
            if ! kill -0 "$owner_pid" 2>/dev/null; then
                rm -f "${REVIEW_SNAP_LOCK}/owner.pid" 2>/dev/null
                rmdir "$REVIEW_SNAP_LOCK" 2>/dev/null
            fi
        else
            lock_age=$(( now - $(stat -f '%m' "$REVIEW_SNAP_LOCK" 2>/dev/null || echo "$now") ))
            (( lock_age > 30 )) && rmdir "$REVIEW_SNAP_LOCK" 2>/dev/null
        fi
    fi
    if (( file_age >= 5 )) && [[ ! -d "$REVIEW_SNAP_LOCK" ]]; then
        (
            mkdir "$REVIEW_SNAP_LOCK" 2>/dev/null || exit 0
            printf '%s\n' "$$" > "${REVIEW_SNAP_LOCK}/owner.pid" 2>/dev/null
            content="$(_refresh_review_snapshot 2>/dev/null)"
            _write_review_snapshot_safely "$content"
            rm -f "${REVIEW_SNAP_LOCK}/owner.pid" 2>/dev/null
            rmdir "$REVIEW_SNAP_LOCK" 2>/dev/null
        ) &
        disown 2>/dev/null || true
    fi
    REVIEW_SNAP="$(cat "$REVIEW_SNAP_FILE" 2>/dev/null || true)"
}

_lane_review_count() {  # _lane_review_count LANE
    awk -F'\t' -v L="$1" '$1==L{print $2; found=1} END{if(!found) print 0}' <<< "$REVIEW_SNAP"
}

_lane_settled_recent() {  # _lane_settled_recent LANE  (prints 1|0)
    awk -F'\t' -v L="$1" '$1==L{print $3; found=1} END{if(!found) print 0}' <<< "$REVIEW_SNAP"
}

# True if this lane's newest outbox response settled within the last 90s —
# drives the brief ✅ "just completed" flash on an otherwise-idle card.
settled_recently() {
    local lane="$1" f task_id task_file to_model ts now best_ts=0 ns d
    now=$(date +%s)
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/outbox"/TASK-*-response.md; do
            [[ -f "$f" ]] || continue
            task_id="$(basename "$f" | sed 's/-response.md$//')"
            task_file=""
            for d in inbox active archive; do
                [[ -f "${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md" ]] && task_file="${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md"
            done
            [[ -z "$task_file" ]] && continue
            to_model="$(frontmatter_field "$task_file" to_model)"
            [[ "$to_model" != "$lane" ]] && continue
            ts=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
            (( ts > best_ts )) && best_ts=$ts
        done
    done
    (( best_ts > 0 && now - best_ts <= 90 ))
}

# The single combined status badge for a card face — notify-into-card: a
# pending review or a fresh settle reads on the card itself, so it survives
# even if a send-keys notification into the chrono pane was eaten/collided.
# Priority (design brief §1: "review-required / blocked never hides"):
#   review > blocked > running > queued > settled-flash > idle.
card_status_badge() {  # card_status_badge LANE STATE REVIEW_COUNT SETTLED_FLASH(0|1)
    local state="$2" review="$3" settled_flash="${4:-0}"
    if [[ "$review" =~ ^[0-9]+$ ]] && (( review > 0 )); then printf '👀'; return; fi
    case "$state" in
        blocked) printf '⛔'; return ;;
        running) printf '⚡'; return ;;
        queued)  printf '⏳'; return ;;
    esac
    # REJECT defect 2 fix: arg 4 used to be silently ignored here, so a
    # fresh settlement had NO card-visible effect (idle-flag-0 and
    # idle-flag-1 rendered byte-identical). A bounded settle-flash (the flag
    # itself already expires after 90s, computed upstream by
    # settled_recently()) now gets a visibly distinct bold/bright ✅ instead
    # of the dim/plain idle ✅ — same single glyph, same 2-column display
    # width (dwidth()/fit() never measure this string; the header row's pad
    # math already treats the badge as an opaque fixed-width value), so no
    # width regression, but a real, load-bearing visual difference.
    if [[ "$settled_flash" == "1" ]]; then
        printf '\033[1;38;5;46m✅\033[0m'
    else
        printf '✅'
    fi
}

# Bright/dim pulse for the running-state dot color, gated by tick parity.
# Frozen to the base color when SQUAD_CARD_ANIMATION=off.
dot_pulse_color() {  # dot_pulse_color BASE_256 TICK
    local base="$1" t="${2:-0}"
    if ! _card_animation_on; then printf '%s' "$base"; return; fi
    if (( t % 2 == 0 )); then printf '%s' "$base"; else printf '15'; fi
}

# Character name for the operator-approved anime crew (content-lane 1615,
# _state/v2-finalization-2026-07-21-crew/crew-mapping.md). 66/71 specialists
# are covered by that proposal; 5 were not (code-reviewer,
# growth-and-search-analyst, scraping-engineer, social-strategist,
# technical-writer) — those get an honest plain-role placeholder rather than
# an invented, never-reviewed anime name, per this task's own hard boundary
# ("if the anime-crew design isn't locatable, use stable placeholder... flag
# it"). Flagged in the return artifact as a follow-up for the content lane.
specialist_crew_name() {
    # Read the character name from the specialist's crew card (shared/cards/) — the
    # single source of truth (Fable Phase-7). The hardcoded case below is now a legacy
    # fallback only, kept until the Phase-8 dead-code pass.
    local _card="${VAULT_ROOT}/shared/cards/${1}.card"
    if [[ -f "$_card" ]]; then
        local _n; _n="$(awk -F': ' '/^name:/{print $2; exit}' "$_card")"
        [[ -n "$_n" ]] && { printf '%s' "$_n"; return; }
    fi
    case "$1" in
        security-analyst) printf 'Kento Nanami' ;;
        scout) printf 'Killua' ;;
        reverse-engineer) printf 'Sasuke' ;;
        exploit-developer) printf 'Sukuna' ;;
        threat-modeler) printf 'Shikamaru' ;;
        detection-engineer) printf 'Hawkeye' ;;
        incident-responder) printf 'Levi' ;;
        red-team-operator) printf 'Aizen' ;;
        experimental-attacker) printf 'Eren' ;;
        privacy-steward) printf 'Neji' ;;
        impact-validator) printf 'Erwin' ;;
        ai-engineer) printf 'Edward Elric' ;;
        architect) printf 'Alphonse Elric' ;;
        backend-engineer) printf 'Roy Mustang' ;;
        database-engineer) printf 'Alex Louis Armstrong' ;;
        devops-engineer) printf 'Winry' ;;
        frontend-engineer) printf 'Nobara' ;;
        game-engineer) printf 'Bertholdt' ;;
        performance-optimizer) printf 'Toshiro Hitsugaya' ;;
        product-manager) printf 'Armin' ;;
        refactor-cleaner) printf 'Scar' ;;
        site-reliability-engineer) printf 'Mikasa' ;;
        smart-contract-engineer) printf 'Ging Freecss' ;;
        software-supply-chain-engineer) printf 'Olivier Armstrong' ;;
        systems-engineer) printf 'Reiner' ;;
        technical-artist) printf 'Deidara' ;;
        test-engineer) printf 'Hange' ;;
        ui-engineer) printf 'Sasha' ;;
        web-builder) printf 'Sai' ;;
        bounty-researcher) printf 'Chrollo' ;;
        data-extraction-engineer) printf 'Shizuku' ;;
        large-context-analyst) printf 'Kurapika' ;;
        learning-coach) printf 'Biscuit' ;;
        research) printf 'Kite' ;;
        synthesizer) printf 'Meruem' ;;
        accessibility-engineer) printf 'Rock Lee' ;;
        asset-provenance-and-rights-auditor) printf 'Kurapika (Chain)' ;;
        brand-voice) printf 'Tsunade' ;;
        content-verifier) printf 'Kakashi' ;;
        copywriter) printf 'Jiraiya' ;;
        editor) printf 'Sakura' ;;
        game-designer) printf 'Orochimaru' ;;
        image-designer) printf 'Sai (Ink)' ;;
        interactive-audio-designer) printf 'Tayuya' ;;
        level-narrative-designer) printf 'Obito' ;;
        localization-specialist) printf 'Minato' ;;
        music-composer) printf 'Byakuya' ;;
        sound-designer) printf 'Chad' ;;
        voice-agent-builder) printf 'Konan' ;;
        voice-narrator) printf 'Mayuri' ;;
        video-director) printf 'Uryu' ;;
        video-editor) printf 'Itachi' ;;
        agentops) printf 'Geto' ;;
        finance-analyst) printf 'Mei Mei' ;;
        harness-optimizer) printf 'Atsuya' ;;
        knowledge-librarian) printf 'Shoko' ;;
        loop-operator) printf 'Toge' ;;
        mac-ops) printf 'Maki' ;;
        memory-curator) printf 'Megumi' ;;
        personal-ops) printf 'Yuji' ;;
        planner) printf 'Shunsui' ;;
        prompt-engineer) printf 'Urahara' ;;
        skeptic) printf 'Maes Hughes' ;;
        summarizer) printf 'Gon' ;;
        triage) printf 'Yuta' ;;
        vibecoding-check) printf 'Kenpachi' ;;
        # Not in the operator-approved crew-mapping proposal (5/71) — honest
        # plain-role placeholder, not a fabricated anime name. Flag for a
        # content-lane follow-up rather than blocking this mechanism.
        code-reviewer) printf 'Code Reviewer' ;;
        growth-and-search-analyst) printf 'Growth Analyst' ;;
        scraping-engineer) printf 'Scraper' ;;
        social-strategist) printf 'Social Strategist' ;;
        technical-writer) printf 'Technical Writer' ;;
        *) printf '' ;;
    esac
}

# A small 2-frame department motif (fallback for any specialist without a
# bespoke crew_banner below) — design brief §1's 6 department families.
department_motif_glyph() {  # department_motif_glyph DEPT FRAME
    local dept="$1" frame="$2"
    case "$dept" in
        security) [[ "$frame" == "1" ]] && printf '[⚔]' || printf '[⚔]' ;;
        coding) [[ "$frame" == "1" ]] && printf '{⚙}' || printf '(⚙)' ;;
        research) printf '[📜]' ;;
        content) printf '~≈~' ;;
        sysmgmt) [[ "$frame" == "1" ]] && printf '[--]' || printf '[==]' ;;
        shared) printf '<=>' ;;
        *) printf '(?)' ;;
    esac
}

# Compact 1-token avatar glyph for the member row (small-card real estate —
# design brief §2: "shows compactly on the card... full-size as the banner
# when you zoom"). The 4 fully-rendered crew_banner specialists get a
# recognizable glyph pulled from their own design; everything else falls
# back to its department motif — the design brief's own stated fallback rule.
specialist_avatar_glyph() {  # specialist_avatar_glyph SPECIALIST FRAME
    local spec="$1" frame="0"
    _card_animation_on && frame="${2:-0}"
    case "$spec" in
        exploit-developer) [[ "$frame" == "1" ]] && printf '(--)' || printf '(oo)' ;;
        reverse-engineer)  [[ "$frame" == "1" ]] && printf '(✹✹)' || printf '(◎◎)' ;;
        detection-engineer) [[ "$frame" == "1" ]] && printf '[🎯]' || printf '[ʘ]' ;;
        incident-responder) [[ "$frame" == "1" ]] && printf '[LV]' || printf '[lv]' ;;
        *) department_motif_glyph "$(specialist_department "$spec")" "$frame" ;;
    esac
}

# Full multi-line animated banner for the zoomed live-terminal view (design
# brief §2: "full-size as the banner when you zoom into the terminal"). Only
# the 4 crew-mapping "fully-rendered" examples get a bespoke banner; empty
# output means the caller should fall back to the department motif instead
# of inventing content for the other 67 (matching the design brief's own
# "a later content pass renders all 71" framing).
crew_banner() {  # crew_banner SPECIALIST FRAME — reads the avatar frame from shared/cards/
    local spec="$1" frame="0"
    _card_animation_on && frame="${2:-0}"
    local card="${VAULT_ROOT}/shared/cards/${spec}.card"
    [[ -f "$card" ]] || { printf ''; return; }   # no card -> caller falls back to motif
    local section="idle"
    [[ "$frame" == "1" ]] && section="active"
    # Emit the ASCII avatar between ---<section>--- and the next --- marker (or EOF).
    awk -v sec="---${section}---" '
        $0 == sec { grab = 1; next }
        grab && /^---/ { exit }
        grab { print }
    ' "$card"
}

# Idle "breathing" ramp — we animate COLOR only (same chars every frame), so it
# glows without ever changing widths or triggering a redraw artifact.
BREATHE=(236 237 238 239 240 241 242 241 240 239 238 237)

# A blank interior rail line: │ <spaces> │ in the accent color.
blank_row() {  # blank_row WIDTH ACCENT
    c256 "$2" "│"; printf '%*s' "$(( $1 - 2 ))" ""; c256 "$2" "│"
}

# A horizontally-centered interior line. CONTENT_DW is the display width of the
# content's visible glyphs (excluding ANSI), so centering stays exact.
fmt_center() {  # fmt_center WIDTH CONTENT_ANSI CONTENT_DW
    local width="$1" content="$2" cdw="$3"
    local inner=$(( width - 2 )) lp rp
    lp=$(( (inner - cdw) / 2 )); (( lp < 0 )) && lp=0
    rp=$(( inner - cdw - lp )); (( rp < 0 )) && rp=0
    printf '│%*s%s%*s│' "$lp" "" "$content" "$rp" ""
}

frontmatter_field() {
    local file="$1" field="$2"
    awk -v key="$field" '/^---$/{p=!p; next} p && index($0, key ":") == 1 {sub("^[^:]+:[[:space:]]*", ""); print; exit}' "$file"
}

count_lane_tasks() {
    local lane="$1" dir="$2" count=0 f to_model task_id response ns_for_response
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/${dir}"/TASK-*.md; do
            [[ -f "$f" ]] || continue
            if [[ "$dir" == "inbox" ]]; then
                task_id="$(basename "$f" .md)"
                response="${VAULT_ROOT}/departments/${ns}/outbox/${task_id}-response.md"
                [[ -f "$response" ]] && continue
            fi
            to_model="$(frontmatter_field "$f" to_model)"
            [[ "$to_model" == "$lane" ]] && count=$((count + 1))
        done
    done
    echo "$count"
}

latest_result() {
    local lane="$1" best="" best_ts=0 f ts ns to_model line task_id task_file d
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/outbox"/TASK-*-response.md; do
            [[ -f "$f" ]] || continue
            task_id="$(basename "$f" | sed 's/-response.md$//')"
            task_file=""
            for d in inbox active archive; do
                [[ -f "${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md" ]] && task_file="${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md"
            done
            if [[ -n "$task_file" ]]; then
                to_model="$(frontmatter_field "$task_file" to_model)"
                [[ "$to_model" != "$lane" ]] && continue
            fi
            ts=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
            if [[ "$ts" -gt "$best_ts" ]]; then
                best_ts="$ts"
                line=$(awk '/^---$/{c++; if(c==2){body=1; next}} body && /^# /{sub(/^# */,""); print; exit}' "$f")
                [[ -z "$line" ]] && line="$(basename "$f")"
                best="$line"
            fi
        done
    done
    echo "$best"
}

# Specialist of the lane's most recently completed task — gives idle lanes some
# specialist context ("who ran last") instead of going blank.
last_specialist() {
    local lane="$1" best_file="" best_ts=0 f ts ns to_model task_id task_file d
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/outbox"/TASK-*-response.md; do
            [[ -f "$f" ]] || continue
            task_id="$(basename "$f" | sed 's/-response.md$//')"
            task_file=""
            for d in inbox active archive; do
                [[ -f "${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md" ]] && task_file="${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md"
            done
            [[ -z "$task_file" ]] && continue
            to_model="$(frontmatter_field "$task_file" to_model)"
            [[ "$to_model" != "$lane" ]] && continue
            ts=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
            if [[ "$ts" -gt "$best_ts" ]]; then best_ts="$ts"; best_file="$task_file"; fi
        done
    done
    [[ -n "$best_file" ]] && frontmatter_field "$best_file" specialist
}

blocked_count() {
    local lane="$1" count=0 f task_id task_file to_model status ns d
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/outbox"/TASK-*-response.md; do
            [[ -f "$f" ]] || continue
            task_id="$(basename "$f" | sed 's/-response.md$//')"
            task_file=""
            for d in inbox active archive; do
                [[ -f "${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md" ]] && task_file="${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md"
            done
            if [[ -n "$task_file" ]]; then
                to_model="$(frontmatter_field "$task_file" to_model)"
                [[ "$to_model" != "$lane" ]] && continue
            fi
            status="$(frontmatter_field "$f" status)"
            echo "$status" | grep -qiE 'failed|error|blocked|needs_human' && count=$((count + 1))
        done
    done
    echo "$count"
}

# Tools a specialist is configured to use, from the 28-column runtime map
# (col 24 required_tools + col 25 preferred_tools), joined with ' · '.
# Empty when the specialist is unmapped or "none".
tools_for_specialist() {
    local spec="$1" row req pref out
    [[ -z "$spec" || "$spec" == "none" ]] && return 0
    row=$(awk -F'\t' -v s="$spec" '$1==s{print; exit}' "${VAULT_ROOT}/shared/specialist-runtime-map.tsv" 2>/dev/null)
    [[ -z "$row" ]] && return 0
    req=$(printf '%s' "$row" | cut -f24)
    pref=$(printf '%s' "$row" | cut -f25)
    out="$req"
    [[ -n "$pref" && "$pref" != "none" ]] && out="${out:+${out},}${pref}"
    printf '%s' "${out//,/ · }"
}

# Path of the newest task packet routed to this lane, searching the given dirs
# in order (active/ first, then inbox/ — so a queued PENDING task still resolves).
_newest_lane_task() {  # _newest_lane_task LANE DIR...
    local lane="$1"; shift
    local dir ns f to_model ts best="" best_ts=0
    for dir in "$@"; do
        for ns in "${SOURCE_NAMESPACES[@]}"; do
            for f in "${VAULT_ROOT}/departments/${ns}/${dir}"/TASK-*.md; do
                [[ -f "$f" ]] || continue
                to_model="$(frontmatter_field "$f" to_model)"
                [[ "$to_model" != "$lane" ]] && continue
                ts=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
                if [[ "$ts" -gt "$best_ts" ]]; then best_ts="$ts"; best="$f"; fi
            done
        done
    done
    printf '%s' "$best"
}

# Specialist assigned to the lane's current (active, else queued) task.
lane_specialist() {
    local f; f="$(_newest_lane_task "$1" active inbox)"
    [[ -z "$f" ]] && return 0
    frontmatter_field "$f" specialist
}

# H1 title of the lane's current (active, else queued) task — a short
# natural-language "what is this lane working on". Empty if none.
active_task_objective() {
    local f; f="$(_newest_lane_task "$1" active inbox)"
    [[ -z "$f" ]] && return 0
    awk '/^---$/{c++; next} c>=2 && /^# /{sub(/^# */,""); print; exit}' "$f"
}

# Best-effort "what is the lane doing right now": scrape the pane, find the most
# recent activity marker (Claude ✻ / ⏺, Codex "Working/Worked for"), clean the
# line and return it. Empty when no marker is visible — we never guess, so the
# caller simply omits the line. Deliberately CLI-agnostic (approach A).
live_now_line() {
    local lane="$1" raw line
    command -v tmux >/dev/null 2>&1 || return 0
    raw=$(tmux capture-pane -t "${SESSION}:${lane}" -p 2>/dev/null) || return 0
    line=$(printf '%s\n' "$raw" | grep -nE '✻|⏺|─ Work(ing|ed) for' | tail -1 | cut -d: -f2-)
    [[ -z "$line" ]] && return 0
    # Strip ANSI, box-drawing chars, and leading spinner/prompt glyphs; collapse.
    line=$(printf '%s' "$line" \
        | sed -E $'s/\033\\[[0-9;]*m//g' \
        | tr -d '─│╭╮╰╯▄▀' \
        | sed -E 's/^[[:space:]✻⏺❯›▸*•]+//; s/[[:space:]]+/ /g; s/^ //; s/ $//')
    printf '%s' "$line"
}

# One labeled interior line, echoed (not printed) so the caller can collect rows
# into an array and count them for height-fill. Value is fit/truncated to width.
fmt_row() {  # fmt_row INNER LABEL VALUE
    local inner="$1" label="$2" value="$3"
    printf '│ \033[38;5;250m%-5s\033[0m %s │' "$label" "$(fit "$value" "$((inner - 6))")"
}

# Full-width state-colored line (used for the idle tagline row).
fmt_tagline() {  # fmt_tagline INNER STATE_COLOR TEXT
    local inner="$1" sc="$2" text="$3"
    printf '│ \033[%sm%s\033[0m │' "$sc" "$(fit "$text" "$inner")"
}

# Emoji-labeled row: "│ <emoji> <value> │". Our label emojis are single-codepoint
# but render TWO display columns, so we fit the value to width-7 (interior width-2
# minus: leading space, emoji=2 cols, space, trailing space) to keep the right
# rail aligned. Value must be single-width text (no emoji) — it's padded by chars.
fmt_erow() {  # fmt_erow WIDTH EMOJI VALUE
    local width="$1" emoji="$2" value="$3"
    printf '│ %s %s │' "$emoji" "$(fit "$value" "$((width - 7))")"
}

draw_card() {
    local lane="$1" width="$2" height="${3:-0}"
    local accent short state='idle' started='0' task='' last=''
    local -a members=()
    accent="$(runtime_accent_color "$lane")"
    short="$(runtime_short_name "$lane")"

    # Parse this lane's snapshot block in one pass (no assoc arrays — bash 3.2).
    local t a b c
    while IFS=$'\t' read -r t a b c; do
        case "$t" in
            @LANE) [[ -n "$b" ]] && state="$b"; started="$c" ;;
            @WORK) members+=("${a}"$'\t'"${b}"$'\t'"${c}") ;;
            @TASK) task="$a" ;;
            @LAST) last="${a}"$'\t'"${b}" ;;
        esac
    done < <(_lane_block "$lane")

    # State → header dot color + lowercase labels. The dot is a single-width ●,
    # pulsing bright/dim on tick parity while running (design brief §3).
    local dot_color state_lc name_lc review_ct settled_flag status_badge model_badge
    review_ct="$(_lane_review_count "$lane")"
    settled_flag="$(_lane_settled_recent "$lane")"
    status_badge="$(card_status_badge "$lane" "$state" "$review_ct" "$settled_flag")"
    model_badge="$(badge_model "$lane")"
    case "$state" in
        running) dot_color="38;5;$(dot_pulse_color 118 "${tick:-0}")"; state_lc='running' ;;
        queued)  dot_color='38;5;214'; state_lc='queued' ;;
        blocked) dot_color='38;5;167'; state_lc='blocked' ;;
        *)       dot_color='38;5;240'; state_lc='idle' ;;
    esac
    name_lc=$(printf '%s' "$short" | tr '[:upper:]' '[:lower:]')

    # Body: working lanes list their specialist SUBAGENTS + task; idle lanes show
    # what ran last. No static tagline — the card shows real work.
    local -a body=()
    if [[ "$state" == "running" || "$state" == "queued" ]]; then
        local m spec st s_ep mg mgc dept avatar cname label
        if (( ${#members[@]} > 0 )); then
            for m in "${members[@]}"; do
                IFS=$'\t' read -r spec st s_ep <<< "$m"
                [[ -z "$spec" ]] && continue
                case "$st" in
                    running) mg='●'; mgc='38;5;118' ;;
                    queued)  mg='◐'; mgc='38;5;214' ;;
                    *)       mg='○'; mgc='38;5;240' ;;
                esac
                # Triple-coherence crew label: avatar glyph + character name +
                # role slug (design brief §2). Falls back to the plain role
                # slug alone if the specialist has no crew-mapping entry.
                dept="$(specialist_department "$spec")"
                avatar="$(specialist_avatar_glyph "$spec" "${tick:-0}")"
                cname="$(specialist_crew_name "$spec")"
                if [[ -n "$cname" ]]; then
                    label="$(badge_department "$dept") ${avatar} ${cname} · ${spec}"
                else
                    label="$spec"
                fi
                body+=("$(fmt_member "$width" "$mgc" "$mg" "$label" "$(elapsed_mmss "$s_ep")")")
            done
        fi
        [[ -n "$task" ]] && body+=("$(fmt_erow "$width" 📋 "$task")")
        (( ${#body[@]} == 0 )) && body+=("$(fmt_erow "$width" ⚡ "working…")")
    else
        # Idle: last work at top, then a per-model logo + a subtly breathing
        # "ready" centered in the card, so idle lanes aren't a blank void.
        if [[ -n "${last//$'\t'/}" ]]; then
            local lspec ltitle
            IFS=$'\t' read -r lspec ltitle <<< "$last"
            body+=("$(fmt_erow "$width" 🕐 "${lspec}${ltitle:+ · $ltitle}")")
        else
            body+=("$(fmt_erow "$width" 🕐 "no recent work")")
        fi
        if (( height > 6 )); then
            local rem=$(( height - 3 )) top bot k bc aline
            bc="${BREATHE[$(( ${tick:-0} % ${#BREATHE[@]} ))]}"
            # Anime crew avatar (from shared/cards/) for this lane's specialist, instead
            # of a bare model emoji. Falls back to the model logo if there is no card.
            local avatar; avatar="$(crew_banner "${lspec:-}" "$(( ${tick:-0} % 2 ))")"
            if [[ -n "$avatar" ]]; then
                local alines=()
                while IFS= read -r aline; do alines+=("$aline"); done <<< "$avatar"
                local ah=${#alines[@]}
                top=$(( (rem - ah) / 2 )); (( top < 0 )) && top=0
                bot=$(( rem - ah - top )); (( bot < 0 )) && bot=0
                for ((k = 0; k < top; k++)); do body+=("$(blank_row "$width" "$accent")"); done
                for aline in "${alines[@]}"; do
                    body+=("$(fmt_center "$width" "$(printf '\033[38;5;%sm%s\033[0m' "$accent" "$aline")" "$(dwidth "$aline")")")
                done
                for ((k = 0; k < bot; k++)); do body+=("$(blank_row "$width" "$accent")"); done
            else
                local logo; logo="$(runtime_logo "$lane")"
                top=$(( (rem - 2) / 2 )); (( top < 0 )) && top=0
                bot=$(( rem - 2 - top )); (( bot < 0 )) && bot=0
                for ((k = 0; k < top; k++)); do body+=("$(blank_row "$width" "$accent")"); done
                body+=("$(fmt_center "$width" "$(printf '\033[1;38;5;%sm%s\033[0m' "$accent" "$logo")" 2)")
                body+=("$(fmt_center "$width" "$(printf '\033[38;5;%sm%s\033[0m' "$bc" "ready")" 5)")
                for ((k = 0; k < bot; k++)); do body+=("$(blank_row "$width" "$accent")"); done
            fi
        fi
    fi

    # Top border: ╭ ● 🟦 <lane name> · 👀 <state (dim)> <fill> ╮  (● = state
    # color; the two badges are single-codepoint, +2 display columns each —
    # registered in VS_WIDE — accounted for as fixed +6 in the pad math since
    # this line is built by hand, not through fit()/dwidth()).
    local hpad=$(( width - 15 - ${#name_lc} - ${#state_lc} ))
    [[ "$hpad" -lt 1 ]] && hpad=1
    c256 "$accent" "╭ "
    printf '\033[%sm●\033[0m ' "$dot_color"
    printf '%s ' "$model_badge"
    printf '\033[1;38;5;%sm%s\033[0m' "$accent" "$name_lc"
    printf '\033[38;5;240m · \033[0m%s ' "$status_badge"
    printf '\033[38;5;240m%s \033[0m' "$state_lc"
    c256 "$accent" "$(repeat_char '─' "$hpad")╮"
    printf '\n'

    # Body rows.
    printf '%s\n' "${body[@]}"

    # Fill to target height: box = 1 (top) + #body + 1 (bottom). Pad the interior
    # with accent-tinted blank rails so cards keep an equal slice of the sidebar.
    local total=$(( ${#body[@]} + 2 ))
    if [[ "$height" -gt "$total" ]]; then
        local i
        for ((i = 0; i < height - total; i++)); do
            c256 "$accent" "│"
            printf '%*s' "$((width - 2))" ""
            c256 "$accent" "│"
            printf '\n'
        done
    fi

    # Bottom border.
    c256 "$accent" "╰$(repeat_char '─' "$((width - 2))")╯"
    printf '\n'
}

draw_compact_card() {
    local lane="$1" width="$2"
    local accent short inbox active outbox blocked specialist last state state_color line max_last rule
    accent="$(runtime_accent_color "$lane")"
    short="$(runtime_short_name "$lane")"
    inbox=$(count_lane_tasks "$lane" inbox)
    active=$(count_lane_tasks "$lane" active)
    outbox=$(count_lane_tasks "$lane" outbox)
    blocked=$(blocked_count "$lane")
    specialist="$(lane_specialist "$lane")"
    last="$(latest_result "$lane")"

    if [[ "$active" -gt 0 ]]; then
        state="WORK"; state_color="38;5;118"
    elif [[ "$inbox" -gt 0 ]]; then
        state="PEND"; state_color="38;5;214"
    elif [[ "$blocked" -gt 0 ]]; then
        state="BLCK"; state_color="38;5;203"
    else
        state="IDLE"; state_color="38;5;245"
    fi

    max_last=$((width - 30))
    [[ "$max_last" -lt 8 ]] && max_last=8
    rule="$(repeat_char '─' "$width")"
    c256 "$accent" "$rule"
    printf '\n'
    printf '\033[38;5;%sm●\033[0m ' "$accent"
    printf '\033[1;38;5;%sm%-6s\033[0m ' "$accent" "$short"
    color "$state_color" "$(fit "$state" 4)"
    printf ' q:%s/%s b:%s ' "$inbox" "$active" "$blocked"
    line="${specialist:-none}"
    color "38;5;250" "$(fit "$line" "$max_last")"
    printf '\n'
    printf '  '
    color "38;5;245" "last "
    color "38;5;250" "$(fit "${last:-none}" "$((width - 7))")"
    printf '\n'
}

# In-place live preview of a lane's actual CLI output (read-only). Shown when a
# card is single-clicked (focus file set). The header doubles as the "◀ back"
# affordance — any single click while previewing returns to the cards.
render_preview() {
    local lane="$1" width="$2" rows="$3" accent line n
    accent="$(runtime_accent_color "$lane")"
    printf '\033[1;38;5;%sm ◀ back \033[0m' "$accent"
    color "38;5;240" "· "
    printf '\033[1;38;5;%sm%s\033[0m ' "$accent" "$lane"
    color "38;5;240" "· live  (click to close · dbl-click to open)"
    printf '\n'
    c256 "$accent" "$(repeat_char '─' "$width")"
    printf '\n'

    # Full-size crew banner (design brief §2: "full-size as the banner when
    # you zoom into the terminal"). Only the 4 crew-mapping "fully-rendered"
    # specialists get a bespoke banner; anything else shows a 1-line
    # department motif instead of inventing content for the other 67.
    local spec cname banner banner_lines=0
    spec="$(lane_specialist "$lane")"
    if [[ -n "$spec" ]]; then
        banner="$(crew_banner "$spec" "${tick:-0}")"
        if [[ -z "$banner" ]]; then
            cname="$(specialist_crew_name "$spec")"
            banner="$(department_motif_glyph "$(specialist_department "$spec")" "${tick:-0}") ${cname:-$spec}"
        fi
        if [[ -n "$banner" ]]; then
            color "38;5;245" " ${spec}"
            printf '\n'
            printf '\033[1;38;5;%sm%s\033[0m\n' "$accent" "$banner"
            banner_lines=$(( $(printf '%s\n' "$banner" | wc -l) + 1 ))
        fi
    fi

    n=$(( rows - 2 - banner_lines )); (( n < 1 )) && n=1
    tmux capture-pane -t "${SESSION}:${lane}" -p 2>/dev/null | tail -n "$n" | while IFS= read -r line; do
        printf '%s\n' "$(fit "$line" "$width")"
    done
}

# WATCH_LANE_TEST_MODE=1 sources this file for its function definitions only
# (used by scripts/python/tests/test_watch_lane_card.py) and skips the
# infinite render loop below, which would otherwise hang a sourcing shell.
if [[ "${WATCH_LANE_TEST_MODE:-0}" == "1" ]]; then
    return 0 2>/dev/null || exit 0
fi

trap 'show_cursor; printf "\n"; exit 0' INT TERM EXIT
hide_cursor
printf '\033[2J'

tick=0
while true; do
    tick=$((tick + 1))
    cols=$(pane_cols)
    rows=$(pane_rows)
    # Never render wider than the pane, or lines wrap into a garbled mess. Only
    # cap DOWN (readability max 78); a narrow pane just gets narrow cards.
    width=$((cols - 1))
    [[ "$width" -gt 78 ]] && width=78
    [[ "$width" -lt 1 ]] && width=1

    # A single click on a card writes a lane name here (double-click clears it and
    # jumps to the window); when set, render an in-place live preview of that lane.
    focus=""
    [[ -f /tmp/vs-sidebar-focus ]] && focus="$(cat /tmp/vs-sidebar-focus 2>/dev/null || true)"

    # Fast per-lane data snapshot (~0.02–0.04s), parsed into the LANE_* arrays that
    # draw_card reads. Replaces the old ~11s/frame per-card file scanning. Run in
    # the parent so the frame subshell below inherits the arrays.
    if [[ -z "$focus" ]]; then
        snap="$(VAULT_ROOT="$VAULT_ROOT" /usr/bin/python3 "${VAULT_ROOT}/bin/vs-lane-snapshot.py" 2>/dev/null)"
        # notify-into-card review/settled state — TTL-gated (5s), one pass for
        # all lanes, populated into REVIEW_SNAP for draw_card to read. See the
        # perf note on _refresh_review_snapshot above for why this is batched
        # and cached rather than called per-lane per-frame.
        _maybe_refresh_review_snapshot
    fi

    # Build the ENTIRE frame in memory, then paint once: home, each line + \033[K
    # (clear to EOL — no horizontal residue), newline BETWEEN lines only (no
    # trailing newline → no scroll → no doubled headers), then \033[J (clear
    # everything below). No per-frame full clear = no flicker; correct on resize.
    frame="$(
        if [[ -n "$focus" && "$LANE" == "all" ]]; then
            render_preview "$focus" "$width" "$rows"
        elif [[ "$LANE" == "all" ]]; then
            printf '\033[48;5;236;38;5;45;1m MODEL LANES \033[0m  '
            color "38;5;245" "scroll · click a lane · dbl-click opens it"
            printf '\n\n'
            card_h=$(( (rows - 8) / 4 ))
            [[ "$card_h" -lt 7 ]] && card_h=7
            _n=${#MODEL_LANES[@]}; _i=0
            for lane in "${MODEL_LANES[@]}"; do
                _i=$((_i + 1))
                draw_card "$lane" "$width" "$card_h"
                [[ "$_i" -lt "$_n" ]] && printf '\n'
            done
        else
            draw_card "$LANE" "$width"
        fi
    )"

    printf '\033[H'
    _first=1; _li=0
    while IFS= read -r _line; do
        (( _li >= rows )) && break
        (( _first )) || printf '\n'
        printf '%s\033[K' "$_line"
        _first=0; _li=$((_li + 1))
    done <<< "$frame"
    printf '\033[J'

    # ~0.5s cadence: fast enough for the idle "breathing" animation, and still
    # snappy for clicks (we poll the focus file every 0.25s and redraw early if it
    # changed). The snapshot's outbox scan is TTL-cached, so a 0.5s tick is cheap.
    _fmt=$(stat -f '%m' /tmp/vs-sidebar-focus 2>/dev/null || echo 0)
    for _ in 1 2; do
        sleep 0.25
        [[ "$(stat -f '%m' /tmp/vs-sidebar-focus 2>/dev/null || echo 0)" != "$_fmt" ]] && break
    done
done
