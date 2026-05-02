#!/bin/bash
# Bootstrap chrono MCP servers across the 4 CLIs (Codex, Gemini, Kimi).
# Claude Code uses ~/.claude/settings.json + chrono plugins, managed separately.
#
# Idempotent: if an MCP is already registered, skip. If missing, register.
# Sources ~/.config/shell/secrets.zsh for API keys.
#
# Usage:
#   bash scripts/bootstrap-mcps.sh           # check + register
#   bash scripts/bootstrap-mcps.sh --dry-run # show what would happen
#   bash scripts/bootstrap-mcps.sh --status  # just show status

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

DRY_RUN=0
STATUS_ONLY=0
for arg in "$@"; do
    case "${arg}" in
        --dry-run) DRY_RUN=1 ;;
        --status) STATUS_ONLY=1 ;;
        --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
    esac
done

# Source operator secrets
SECRETS="${HOME}/.config/shell/secrets.zsh"
if [[ -f "${SECRETS}" ]]; then
    # shellcheck disable=SC1090
    source "${SECRETS}"
fi

CHRONO_PY="${HOME}/chrono/.venv/bin/python"
CHRONO_PLUGINS="${HOME}/chrono/plugins"

if [[ ! -x "${CHRONO_PY}" ]]; then
    echo "WARNING: chrono Python venv not at ${CHRONO_PY}"
    echo "Skipping registration (chrono MCP servers can't run without it)."
    exit 0
fi

# === MCP definitions ===
# Format per MCP:  name|args|env_vars (space-separated KEY=VAR_NAME pairs to forward)
MCPS=(
    "chrono-vault|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py|CHRONO_VAULT_ROOT OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    "chrono-kg|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py --namespace kg|CHRONO_VAULT_ROOT OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    "chrono-obsidian|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py --namespace obsidian|OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    "chrono-catalog|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py --namespace catalog|"
    "chrono-research-arsenal|${CHRONO_PLUGINS}/chrono-research-arsenal/mcp_server.py|APIFY_TOKEN BRAVE_API_KEY PERPLEXITY_API_KEY SERPER_API_KEY XAI_API_KEY"
    "chrono-content-engineer|${CHRONO_PLUGINS}/chrono-content-engineer/mcp_server.py|GEMINI_API_KEY OPENAI_API_KEY XAI_API_KEY"
)

# Compute env flags for a given mcp's env-var-name list
build_env_flags_codex() {
    local out=""
    for v in $1; do
        local val="${!v:-}"
        if [[ -n "${val}" ]]; then
            out+=" --env ${v}=${val}"
        fi
    done
    echo "${out}"
}

build_env_flags_gemini() {
    local out=""
    for v in $1; do
        local val="${!v:-}"
        if [[ -n "${val}" ]]; then
            out+=" -e ${v}=${val}"
        fi
    done
    echo "${out}"
}

# Mask actual key values in dry-run output (keep var name, show *****)
mask_env_flags() {
    local input="$1"
    echo "${input}" | sed -E 's/(=)[^ ]{6,}/\1*****/g'
}

# Snapshot current registrations
# `gemini mcp list` is unreliable (silent on user-scope) so we parse settings.json.
echo "=== Discovering existing MCP registrations ==="
CODEX_LIST=$(codex mcp list 2>/dev/null || echo "")
GEMINI_SETTINGS="${HOME}/.gemini/settings.json"
GEMINI_LIST=""
if [[ -f "${GEMINI_SETTINGS}" ]] && command -v jq >/dev/null 2>&1; then
    GEMINI_LIST=$(jq -r '.mcpServers // {} | keys[]' "${GEMINI_SETTINGS}" 2>/dev/null || echo "")
fi
KIMI_LIST=$(kimi mcp list 2>&1 | grep -v 'AuthlibDeprecation\|authlib.jose\|It will be compatible\|from authlib' || echo "")

show_status() {
    local cli="$1"; local list="$2"; local label="$3"
    echo ""
    echo "## ${label}"
    for entry in "${MCPS[@]}"; do
        local name="${entry%%|*}"
        if echo "${list}" | grep -q "^[ ]*${name}\b\|^${name}\b"; then
            echo "  ✓ ${name}"
        else
            echo "  ✗ ${name} (missing)"
        fi
    done
}

show_status "codex" "${CODEX_LIST}" "Codex CLI"
show_status "gemini" "${GEMINI_LIST}" "Gemini CLI"
show_status "kimi" "${KIMI_LIST}" "Kimi CLI"

if [[ ${STATUS_ONLY} -eq 1 ]]; then
    exit 0
fi

echo ""
echo "=== Registering missing MCPs ==="

register_codex() {
    local name="$1"; local args_str="$2"; local env_vars="$3"
    if echo "${CODEX_LIST}" | grep -q "^${name}\b"; then
        echo "  [codex] ${name}: already registered"
        return
    fi
    local env_flags
    env_flags=$(build_env_flags_codex "${env_vars}")
    # shellcheck disable=SC2206
    local args_arr=(${args_str})
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  [codex] would: codex mcp add ${name}$(mask_env_flags "${env_flags}") -- ${CHRONO_PY} ${args_arr[*]}"
        return
    fi
    # shellcheck disable=SC2086
    if codex mcp add "${name}" ${env_flags} -- "${CHRONO_PY}" "${args_arr[@]}" 2>/dev/null; then
        echo "  [codex] ${name}: ✓ added"
    else
        echo "  [codex] ${name}: ✗ failed"
    fi
}

register_gemini() {
    local name="$1"; local args_str="$2"; local env_vars="$3"
    if echo "${GEMINI_LIST}" | grep -q "${name}"; then
        echo "  [gemini] ${name}: already registered"
        return
    fi
    local env_flags
    env_flags=$(build_env_flags_gemini "${env_vars}")
    # shellcheck disable=SC2206
    local args_arr=(${args_str})
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  [gemini] would: gemini mcp add -s user$(mask_env_flags "${env_flags}") ${name} ${CHRONO_PY} ${args_arr[*]}"
        return
    fi
    # shellcheck disable=SC2086
    if gemini mcp add -s user ${env_flags} "${name}" "${CHRONO_PY}" "${args_arr[@]}" >/dev/null 2>&1; then
        echo "  [gemini] ${name}: ✓ added"
    else
        echo "  [gemini] ${name}: ✗ failed"
    fi
}

register_kimi() {
    local name="$1"; local args_str="$2"; local env_vars="$3"
    if echo "${KIMI_LIST}" | grep -q "${name}"; then
        echo "  [kimi] ${name}: already registered"
        return
    fi
    # kimi takes JSON config; use mcp add helper
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  [kimi] would: register ${name} (via kimi mcp add)"
        return
    fi
    # shellcheck disable=SC2206
    local args_arr=(${args_str})
    local env_flags=()
    for v in ${env_vars}; do
        local val="${!v:-}"
        if [[ -n "${val}" ]]; then
            env_flags+=("--env" "${v}=${val}")
        fi
    done
    if kimi mcp add "${name}" "${CHRONO_PY}" "${args_arr[@]}" "${env_flags[@]}" >/dev/null 2>&1; then
        echo "  [kimi] ${name}: ✓ added"
    else
        echo "  [kimi] ${name}: ✗ failed (may need manual registration — see ~/.kimi/mcp.json)"
    fi
}

for entry in "${MCPS[@]}"; do
    IFS='|' read -r name args_str env_vars <<<"${entry}"
    echo ""
    echo "${name}:"
    register_codex "${name}" "${args_str}" "${env_vars}"
    register_gemini "${name}" "${args_str}" "${env_vars}"
    register_kimi "${name}" "${args_str}" "${env_vars}"
done

echo ""
echo "=== Done. Re-run with --status to verify. ==="
