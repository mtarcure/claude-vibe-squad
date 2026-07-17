#!/bin/bash
# bin/dispatch-toolkit-verify.sh — per-pane MCP consistency check.
#
# For each model lane, parse the "Expected Model Lane Tool Surface" block from
# shared/dispatch-toolkit.sh, then ask the CLI what's actually installed via
# `<cli> mcp list`. Warn on enumerated-but-not-installed mismatches.
# Config-consistency check, NOT a runtime probe.
#
# Routing-reminder prose is intentionally outside the expected-surface block and
# is NOT checked.
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
LANES=(gpt-codex claude gemini kimi)
CLIS=(codex     claude gemini kimi)
# (chrono pane is the Coordinator and doesn't receive a toolkit injection.)

# Recognized MCP token regex (extend as the squad adds tools)
MCP_REGEX='chrono-vault|chrono-kg|chrono-obsidian|chrono-catalog|chrono-research-arsenal|chrono-media-studio|playwright|chrome-devtools|context7|sequential-thinking|perplexity|elevenlabs|figma|firebase|sentry|linear|stitch'

mcp_list_for_cli() {
    local cli="$1"
    case "$cli" in
        claude)
            for file in "${HOME}/.claude/settings.json" "${VAULT_ROOT}/.claude/settings.json"; do
                [[ -f "$file" ]] || continue
                if command -v jq >/dev/null 2>&1; then
                    jq -r '.. | objects | .mcpServers? // empty | keys[]' "$file" 2>/dev/null || true
                else
                    grep -Eo '"chrono-[^"]+|context7|sequential-thinking"' "$file" | tr -d '"' || true
                fi
            done
            ;;
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

mcp_list_for_cli_with_timeout() {
    local cli="$1"
    local tmp="${TMPDIR:-/tmp}/dispatch-toolkit-verify-${cli}-$$.txt"
    : > "$tmp"
    mcp_list_for_cli "$cli" > "$tmp" 2>&1 &
    local pid=$!
    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$waited" -ge 8 ]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
            cat "$tmp"
            rm -f "$tmp"
            return 124
        fi
        sleep 1
        waited=$((waited + 1))
    done
    wait "$pid" 2>/dev/null || true
    cat "$tmp"
    rm -f "$tmp"
    return 0
}

# Extract enumerated MCPs from the "Expected Model Lane Tool Surface"
# block of a to_model case branch.
extract_enumerated_mcps() {
    local lane="$1"
    awk -v lane="$lane" '
        $0 ~ "^    " lane "\\)$" { in_lane = 1; next }
        in_lane && /^        ;;$/ { in_lane = 0; next }
        in_lane && /Expected Model Lane Tool Surface/ { in_block = 1; seen = 0; next }
        # Sub-block ends on blank line after content or next bold header.
        in_block && /^$/ && seen { in_block = 0; next }
        in_block && /^$/ { next }
        in_block && /^\*\*[A-Z][^:]*:\*\*/ { in_block = 0; next }
        in_block { seen = 1; print }
    ' "$TOOLKIT" | grep -oE "$MCP_REGEX" | sort -u
}

extract_installed_mcps() {
    local cli="$1"
    mcp_list_for_cli_with_timeout "$cli" | grep -oE "$MCP_REGEX" | sort -u
}

WARN_COUNT=0
TOTAL_LANES=${#LANES[@]}

echo "Per-model-lane dispatch-toolkit MCP consistency check"
echo "================================================"
echo

i=0
while [ "$i" -lt "$TOTAL_LANES" ]; do
    lane="${LANES[$i]}"
    cli="${CLIS[$i]}"
    echo "[$lane] cli=$cli"

    enumerated="$(extract_enumerated_mcps "$lane")"
    installed="$(extract_installed_mcps "$cli")"

    if [ -z "$enumerated" ]; then
        echo "  WARN: $lane has no MCPs enumerated in dispatch-toolkit.sh expected surface"
        WARN_COUNT=$((WARN_COUNT + 1))
        echo
        i=$((i + 1))
        continue
    fi

    pane_warns=0
    for mcp in $enumerated; do
        if ! echo "$installed" | grep -q "^${mcp}$"; then
            echo "  WARN: $lane expects '$mcp' but it was not listed by $cli"
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
    echo "PASS: all expected MCP enumerations verified across $TOTAL_LANES model lanes."
    exit 0
else
    echo "FAIL: $WARN_COUNT mismatch(es) found. Fix dispatch-toolkit.sh OR install missing MCPs."
    exit 1
fi
