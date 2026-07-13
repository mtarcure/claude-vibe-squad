#!/bin/bash
# Audit MCP registration and real stdio usability for the squad CLIs.

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
CHRONO_PY="${CHRONO_PY:-${HOME}/chrono/.venv/bin/python}"
CHRONO_PLUGINS="${CHRONO_PLUGINS:-${HOME}/chrono/plugins}"
PROBE="${VAULT_ROOT}/scripts/python/mcp_probe.py"
DATE="$(date -u +%Y-%m-%d)"
LOG="${VAULT_ROOT}/_state/audit-logs/${DATE}-mcp-audit.md"

mkdir -p "$(dirname "${LOG}")"

if [[ -f "${HOME}/.config/shell/secrets.zsh" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "${HOME}/.config/shell/secrets.zsh"
    set -u
fi

MCPS=(
    "chrono-vault|required|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py|CHRONO_VAULT_ROOT OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    "chrono-kg|required|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py --namespace kg|CHRONO_VAULT_ROOT OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    "chrono-obsidian|required|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py --namespace obsidian|OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    "chrono-catalog|required|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py --namespace catalog|"
    "chrono-research-arsenal|optional|${CHRONO_PLUGINS}/chrono-research-arsenal/mcp_server.py|APIFY_TOKEN BRAVE_API_KEY PERPLEXITY_API_KEY SERPER_API_KEY XAI_API_KEY"
    "chrono-content-engineer|optional|${CHRONO_PLUGINS}/chrono-content-engineer/mcp_server.py|GEMINI_API_KEY OPENAI_API_KEY XAI_API_KEY"
    "chrono-recon|optional|${CHRONO_PLUGINS}/chrono-recon/mcp_server.py|GH_TOKEN"
)

command_list() {
    local cli="$1"
    case "$cli" in
        codex) codex mcp list 2>/dev/null || true ;;
        gemini)
            if [[ -f "${HOME}/.gemini/settings.json" ]] && command -v jq >/dev/null 2>&1; then
                jq -r '.mcpServers // {} | keys[]' "${HOME}/.gemini/settings.json" 2>/dev/null || true
            fi
            ;;
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

env_status() {
    local vars="$1"
    [[ -z "$vars" ]] && { echo "n/a"; return; }
    local present=0 total=0
    for var in $vars; do
        total=$((total + 1))
        [[ -n "${!var:-}" ]] && present=$((present + 1))
    done
    [[ "$present" -gt 0 ]] && echo "ok(${present}/${total})" || echo "missing(0/${total})"
}

probe_mcp() {
    local args_str="$1"
    [[ -x "$CHRONO_PY" ]] || { echo "usable=false reason=missing-python"; return 1; }
    [[ -f "$PROBE" ]] || { echo "usable=false reason=missing-probe"; return 1; }
    # shellcheck disable=SC2206
    local args_arr=($args_str)
    [[ -f "${args_arr[0]}" ]] || { echo "usable=false reason=missing-server"; return 1; }
    "$CHRONO_PY" "$PROBE" "$CHRONO_PY" "${args_arr[@]}" 2>/dev/null
}

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

for entry in "${MCPS[@]}"; do
    IFS='|' read -r name _tier args_str _vars <<<"$entry"
    probe_mcp "$args_str" > "${PROBE_CACHE}/${name}.txt" 2>/dev/null || true
done

for cli in claude codex gemini kimi; do
    echo "## ${cli}" | tee -a "${LOG}"
    if ! command -v "$cli" >/dev/null 2>&1; then
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
