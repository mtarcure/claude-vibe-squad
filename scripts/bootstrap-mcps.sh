#!/bin/bash
# Bootstrap chrono MCP servers across Codex, Gemini, agy, and Kimi.
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VAULT_ROOT="${VAULT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd -P)}"

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

CHRONO_PY="${CHRONO_PY:-${VAULT_ROOT}/.venv/bin/python}"
CHRONO_PLUGINS="${CHRONO_PLUGINS:-${VAULT_ROOT}/plugins}"

# The venv is required to *register* the chrono MCPs, but not to *report* what is
# already registered. Record its absence and keep going, so `--status` still
# answers rather than exiting silently and reading as "nothing to report".
VENV_OK=1
if [[ ! -x "${CHRONO_PY}" ]]; then
    VENV_OK=0
fi

cli_available() { command -v "$1" >/dev/null 2>&1; }

# === MCP definitions ===
# Format per MCP:  name|args|env_vars (space-separated KEY=VAR_NAME pairs to forward)
MCPS=(
    "chrono-vault|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py|CHRONO_VAULT_ROOT OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    # CHRONO_VAULT_ROOT is required even in the obsidian namespace: this is the
    # SAME mcp_server.py, and its startup guard plus vaultroot.resolve_vault_root()
    # both read CHRONO_VAULT_ROOT only -- they do NOT honour the OBSIDIAN_VAULT_ROOT
    # alias that broker.py (ROOT_ALIASES) and clearance.py (VAULT_PATH_ENV) declare.
    # MCP clients pass this env dict INSTEAD of the inherited environment, so a
    # shell export cannot cover the gap. Omitting it made the server exit before
    # the handshake, which every client reported only as "Connection closed"
    # (kimi refused to start at all). Verified 2026-08-17 by spawning the server
    # under `env -i` with just the two names below.
    "chrono-obsidian|${CHRONO_PLUGINS}/chrono-vault/mcp_server.py --namespace obsidian|CHRONO_VAULT_ROOT OBSIDIAN_REST_API_KEY OBSIDIAN_VAULT_ROOT"
    "chrono-research-arsenal|${CHRONO_PLUGINS}/chrono-research-arsenal/mcp_server.py|APIFY_TOKEN BRAVE_API_KEY FIRECRAWL_API_KEY PERPLEXITY_API_KEY SERPER_API_KEY XAI_API_KEY"
    "chrono-media-studio|${CHRONO_PLUGINS}/chrono-media-studio/mcp_server.py|GEMINI_API_KEY OPENAI_API_KEY XAI_API_KEY"
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
CODEX_LIST=""
cli_available codex && CODEX_LIST=$(codex mcp list 2>/dev/null || echo "")
GEMINI_SETTINGS="${HOME}/.gemini/settings.json"
GEMINI_LIST=""
if [[ -f "${GEMINI_SETTINGS}" ]] && command -v jq >/dev/null 2>&1; then
    GEMINI_LIST=$(jq -r '.mcpServers // {} | keys[]' "${GEMINI_SETTINGS}" 2>/dev/null || echo "")
fi
KIMI_LIST=""
cli_available kimi && KIMI_LIST=$(kimi mcp list 2>&1 | grep -v 'AuthlibDeprecation\|authlib.jose\|It will be compatible\|from authlib' || echo "")
AGY_LIST=""
cli_available agy && AGY_LIST=$(agy mcp list 2>&1 || echo "")

# An absent CLI and a CLI with nothing registered produce the same empty list.
# Report them differently: "not installed" is a known state, whereas printing
# every MCP as "missing" invents a measurement that was never taken.
show_status() {
    local cli="$1"; local list="$2"; local label="$3"
    echo ""
    echo "## ${label}"
    if ! cli_available "${cli}"; then
        echo "  — ${cli} CLI not installed; registration state UNKNOWN (not measured)"
        return
    fi
    for entry in "${MCPS[@]}"; do
        local name="${entry%%|*}"
        if echo "${list}" | grep -Eq "^[[:space:]]*${name}([[:space:]]|$)"; then
            echo "  ✓ ${name}"
        else
            echo "  ✗ ${name} (missing)"
        fi
    done
}

show_status "codex" "${CODEX_LIST}" "Codex CLI"
show_status "gemini" "${GEMINI_LIST}" "Gemini CLI"
show_status "agy" "${AGY_LIST}" "Antigravity CLI (gemini lane)"
show_status "kimi" "${KIMI_LIST}" "Kimi CLI"

# === Optional dependency: Trail of Bits mcp-context-protector ===
#
# The guarded security MCPs (guarded-semgrep, guarded-slither, guarded-solodit)
# are declared in the per-lane CLI configs and each runs as a CHILD of the Trail
# of Bits context-protector wrapper. The wrapper is a ~704 MB third-party
# checkout: it is an install-time dependency and is deliberately never vendored
# into this repository. Its absence must take out exactly those three servers.
CONTEXT_PROTECTOR="${CONTEXT_PROTECTOR:-${VAULT_ROOT}/_state/tooling-arsenal-2026-07-18/sources/mcp-context-protector/mcp-context-protector.sh}"
GUARDED_MCPS="guarded-semgrep guarded-slither guarded-solodit"

show_context_protector_status() {
    echo ""
    echo "## Guarded security MCPs (mcp-context-protector)"
    # The wrapper is a shim that execs .venv/bin/mcp-context-protector inside its
    # own checkout and exits 127 when that entry point is missing. Checking only
    # the shim would report a non-functional install as present, so require the
    # entry point it actually dispatches to.
    local cp_dir cp_entry
    cp_dir="$(dirname "${CONTEXT_PROTECTOR}")"
    cp_entry="${cp_dir}/.venv/bin/mcp-context-protector"
    if [[ -x "${CONTEXT_PROTECTOR}" ]] && [[ -x "${cp_entry}" ]]; then
        echo "  ✓ mcp-context-protector: ${CONTEXT_PROTECTOR}"
        for g in ${GUARDED_MCPS}; do echo "    ✓ ${g} (wrapper present)"; done
        return 0
    fi
    if [[ -x "${CONTEXT_PROTECTOR}" ]] && [[ ! -x "${cp_entry}" ]]; then
        echo "  ✗ mcp-context-protector wrapper found, but its entry point is missing:"
        echo "      ${cp_entry}"
        echo "    The wrapper would exit 127. Its venv is not built."
    elif [[ -e "${CONTEXT_PROTECTOR}" ]]; then
        echo "  ✗ mcp-context-protector present but not executable: ${CONTEXT_PROTECTOR}"
    else
        echo "  ✗ mcp-context-protector not installed at: ${CONTEXT_PROTECTOR}"
    fi
    for g in ${GUARDED_MCPS}; do echo "    — ${g}: UNAVAILABLE (its wrapper is absent)"; done
    echo "  This disables those three servers and nothing else. Every other MCP,"
    echo "  specialist, and lane is unaffected."
    echo "  Install it (never vendored — ~704 MB third-party checkout):"
    echo "    docs/install/security-mcps.md"
    return 1
}

show_context_protector_status || true

if [[ ${STATUS_ONLY} -eq 1 ]]; then
    exit 0
fi

if [[ ${VENV_OK} -eq 0 ]]; then
    echo ""
    echo "WARNING: chrono Python venv not at ${CHRONO_PY}"
    echo "Cannot register the chrono MCP servers without it. Nothing was changed."
    echo "Fix: run 'uv sync' in ${VAULT_ROOT}, then re-run this script."
    exit 0
fi

echo ""
echo "=== Registering missing MCPs ==="
AGY_REGISTRATION_FAILED=0

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

register_agy() {
    local name="$1"; local args_str="$2"; local env_vars="$3"
    if echo "${AGY_LIST}" | grep -Eq "^[[:space:]]*${name}([[:space:]]|$)"; then
        echo "  [agy] ${name}: already registered"
        return
    fi
    # Build one non-empty argv array from the subcommand onward. macOS ships
    # Bash 3.2, where expanding an empty local array under `set -u` raises an
    # unbound-variable error before agy runs.
    local agy_args=("mcp" "add")
    local masked_env=""
    local v val
    for v in ${env_vars}; do
        val="${!v:-}"
        if [[ -n "${val}" ]]; then
            agy_args+=("--env" "${v}=${val}")
            masked_env+=" --env ${v}=*****"
        fi
    done
    # shellcheck disable=SC2206
    local args_arr=(${args_str})
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  [agy] would: agy mcp add${masked_env} ${name} ${CHRONO_PY} ${args_arr[*]}"
        return
    fi
    # agy requires every --env/-e flag before the server name.
    agy_args+=("${name}" "${CHRONO_PY}" "${args_arr[@]}")
    if agy "${agy_args[@]}" >/dev/null 2>&1; then
        echo "  [agy] ${name}: ✓ added"
    else
        echo "  [agy] ${name}: ✗ failed"
        AGY_REGISTRATION_FAILED=1
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
    register_agy "${name}" "${args_str}" "${env_vars}"
    register_kimi "${name}" "${args_str}" "${env_vars}"
done

echo ""
if [[ ${AGY_REGISTRATION_FAILED} -ne 0 ]]; then
    echo "=== agy registration failed. No success claim; inspect a direct sanitized agy error. ==="
    exit 1
fi
echo "=== Done. Re-run with --status to verify. ==="
