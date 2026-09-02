#!/bin/bash
# bin/dispatch-toolkit-verify.sh — per-pane MCP consistency check.
#
# For each model lane, RUN shared/dispatch-toolkit.sh the way send-task.sh does
# and read the "Expected Model Lane Tool Surface" block out of what it actually
# emits, then ask the CLI what's actually installed via the lane's native
# inventory command. Fail on expected-but-missing MCPs everywhere and on
# unexpected-installed MCPs where the native inventory is the exhaustive lane
# contract. Claude's controller/global plugins are role-scoped at launch, and
# Grok's inventory is explicitly global, so their safe extras are not required
# to appear in this generic toolkit block. Refuse to claim a match when either
# surface cannot be measured.
# Config-consistency check, NOT a runtime probe.
#
# The subject is judged as a script first (`bash -n`) and as a document second
# (its rendered stdout). Neither check alone is enough: a /dev/null-redirected
# toolkit parses cleanly, and an unrunnable one still reads correctly.
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
TOOL_REGISTRY="${DISPATCH_TOOLKIT_REGISTRY_UNDER_TEST:-${VAULT_ROOT}/shared/registries/skill-tool-registry.tsv}"

if [ ! -f "$TOOLKIT" ]; then
    echo "ERROR: dispatch-toolkit.sh not found at $TOOLKIT"
    exit 2
fi

# The subject has to be a script before it can be a document. Until 2026-09-01
# this check only ever ran awk over the toolkit's SOURCE TEXT, so a toolkit
# that bash cannot even parse still reported
# "PASS: all expected MCP enumerations verified across 5 model lanes" --
# measured with a one-character `esac` typo, and again with the bare `case`
# fragment lifted out of its script. Both are unrunnable; both were green.
# That is a defect in the audited file, not an inability to measure, so it is
# a FAIL (1) rather than a COULD NOT DETERMINE (2).
if ! parse_error="$(bash -n "$TOOLKIT" 2>&1)"; then
    echo "FAIL: $TOOLKIT is not valid bash, so no lane can be verified against it."
    printf '%s\n' "$parse_error" | sed 's/^/  /'
    exit 1
fi

# Parallel arrays — bash 3.2 has no associative arrays
LANES=(gpt-codex claude gemini grok kimi)
# CLIS must name the binary DISPATCH launches, not the lane. The gemini lane
# runs on `agy` under OAuth -- the API-key `gemini` path is retired -- and this
# array said `gemini` for weeks, so every gemini row audited a CLI the squad no
# longer uses. Its six "lists X but does not enumerate it" warnings, perplexity
# among them, described the retired binary; a live `agy mcp list` shows
# chrono-research-arsenal enabled.
#
# Same split-source defect that took memory autocapture down for 12 days and 73
# notes (4928b84b). seatbelt_profile.LANE_CLI_PATHS is the one home
# (CLAUDE.md Hard Rule 10); test_toolkit_verify_lane_authority.py pins every
# lane here to it, in both directions.
CLIS=(codex     claude agy    grok kimi)
# (chrono pane is the Coordinator and doesn't receive a toolkit injection.)

# Every lane is asked with the subscription credentials unset: each of these
# CLIs prefers an API key over the operator's OAuth session when both are set,
# and would then report a different account's MCP inventory. Named once so a
# sixth lane cannot be added without it.
NOAUTH=(env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY)

mcp_list_for_cli() {
    local cli="$1"
    if [[ -n "${DISPATCH_TOOLKIT_MCP_LIST_DIR_UNDER_TEST:-}" ]]; then
        local fixture="${DISPATCH_TOOLKIT_MCP_LIST_DIR_UNDER_TEST}/${cli}.txt"
        [[ -f "$fixture" ]] || return 66
        cat "$fixture"
        return 0
    fi
    # Per-lane stderr handling is deliberate, not incidental: codex must emit
    # clean JSON and kimi prattles authlib warnings, so both discard stderr,
    # while agy prints its table on stdout; 2>&1 keeps any diagnostic with it.
    case "$cli" in
        claude) "${NOAUTH[@]}" "$cli" mcp list 2>&1 ;;
        codex)  "${NOAUTH[@]}" "$cli" mcp list --json 2>/dev/null ;;
        # agy prints its table on stdout and REJECTS the retired gemini CLI's
        # -d flag ("flags provided but not defined: -d"), so this cannot be a
        # blind rename: keeping -d would fail every gemini-lane probe instead
        # of reporting an inventory. Verified against the installed binary.
        agy)    "${NOAUTH[@]}" "$cli" mcp list 2>&1 ;;
        grok)   "${NOAUTH[@]}" "$cli" inspect 2>&1 ;;
        *)      "${NOAUTH[@]}" "$cli" mcp list 2>/dev/null ;;
    esac
}

# Count the MCP connections this lane is declared to carry. The registry is
# the broad host-capability authority, while the rendered toolkit is a
# role-facing subset; callers take the larger count so a withheld/out-of-date
# registry cannot make the timeout smaller than the surface under test.
declared_mcp_count_for_lane() {
    local lane="$1"
    [[ "$lane" == gpt-codex ]] && lane=codex
    [[ -f "$TOOL_REGISTRY" ]] || { printf '0\n'; return 0; }
    awk -F '\t' -v lane="$lane" '
        NR == 1 {
            for (i = 1; i <= NF; i++) column[$i] = i
            next
        }
        function lane_matches(spec,    parts, n, j) {
            if (spec == "all") return 1
            n = split(spec, parts, "|")
            for (j = 1; j <= n; j++) if (parts[j] == lane) return 1
            return 0
        }
        $column["record_kind"] == "tool" &&
        $column["type"] == "mcp" &&
        $column["verified_state"] != "no" &&
        lane_matches($column["lanes"]) { count++ }
        END { print count + 0 }
    ' "$TOOL_REGISTRY"
}

# Compatibility servers remain installed so old callers keep working, but the
# toolkit intentionally does not advertise them to new workers. This policy is
# derived from registry semantics, never a server-name exception: the row must
# declare both compatibility intent and a preferred successor for new callers.
# A future alias using the same declaration is therefore classified without an
# edit here. Unsafe names and unreadable/malformed registries fail closed at the
# comparison site: the installed extra remains a WARN.
declared_compatibility_aliases_for_lane() {
    local lane="$1"
    [[ "$lane" == gpt-codex ]] && lane=codex
    [[ -f "$TOOL_REGISTRY" ]] || return 66
    awk -F '\t' -v lane="$lane" '
        NR == 1 {
            for (i = 1; i <= NF; i++) column[$i] = i
            required[1] = "name"
            required[2] = "record_kind"
            required[3] = "type"
            required[4] = "lanes"
            required[5] = "invocation"
            required[6] = "verified_state"
            required[7] = "notes"
            for (i = 1; i <= 7; i++) if (!column[required[i]]) invalid = 1
            next
        }
        function lane_matches(spec,    parts, n, j) {
            if (spec == "all") return 1
            n = split(spec, parts, "|")
            for (j = 1; j <= n; j++) if (parts[j] == lane) return 1
            return 0
        }
        !invalid &&
        $column["record_kind"] == "tool" &&
        $column["type"] == "mcp" &&
        $column["verified_state"] != "no" &&
        lane_matches($column["lanes"]) {
            invocation = tolower($column["invocation"])
            declaration = invocation " " tolower($column["notes"])
            if (declaration ~ /(^|[^a-z])compatibility([^a-z]|$)/ &&
                invocation ~ /(^|[^a-z])prefer .+ for new callers([^a-z]|$)/) {
                name = $column["name"]
                if (name !~ /^[A-Za-z0-9][A-Za-z0-9._:-]*$/) invalid = 1
                else print name
            }
        }
        END { if (invalid) exit 65 }
    ' "$TOOL_REGISTRY" | sort -u
}

# Units: all inputs and outputs are whole seconds. Operator measurements on
# this host (2026-09-01) were 5.9s, 6.0s, 6.8s, and 7.3s under load for the
# Claude lane's ten declared MCP connections. Five seconds covers fixed CLI
# startup/cleanup and one second per declared connection scales the cap as the
# inventory grows; that gives Claude 15s today instead of a workload-blind 8s.
# A slow host can supply a measured whole-second override without removing the
# finite cap. Invalid overrides fail the inventory check rather than silently
# weakening or disabling it.
mcp_list_timeout_seconds() {
    local declared_server_count="$1"
    local override="${DISPATCH_TOOLKIT_MCP_LIST_TIMEOUT_SECONDS:-}"
    if [[ -n "$override" ]]; then
        case "$override" in
            *[!0-9]*|'') return 64 ;;
        esac
        [[ "$override" -gt 0 ]] || return 64
        printf '%s\n' "$override"
        return 0
    fi
    case "$declared_server_count" in
        *[!0-9]*|'') return 64 ;;
    esac
    printf '%s\n' "$((5 + declared_server_count))"
}

# Run one lane's inventory into `dest`, killing it if it overruns. The output is
# read only on a zero exit, so the timeout path leaves the partial capture for
# the caller to discard.
mcp_list_for_cli_with_timeout() {
    local cli="$1" dest="$2" declared_server_count="$3" rc=0
    local timeout_seconds=""
    timeout_seconds="$(mcp_list_timeout_seconds "$declared_server_count")" \
        || return $?
    mcp_list_for_cli "$cli" > "$dest" 2>&1 &
    local pid=$!
    # Poll in tenths so a fast local inventory does not pay a one-second tax
    # and the whole-second cap is enforced within 100ms of its boundary.
    local waited_tenths=0
    local timeout_tenths=$((timeout_seconds * 10))
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$waited_tenths" -ge "$timeout_tenths" ]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
            return 124
        fi
        sleep 0.1
        waited_tenths=$((waited_tenths + 1))
    done
    wait "$pid" 2>/dev/null || rc=$?
    return "$rc"
}

# Render the toolkit for one lane, exactly the way the dispatch path does:
# bin/send-task.sh runs `bash shared/dispatch-toolkit.sh <namespace> <to-model>`
# and appends the stdout to the packet. The namespace is deliberately empty --
# it selects the toolkit's own "unknown namespace, no toolkit injection"
# branch, so only the lane block varies and this check stays a lane check.
#
# Reading the source instead of running it was the hole: a toolkit whose every
# heredoc is redirected to /dev/null still SPELLS OUT each expected-surface
# block in the file, so source-parsing declared five clean lanes for a toolkit
# that injects nothing into any packet. `bash -n` cannot see that either --
# such a file parses and exits 0. Rendered stdout is the only artifact a
# dispatched lane ever receives, so it is the thing to compare.
render_toolkit_lane() {
    bash "$TOOLKIT" '' "$1" 2>/dev/null
}

# Extract enumerated MCPs from the "Expected Model Lane Tool Surface"
# block of the rendered lane markdown, read on stdin.
extract_enumerated_mcps() {
    local block=""
    block="$(awk '
        index($0, "Expected Model Lane Tool Surface") { in_block = 1; seen = 0; next }
        # Sub-block ends on blank line after content or next bold header.
        in_block && /^$/ && seen { in_block = 0; next }
        in_block && /^$/ { next }
        in_block && /^\*\*[A-Z][^:]*:\*\*/ { in_block = 0; next }
        in_block { seen = 1; print }
    ')" || return $?
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
    local cli="$1" declared_server_count="$2"
    local raw_file="" rc=0
    raw_file="$(mktemp "${TMPDIR:-/tmp}/dispatch-toolkit-inventory-${cli}.XXXXXXXX")" \
        || return 70
    mcp_list_for_cli_with_timeout "$cli" "$raw_file" "$declared_server_count" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        rm -f "$raw_file"
        return "$rc"
    fi
    # No `command -v python3` pre-flight: an absent interpreter exits 127 here,
    # which the caller already reports as COULD NOT DETERMINE — the same verdict
    # the pre-flight produced, one branch later.
    python3 - "$cli" "$raw_file" "$VAULT_ROOT" <<'PYEOF'
import json
from pathlib import Path
import re
import sys

cli, source, repo_root = sys.argv[1:]
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
elif cli == "claude":
    # Claude's native inventory includes three reviewed first-party connector
    # names with spaces and dots. Reuse the launch rail's canonical parser so
    # this verifier accepts exactly those names, maps them onto shell-safe
    # adapter IDs, and retains its rejection of unknown/lookalike/metacharacter
    # names. A second free-form allowlist here would become another authority.
    sys.path.insert(0, str(Path(repo_root) / "scripts" / "python"))
    from lane_capability_enforcement import (  # noqa: E402
        CapabilityDenied,
        parse_live_mcp_listing,
    )

    try:
        names.extend(parse_live_mcp_listing(lane="claude", output=text))
    except CapabilityDenied as exc:
        raise ValueError(str(exc)) from exc
elif cli == "agy":
    lines = text.splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines)
            if line.split() == ["NAME", "TYPE", "STATUS", "COMMAND/URL"]
        ) + 1
    except StopIteration as exc:
        raise ValueError("agy MCP inventory table header is missing") from exc
    for raw in lines[start:]:
        line = raw.strip()
        if not line:
            continue
        columns = line.split(maxsplit=3)
        if len(columns) != 4 or not all(columns[1:]):
            raise ValueError("agy MCP inventory contains an unparseable row")
        names.append(canonical(columns[0]))
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

    render_rc=0
    rendered="$(render_toolkit_lane "$lane")" || render_rc=$?
    if [ "$render_rc" -ne 0 ]; then
        echo "  WARN: $lane — the toolkit exited $render_rc rendering this lane, so the"
        echo "        text send-task.sh would append to a $lane packet is not trustworthy"
        WARN_COUNT=$((WARN_COUNT + 1))
        echo
        i=$((i + 1))
        continue
    fi

    enumerated_rc=0
    installed_rc=0
    enumerated="$(printf '%s\n' "$rendered" | extract_enumerated_mcps)" || enumerated_rc=$?
    enumerated_count="$(printf '%s\n' "$enumerated" | awk 'NF { count++ } END { print count + 0 }')"
    declared_count="$(declared_mcp_count_for_lane "$lane")" || declared_count=0
    if [[ "$enumerated_count" -gt "$declared_count" ]]; then
        declared_count="$enumerated_count"
    fi
    installed="$(extract_installed_mcps "$cli" "$declared_count")" || installed_rc=$?

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
        echo "  WARN: $lane rendered no expected-surface MCPs — the block is missing or"
        echo "        empty in what dispatch-toolkit.sh actually emits for this lane"
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
    if [[ "$lane" == claude ]]; then
        # Claude's native inventory is intentionally global: first-party
        # connectors and optional plugins can be installed for the controller,
        # while lane_capability_enforcement.py denies their tool namespaces to
        # a worker unless its role projection authorizes them. The toolkit
        # block is therefore a required subset, not an exhaustive global list.
        # The parser above still validates every name fail-closed before any
        # item reaches this comparison.
        optional_count=0
        while IFS= read -r mcp; do
            [[ -n "$mcp" ]] || continue
            if ! grep -Fxq -- "$mcp" <<< "$enumerated"; then
                optional_count=$((optional_count + 1))
            fi
        done <<< "$installed"
        if [[ "$optional_count" -gt 0 ]]; then
            echo "  NOTE: $optional_count role-scoped optional/global MCP(s) are not required by the toolkit"
        fi
    elif [[ "$lane" != grok ]]; then
        compatibility_aliases="$(declared_compatibility_aliases_for_lane "$lane")" \
            || compatibility_aliases=""
        while IFS= read -r mcp; do
            [[ -n "$mcp" ]] || continue
            if ! grep -Fxq -- "$mcp" <<< "$enumerated"; then
                if grep -Fxq -- "$mcp" <<< "$compatibility_aliases"; then
                    echo "  NOTE: $cli lists '$mcp'; registry marks it compatibility-only,"
                    echo "        so $lane intentionally does not enumerate it"
                else
                    echo "  WARN: $cli lists '$mcp' but $lane does not enumerate it"
                    WARN_COUNT=$((WARN_COUNT + 1))
                    pane_warns=$((pane_warns + 1))
                fi
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
