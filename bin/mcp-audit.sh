#!/bin/bash
# Audit MCP registration and real stdio usability for the squad CLIs.

set -uo pipefail

export PATH="${HOME}/.grok/bin:${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
CHRONO_PY="${CHRONO_PY:-${VAULT_ROOT}/.venv/bin/python}"
CHRONO_PLUGINS="${CHRONO_PLUGINS:-${VAULT_ROOT}/plugins}"
PROBE="${VAULT_ROOT}/scripts/python/mcp_probe.py"
DATE="$(date -u +%Y-%m-%d)"
LOG="${VAULT_ROOT}/_state/audit-logs/${DATE}-mcp-audit.md"

mkdir -p "$(dirname "${LOG}")"

# Library mode (MCP_AUDIT_LIB_ONLY=1) stops before any side effect so the test
# suite can exercise the helpers below. It must not inherit the operator's real
# secrets either, or credential-presence assertions would depend on the host.
if [[ "${MCP_AUDIT_LIB_ONLY:-0}" != "1" && -f "${HOME}/.config/shell/secrets.zsh" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "${HOME}/.config/shell/secrets.zsh"
    set -u
fi

MCPS=(
    "chrono-vault|required|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py|CHRONO_VAULT_ROOT OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    "chrono-obsidian|required|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py --namespace obsidian|CHRONO_VAULT_ROOT OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    # Exactly the credentials this server reads: FIRECRAWL_API_KEY (firecrawl_scrape
    # /_crawl/_parse), PERPLEXITY_API_KEY (perplexity_search), XAI_API_KEY
    # (xai_search); arxiv_search needs none. APIFY_TOKEN/BRAVE_API_KEY/
    # SERPER_API_KEY were audited here with no reader in the server, so their
    # absence could never explain an outage, while FIRECRAWL_API_KEY -- which
    # three of the six tools require -- went unwatched.
    "chrono-research-arsenal|optional|${CHRONO_PLUGINS}/chrono-research-arsenal/mcp_server.py|FIRECRAWL_API_KEY PERPLEXITY_API_KEY XAI_API_KEY"
    "chrono-media-studio|optional|${CHRONO_PLUGINS}/chrono-media-studio/mcp_server.py|GEMINI_API_KEY OPENAI_API_KEY XAI_API_KEY"
    "chrono-recon|optional|${CHRONO_PLUGINS}/chrono-recon/mcp_server.py|GH_TOKEN"
)

command_list() {
    local cli="$1"
    case "$cli" in
        codex) codex mcp list 2>/dev/null || true ;;
        gemini) agy mcp list 2>&1 || true ;;
        grok) grok inspect 2>&1 || true ;;
        kimi) kimi mcp list 2>&1 | grep -v 'AuthlibDeprecation\|authlib.jose\|It will be compatible\|from authlib' || true ;;
        claude)
            for file in "${HOME}/.claude/settings.json" "${VAULT_ROOT}/.claude/settings.json"; do
                [[ -f "$file" ]] || continue
                if command -v jq >/dev/null 2>&1; then
                    jq -r '.. | objects | .mcpServers? // empty | keys[]' "$file" 2>/dev/null || true
                else
                    grep -Eo '"chrono-[^"]+"' "$file" | tr -d '"' || true
                fi
            done
            # chrono-recon (and other chrono-* servers) load via enabledPlugins on the
            # claude lane, not the mcpServers block — surface plugin base names too so
            # plugin-registered MCPs are detected as registered.
            if command -v jq >/dev/null 2>&1; then
                jq -r '.enabledPlugins // {} | to_entries[] | select(.value==true) | .key | sub("@.*";"")' "${HOME}/.claude/settings.json" 2>/dev/null || true
            fi
            ;;
    esac
}

has_registration() {
    local list="$1" name="$2"
    echo "$list" | grep -Eq "(^|[[:space:]])${name}($|[[:space:]])"
}

# Does this auth_ok state count against the audit verdict?
#
# env_status computing "partial(2/3)" is worth nothing if only the human-read
# log row carries it. doctor.sh keys on the `summary: issues=N warnings=N`
# line, so an unset FIRECRAWL_API_KEY rendered as "MCP usability audit passed"
# while three of six arsenal tools were dead at call time.
#
# A shortfall is a WARNING, not an issue: the server is registered, reachable
# and usable -- individual tools fail when called. That is degraded, not down.
credential_shortfall() {
    case "$1" in
        partial\(*|missing\(*) return 0 ;;
        *) return 1 ;;
    esac
}

env_status() {
    local vars="$1"
    [[ -z "$vars" ]] && { echo "n/a"; return; }
    local present=0 total=0
    for var in $vars; do
        total=$((total + 1))
        [[ -n "${!var:-}" ]] && present=$((present + 1))
    done
    # "ok" means every declared credential is present. Anything less is
    # "partial": each absent key is a tool that fails at call time, and an
    # ok(1/5) beside four missing keys is how a broken lane read as healthy.
    if [[ "$present" -eq "$total" ]]; then
        echo "ok(${present}/${total})"
    elif [[ "$present" -gt 0 ]]; then
        echo "partial(${present}/${total})"
    else
        echo "missing(0/${total})"
    fi
}

probe_mcp() {
    local args_str="$1"
    local call_tool="${2:-}"
    [[ -x "$CHRONO_PY" ]] || { echo "usable=false reason=missing-python"; return 1; }
    [[ -f "$PROBE" ]] || { echo "usable=false reason=missing-probe"; return 1; }
    # shellcheck disable=SC2206
    local args_arr=($args_str)
    [[ -f "${args_arr[0]}" ]] || { echo "usable=false reason=missing-server"; return 1; }
    # Hard-cap the probe: an MCP server that hangs on init must be REPORTED as
    # unusable, never allowed to freeze the audit (which freezes doctor + launch).
    # -k SIGKILLs the process group if it ignores SIGTERM, so no orphaned server.
    local rc=0
    # `--call TOOL` only when the caller named one. Two plain words rather than
    # an array: bash 3.2 cannot expand an empty array under `set -u`.
    timeout -k 2 "${MCP_PROBE_TIMEOUT:-8}" "$CHRONO_PY" "$PROBE" \
        ${call_tool:+--call "$call_tool"} "$CHRONO_PY" "${args_arr[@]}" 2>/dev/null || rc=$?
    if [[ "$rc" -eq 124 || "$rc" -eq 137 ]]; then
        echo "usable=false reason=probe-timeout"
    fi
    return "$rc"
}

# Helpers are defined; everything past here probes live servers and writes the
# operator's audit log. Library mode returns now.
if [[ "${MCP_AUDIT_LIB_ONLY:-0}" == "1" ]]; then
    return 0 2>/dev/null || exit 0
fi

{
    echo "# MCP Audit - ${DATE}"
    echo ""
    echo "Run at: $(date -u +%FT%TZ)"
    echo ""
} > "${LOG}"

issues=0
warnings=0
PROBE_CACHE="$(mktemp -d "${TMPDIR:-/tmp}/mcp-audit.XXXXXX")"
trap 'rm -rf "${PROBE_CACHE}"' EXIT

# Probe all MCP servers in PARALLEL. Each writes its own cache file and is
# independently timeout-capped, so they don't interfere — this turns ~18×(up to
# 8s) sequential into one ~8s wave, which is what kept doctor/launch slow.
for entry in "${MCPS[@]}"; do
    IFS='|' read -r name _tier args_str _vars <<<"$entry"
    # chrono-vault alone gets a real tool call. `health` is read-only and is the
    # only tool here that reports whether the thing behind the server actually
    # works: a stale index leaves every recall dead while the server handshakes
    # and dispatches perfectly, which no sentinel call can see. Every other
    # server keeps the sentinel, because their tools write to the KG
    # (record_finding) or spend metered credit (firecrawl_scrape).
    # A branch and not a sixth MCPS field: exactly one server qualifies, and one
    # `[[ ]]` reads plainer than a table with one populated row. Add the field
    # when a second server earns a safe health tool.
    probe_call=""
    [[ "$name" == "chrono-vault" ]] && probe_call="health"
    probe_mcp "$args_str" "$probe_call" > "${PROBE_CACHE}/${name}.txt" 2>/dev/null &
done
wait

for cli in claude codex gemini grok kimi; do
    echo "## ${cli}" | tee -a "${LOG}"
    cli_binary="${cli}"
    [[ "${cli}" == gemini ]] && cli_binary=agy
    if ! command -v "${cli_binary}" >/dev/null 2>&1; then
        echo "- cli_present=false" | tee -a "${LOG}"
        issues=$((issues + 1))
        echo "" | tee -a "${LOG}"
        continue
    fi
    echo "- cli_present=true" | tee -a "${LOG}"
    list="$(command_list "$cli")"
    for entry in "${MCPS[@]}"; do
        IFS='|' read -r name tier args_str vars <<<"$entry"
        registered=false
        has_registration "$list" "$name" && registered=true
        reachable=false
        # shellcheck disable=SC2206
        args_arr=($args_str)
        [[ -x "$CHRONO_PY" && -f "${args_arr[0]}" ]] && reachable=true
        auth_ok="$(env_status "$vars")"
        probe_result="$(cat "${PROBE_CACHE}/${name}.txt" 2>/dev/null || echo "usable=false reason=probe-missing")"
        usable=false
        echo "$probe_result" | grep -q 'usable=true' && usable=true

        echo "- ${name}: tier=${tier} registered=${registered} reachable=${reachable} auth_ok=${auth_ok} ${probe_result}" | tee -a "${LOG}"
        if credential_shortfall "${auth_ok}"; then
            warnings=$((warnings + 1))
        fi

        if [[ "$tier" == "required" && ( "$registered" != "true" || "$reachable" != "true" || "$usable" != "true" ) ]]; then
            issues=$((issues + 1))
        elif [[ "$registered" != "true" || "$reachable" != "true" || "$usable" != "true" ]]; then
            warnings=$((warnings + 1))
        fi
    done
    echo "" | tee -a "${LOG}"
done

echo "summary: issues=${issues} warnings=${warnings} log=${LOG}"
[[ "$issues" -eq 0 ]]
