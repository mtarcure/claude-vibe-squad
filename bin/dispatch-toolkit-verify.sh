#!/bin/bash
# bin/dispatch-toolkit-verify.sh — per-pane MCP consistency check.
#
# For each Lead pane, parse the "MCPs verified installed in this pane" block
# from shared/dispatch-toolkit.sh, then ask the pane's CLI what's actually
# installed via `<cli> mcp list`. Warn on enumerated-but-not-installed
# mismatches. Config-consistency check, NOT a runtime probe.
#
# Routing-reminder prose (which mentions other Leads' MCPs by name to direct
# handoffs) is intentionally outside the verified-installed block and is NOT
# checked.
#
# Usage:  bash bin/dispatch-toolkit-verify.sh
# Exits 0 if all per-pane enumerations match install state; non-zero otherwise.
#
# Bash 3.2-compatible (macOS default). Uses parallel arrays, not associative.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
TOOLKIT="${VAULT_ROOT}/shared/dispatch-toolkit.sh"

if [ ! -f "$TOOLKIT" ]; then
    echo "ERROR: dispatch-toolkit.sh not found at $TOOLKIT"
    exit 2
fi

# Parallel arrays — bash 3.2 has no associative arrays
PANES=(coding security content sysmgmt research)
CLIS=(codex   claude   gemini  claude  kimi)
# (chrono pane is the Coordinator and doesn't receive a toolkit injection;
# it routes work TO the Leads. Verifier only checks the 5 dispatched-to panes.)

# Recognized MCP token regex (extend as the squad adds tools)
MCP_REGEX='chrono-vault|chrono-kg|chrono-obsidian|chrono-catalog|chrono-research-arsenal|chrono-content-engineer|playwright|chrome-devtools|context7|sequential-thinking|perplexity|elevenlabs|figma|firebase|sentry|linear|stitch'

mcp_list_for_cli() {
    local cli="$1"
    case "$cli" in
        gemini)
            # gemini's `mcp list` requires -d to print AND writes the list
            # to stderr (not stdout). Merge both streams to capture it.
            # The "Connected/Disconnected" status reflects a runtime probe
            # at list-time; we only care about configured names here.
            env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
                "$cli" mcp list -d 2>&1
            ;;
        *)
            env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
                "$cli" mcp list 2>/dev/null
            ;;
    esac
}

# Extract enumerated MCPs from the "MCPs verified installed in this pane"
# block of a Lead's case branch. Block ends at the next blank line OR the
# next bold-header line (`**...:**`).
extract_enumerated_mcps() {
    local pane="$1"
    awk -v pane="$pane" '
        # Track entry into the pane case branch
        $0 ~ "^    " pane "\\)$" { in_pane = 1; next }
        in_pane && /^        ;;$/ { in_pane = 0; next }
        # Within the pane block, track entry into the verified-installed sub-block
        in_pane && /MCPs verified installed in this pane/ { in_block = 1; next }
        # Sub-block ends on blank line or next bold header
        in_block && /^$/ { in_block = 0; next }
        in_block && /^\*\*[A-Z][^:]*:\*\*/ { in_block = 0; next }
        in_block { print }
    ' "$TOOLKIT" | grep -oE "$MCP_REGEX" | sort -u
}

extract_installed_mcps() {
    local cli="$1"
    mcp_list_for_cli "$cli" | grep -oE "$MCP_REGEX" | sort -u
}

WARN_COUNT=0
TOTAL_PANES=${#PANES[@]}

echo "Per-pane dispatch-toolkit MCP consistency check"
echo "================================================"
echo

i=0
while [ "$i" -lt "$TOTAL_PANES" ]; do
    pane="${PANES[$i]}"
    cli="${CLIS[$i]}"
    echo "[$pane] cli=$cli"

    enumerated="$(extract_enumerated_mcps "$pane")"
    installed="$(extract_installed_mcps "$cli")"

    if [ -z "$enumerated" ]; then
        echo "  WARN: $pane pane has no MCPs enumerated in dispatch-toolkit.sh installed-block"
        WARN_COUNT=$((WARN_COUNT + 1))
        echo
        i=$((i + 1))
        continue
    fi

    pane_warns=0
    for mcp in $enumerated; do
        if ! echo "$installed" | grep -q "^${mcp}$"; then
            echo "  WARN: $pane enumerates '$mcp' but it's not installed in $cli"
            WARN_COUNT=$((WARN_COUNT + 1))
            pane_warns=$((pane_warns + 1))
        fi
    done

    if [ "$pane_warns" -eq 0 ]; then
        n=$(echo "$enumerated" | wc -l | tr -d ' ')
        echo "  OK: $n enumerated MCPs all match install state"
    fi
    echo
    i=$((i + 1))
done

echo "================================================"
if [ "$WARN_COUNT" -eq 0 ]; then
    echo "PASS: all per-pane MCP enumerations verified across $TOTAL_PANES panes."
    exit 0
else
    echo "FAIL: $WARN_COUNT mismatch(es) found. Fix dispatch-toolkit.sh OR install missing MCPs."
    exit 1
fi
