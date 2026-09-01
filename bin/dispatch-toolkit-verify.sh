#!/bin/bash
# bin/dispatch-toolkit-verify.sh — per-pane MCP consistency check.
#
# For each model lane, parse the "Expected Model Lane Tool Surface" block from
# shared/dispatch-toolkit.sh, then ask the CLI what's actually installed via
# the lane's native inventory command. Fail on expected-but-missing or
# unexpected-installed mismatches, except Grok's explicitly global inventory;
# refuse to claim a match when either surface cannot be measured.
# Config-consistency check, NOT a runtime probe.
#
# Routing-reminder prose is intentionally outside the expected-surface block and
# is NOT checked.
#
# Usage:  bash bin/dispatch-toolkit-verify.sh
# Exits 0 for an exact match, 1 for a mismatch, and 2 when comparison could not
# be completed.
#
# Bash 3.2-compatible (macOS default). Uses parallel arrays, not associative.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
TOOLKIT="${DISPATCH_TOOLKIT_UNDER_TEST:-${VAULT_ROOT}/shared/dispatch-toolkit.sh}"

if [ ! -f "$TOOLKIT" ]; then
    echo "ERROR: dispatch-toolkit.sh not found at $TOOLKIT"
    exit 2
fi

# Parallel arrays — bash 3.2 has no associative arrays
LANES=(gpt-codex claude gemini grok kimi)
CLIS=(codex     claude gemini grok kimi)
# (chrono pane is the Coordinator and doesn't receive a toolkit injection.)

mcp_list_for_cli() {
    local cli="$1"
    if [[ -n "${DISPATCH_TOOLKIT_MCP_LIST_DIR_UNDER_TEST:-}" ]]; then
        local fixture="${DISPATCH_TOOLKIT_MCP_LIST_DIR_UNDER_TEST}/${cli}.txt"
        [[ -f "$fixture" ]] || return 66
        cat "$fixture"
        return 0
    fi
    case "$cli" in
        claude)
            env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
                "$cli" mcp list 2>&1
            ;;
        codex)
            env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
                "$cli" mcp list --json 2>/dev/null
            ;;
        gemini)
            # gemini's `mcp list` requires -d to print AND writes the list
            # to stderr (not stdout). Merge both streams to capture it.
            # The "Connected/Disconnected" status reflects a runtime probe
            # at list-time; we only care about configured names here.
            env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
                "$cli" mcp list -d 2>&1
            ;;
        grok)
            env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
                "$cli" inspect 2>&1
            ;;
        *)
            env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
                "$cli" mcp list 2>/dev/null
            ;;
    esac
}

mcp_list_for_cli_with_timeout() {
    local cli="$1"
    local tmp="" rc=0
    tmp="$(mktemp "${TMPDIR:-/tmp}/dispatch-toolkit-verify-${cli}.XXXXXXXX")" || return 70
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
    wait "$pid" 2>/dev/null || rc=$?
    cat "$tmp"
    rm -f "$tmp"
    return "$rc"
}

# Extract enumerated MCPs from the "Expected Model Lane Tool Surface"
# block of a to_model case branch.
extract_enumerated_mcps() {
    local lane="$1"
    local block=""
    block="$(awk -v lane="$lane" '
        $0 ~ "^    " lane "\\)$" { in_lane = 1; next }
        in_lane && /^        ;;$/ { in_lane = 0; in_block = 0; next }
        in_lane && /Expected Model Lane Tool Surface/ { in_block = 1; seen = 0; next }
        # Sub-block ends on blank line after content or next bold header.
        in_block && /^$/ && seen { in_block = 0; next }
        in_block && /^$/ { next }
        in_block && /^\*\*[A-Z][^:]*:\*\*/ { in_block = 0; next }
        in_block { seen = 1; print }
    ' "$TOOLKIT")" || return $?
    # The first sentence is the required MCP surface. Later sentences may name
    # MCP *tools* such as `generate_image`; treating those as server names is a
    # category error. A period inside a backtick token remains intact because
    # only a period followed by whitespace ends the sentence.
    printf '%s\n' "$block" \
        | sed 's/\. .*$//' \
        | grep -oE '`[A-Za-z0-9][A-Za-z0-9._:-]*`' \
        | tr -d '`' \
        | sort -u \
        || true
}

extract_installed_mcps() {
    local cli="$1"
    local raw_file="" rc=0
    raw_file="$(mktemp "${TMPDIR:-/tmp}/dispatch-toolkit-inventory-${cli}.XXXXXXXX")" \
        || return 70
    mcp_list_for_cli_with_timeout "$cli" >"$raw_file" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        rm -f "$raw_file"
        return "$rc"
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        rm -f "$raw_file"
        return 69
    fi
    python3 - "$cli" "$raw_file" <<'PYEOF'
import json
from pathlib import Path
import re
import sys

cli, source = sys.argv[1:]
text = Path(source).read_text(encoding="utf-8", errors="strict")
safe = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def canonical(name: str) -> str:
    name = name.strip()
    if name.startswith("plugin:"):
        name = name.rsplit(":", 1)[-1]
    if not safe.fullmatch(name):
        raise ValueError(f"unsafe MCP server name: {name!r}")
    return name


names = []
if cli == "codex":
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("Codex MCP inventory is not a JSON list")
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("Codex MCP inventory has the wrong schema")
        names.append(canonical(item["name"]))
elif cli in {"claude", "gemini"}:
    header = "Checking MCP server health…" if cli == "claude" else "Configured MCP servers:"
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header) + 1
    except StopIteration as exc:
        raise ValueError(f"{cli} MCP inventory header is missing") from exc
    for raw in lines[start:]:
        line = raw.strip()
        if not line:
            continue
        if cli == "claude":
            live_name, separator, remainder = line.partition(": ")
            _command, status_separator, status = remainder.rpartition(" - ")
            if not separator or not status_separator or not status.strip():
                raise ValueError("Claude MCP inventory contains an unparseable row")
            names.append(canonical(live_name))
        else:
            match = re.match(
                r"^[✓✔✗✘]\s+(?P<name>[A-Za-z0-9][A-Za-z0-9._:-]*)"
                r"(?:\s+\(from\s+[^)]+\))?:\s+.*\s+-\s+.+$",
                line,
            )
            if match is None:
                raise ValueError("Gemini MCP inventory contains an unparseable row")
            names.append(canonical(match.group("name")))
elif cli == "grok":
    lines = text.splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines)
            if re.fullmatch(r"\s*MCP Servers\s+\([0-9]+\)\s*", line)
        )
    except StopIteration as exc:
        raise ValueError("Grok MCP inventory header is missing") from exc
    declared_count = int(re.search(r"\(([0-9]+)\)", lines[start]).group(1))
    for raw in lines[start + 1:]:
        match = re.fullmatch(
            r"\s*[├└](?:─+)?\s+(?P<name>[A-Za-z0-9][A-Za-z0-9._:-]*)"
            r"\s+\((?:stdio|http)\)(?:\s+.*)?",
            raw,
        )
        if match is not None:
            names.append(canonical(match.group("name")))
        elif names and raw and not raw[0].isspace():
            break
    if len(set(names)) != declared_count:
        raise ValueError("Grok MCP inventory count does not match its inspect header")
else:
    # Kimi currently emits a text table. Refuse unknown non-header rows rather
    # than tokenizing every word and accidentally treating an error message as
    # a configured server.
    ignored = {"name", "mcp", "server", "servers", "status", "configured"}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith(("authlib", "from authlib")):
            continue
        match = re.match(
            r"^[✓✔✗✘]?\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._:-]*)"
            r"(?:\s|:|$)",
            line,
        )
        if match is None:
            raise ValueError("Kimi MCP inventory contains an unparseable row")
        name = match.group("name")
        if name.lower() in ignored:
            continue
        names.append(canonical(name))

for name in sorted(set(names)):
    print(name)
PYEOF
    rc=$?
    rm -f "$raw_file"
    return "$rc"
}

WARN_COUNT=0
UNKNOWN_COUNT=0
TOTAL_LANES=${#LANES[@]}

echo "Per-model-lane dispatch-toolkit MCP consistency check"
echo "================================================"
echo

i=0
while [ "$i" -lt "$TOTAL_LANES" ]; do
    lane="${LANES[$i]}"
    cli="${CLIS[$i]}"
    echo "[$lane] cli=$cli"

    enumerated_rc=0
    installed_rc=0
    enumerated="$(extract_enumerated_mcps "$lane")" || enumerated_rc=$?
    installed="$(extract_installed_mcps "$cli")" || installed_rc=$?

    if [ "$enumerated_rc" -ne 0 ]; then
        echo "  COULD NOT DETERMINE: expected MCP surface could not be parsed (exit $enumerated_rc)"
        UNKNOWN_COUNT=$((UNKNOWN_COUNT + 1))
        echo
        i=$((i + 1))
        continue
    fi
    if [ "$installed_rc" -ne 0 ]; then
        echo "  COULD NOT DETERMINE: $cli MCP inventory failed or timed out (exit $installed_rc)"
        UNKNOWN_COUNT=$((UNKNOWN_COUNT + 1))
        echo
        i=$((i + 1))
        continue
    fi

    if [ -z "$enumerated" ]; then
        echo "  WARN: $lane has no MCPs enumerated in dispatch-toolkit.sh expected surface"
        WARN_COUNT=$((WARN_COUNT + 1))
        echo
        i=$((i + 1))
        continue
    fi

    pane_warns=0
    while IFS= read -r mcp; do
        [[ -n "$mcp" ]] || continue
        if ! grep -Fxq -- "$mcp" <<< "$installed"; then
            echo "  WARN: $lane expects '$mcp' but it was not listed by $cli"
            WARN_COUNT=$((WARN_COUNT + 1))
            pane_warns=$((pane_warns + 1))
        fi
    done <<< "$enumerated"
    if [[ "$lane" != grok ]]; then
        while IFS= read -r mcp; do
            [[ -n "$mcp" ]] || continue
            if ! grep -Fxq -- "$mcp" <<< "$enumerated"; then
                echo "  WARN: $cli lists '$mcp' but $lane does not enumerate it"
                WARN_COUNT=$((WARN_COUNT + 1))
                pane_warns=$((pane_warns + 1))
            fi
        done <<< "$installed"
    fi

    if [ "$pane_warns" -eq 0 ]; then
        n=$(echo "$enumerated" | wc -l | tr -d ' ')
        echo "  OK: $n enumerated MCPs all match install state"
    fi
    echo
    i=$((i + 1))
done

echo "================================================"
if [ "$WARN_COUNT" -eq 0 ]; then
    if [ "$UNKNOWN_COUNT" -gt 0 ]; then
        echo "COULD NOT DETERMINE: $UNKNOWN_COUNT lane inventory check(s) did not run."
        exit 2
    fi
    echo "PASS: all expected MCP enumerations verified across $TOTAL_LANES model lanes."
    exit 0
else
    echo "FAIL: $WARN_COUNT mismatch(es) found. Fix dispatch-toolkit.sh OR install missing MCPs."
    exit 1
fi
