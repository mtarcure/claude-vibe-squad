#!/bin/bash
# Install the Vibe Squad launchd routines (LaunchAgents) from the templates in launchd/.
#
# `bin/squad up` refuses to launch until com.vibesquad.daemon is installed and loaded
# (bin/launch-squad.sh:69-72). This script is the supported way to get there.
#
# Usage:
#   bash bin/install-routines.sh                # install required + optional routines, then load
#   bash bin/install-routines.sh --daemon-only  # install only what `squad up` requires
#   bash bin/install-routines.sh --dry-run      # render + validate, change nothing
#   bash bin/install-routines.sh --status       # report installed/loaded state
#   bash bin/install-routines.sh --force        # replace a differing installed plist
#
# To uninstall one agent:
#   launchctl bootout gui/$(id -u)/<label> && rm ~/Library/LaunchAgents/<label>.plist

set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

# Agents `bin/squad up` blocks on. Keep this list in sync with DAEMON_LABEL in bin/launch-squad.sh.
REQUIRED_AGENTS=("com.vibesquad.daemon")
# Installed by default for parity with previous behavior, but not required to launch.
OPTIONAL_AGENTS=("com.claudevibesquad.nightly" "com.vibesquad.weekly-review" "com.vibesquad.dream")

# Test seams. Both default to real behavior; they exist so the install path can be
# exercised without mutating the operator's live launchd session.
LAUNCHAGENTS_DIR="${SQUAD_LAUNCHAGENTS_DIR:-${HOME}/Library/LaunchAgents}"
NO_BOOTSTRAP="${SQUAD_INSTALL_NO_BOOTSTRAP:-0}"

DRY_RUN=0
STATUS_ONLY=0
FORCE=0
DAEMON_ONLY=0

for arg in "$@"; do
    case "${arg}" in
        --dry-run)     DRY_RUN=1 ;;
        --status)      STATUS_ONLY=1 ;;
        --force)       FORCE=1 ;;
        --daemon-only) DAEMON_ONLY=1 ;;
        --help|-h)     sed -n '2,15p' "$0"; exit 0 ;;
        *)
            echo "ERROR: unknown option: ${arg}" >&2
            echo "Run 'bash bin/install-routines.sh --help' for usage." >&2
            exit 2
            ;;
    esac
done

AGENTS=("${REQUIRED_AGENTS[@]}")
if [[ ${DAEMON_ONLY} -eq 0 ]]; then
    AGENTS+=("${OPTIONAL_AGENTS[@]}")
fi

# Test seam: install an explicit label list instead of the built-in sets, so the
# render/install/bootstrap/verify path can be exercised end to end against a
# throwaway label rather than against the live com.vibesquad.daemon.
if [[ -n "${SQUAD_INSTALL_AGENTS:-}" ]]; then
    read -r -a AGENTS <<<"${SQUAD_INSTALL_AGENTS}"
    REQUIRED_AGENTS=("${AGENTS[@]}")
    OPTIONAL_AGENTS=()
fi

LAUNCHD_DOMAIN="gui/$(id -u)"
FAILURES=0
DEGRADED=0

# --- rendering -------------------------------------------------------------

# Render one template to a destination path, then prove the result is installable.
#
# Both __VAULT_ROOT__ and __HOME__ must be substituted even when a template only
# *documents* one of them: the daemon template's own instruction comment contains
# the literal string __HOME__, and bin/launch-squad.sh:74 rejects any installed
# plist matching __[A-Z][A-Z0-9_]*__ anywhere in the file, comments included.
# Substituting only __VAULT_ROOT__ therefore produces a plist the launcher refuses.
render_plist() {
    local src="$1" dest="$2"

    sed -e "s|__VAULT_ROOT__|${VAULT_ROOT}|g" \
        -e "s|__HOME__|${HOME}|g" \
        "${src}" > "${dest}"

    local residual
    if residual=$(LC_ALL=C grep -oE '__[A-Z][A-Z0-9_]*__' "${dest}" | sort -u | tr '\n' ' ') \
       && [[ -n "${residual}" ]]; then
        echo "  ✗ unresolved template token(s) after rendering: ${residual}" >&2
        echo "    bin/launch-squad.sh would refuse to bootstrap this plist." >&2
        return 1
    fi

    if ! plutil -lint "${dest}" >/dev/null 2>&1; then
        echo "  ✗ rendered plist failed plutil validation" >&2
        plutil -lint "${dest}" >&2 || true
        return 1
    fi

    return 0
}

# --- installation ----------------------------------------------------------

install_agent() {
    local label="$1"
    local src="${VAULT_ROOT}/launchd/${label}.plist"
    local target="${LAUNCHAGENTS_DIR}/${label}.plist"

    echo ""
    echo "${label}:"

    if [[ ! -f "${src}" ]]; then
        echo "  ✗ template not found: ${src}" >&2
        FAILURES=$((FAILURES + 1))
        return 1
    fi

    mkdir -p "${LAUNCHAGENTS_DIR}"

    # Render into the destination directory so the final move is a same-filesystem
    # rename, which is atomic: a reader never sees a half-written plist.
    local staged
    staged="$(mktemp "${LAUNCHAGENTS_DIR}/.${label}.plist.XXXXXX")"

    if ! render_plist "${src}" "${staged}"; then
        rm -f "${staged}"
        FAILURES=$((FAILURES + 1))
        return 1
    fi

    if [[ -f "${target}" ]] && cmp -s "${staged}" "${target}"; then
        echo "  ✓ already installed and identical: ${target}"
        rm -f "${staged}"
    elif [[ -f "${target}" ]] && [[ ${FORCE} -eq 0 ]]; then
        # An installed plist that differs may carry operator edits. Refuse rather
        # than silently overwrite; --force is the explicit opt-in.
        echo "  ✗ installed plist differs from the rendered template: ${target}" >&2
        echo "    Re-run with --force to replace it, or diff it first:" >&2
        echo "      diff ${target} <(sed -e 's|__VAULT_ROOT__|${VAULT_ROOT}|g' -e 's|__HOME__|${HOME}|g' ${src})" >&2
        rm -f "${staged}"
        FAILURES=$((FAILURES + 1))
        return 1
    elif [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  [dry-run] would install: ${target}"
        rm -f "${staged}"
    else
        chmod 644 "${staged}"
        mv -f "${staged}" "${target}"
        echo "  ✓ installed: ${target}"
    fi

    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  [dry-run] would load: ${LAUNCHD_DOMAIN}/${label}"
        return 0
    fi

    bootstrap_agent "${label}" "${target}"
}

# --- loading ---------------------------------------------------------------

# Resolve symlinks in a path's directory so two spellings of the same file compare
# equal. launchd reports the physical path (/private/tmp/...), while the path this
# script constructs from $HOME may go through a symlink (/tmp/...); comparing the
# raw strings would report a correctly-installed agent as foreign.
resolve_path() {
    local p="$1" dir base
    dir="$(dirname -- "${p}")"
    base="$(basename -- "${p}")"
    ( cd -- "${dir}" 2>/dev/null && printf '%s/%s\n' "$(pwd -P)" "${base}" ) || printf '%s\n' "${p}"
}

# Echo the plist path launchd actually loaded a label from, or nothing if the
# label is not registered.
#
# The bare exit code of `launchctl print` is NOT a usable liveness signal here.
# launchd is addressed by label over IPC, not through the filesystem, so the query
# answers for whichever session owns this uid regardless of which HOME or
# LaunchAgents directory this script was pointed at. Asking only "is the label
# known?" therefore reports another installation's state as if it were ours. Bind
# the answer to identity instead: compare the path launchd reports against the
# plist we intend to manage.
#
# "Not registered" is an ordinary answer, not a failure. launchctl exits 113 for
# it, and under `set -o pipefail` that status would propagate out of the pipeline
# and trip `set -e`, so absorb it here and let an empty string mean "not loaded".
loaded_plist_path() {
    local service="$1" out
    out="$(launchctl print "${service}" 2>/dev/null || true)"
    printf '%s\n' "${out}" | sed -n 's/^[[:space:]]*path = //p' | head -1
}

bootstrap_agent() {
    local label="$1" target="$2"
    local service="${LAUNCHD_DOMAIN}/${label}"

    if [[ "${NO_BOOTSTRAP}" == "1" ]]; then
        echo "  — not loaded: SQUAD_INSTALL_NO_BOOTSTRAP=1 (plist is installed and valid)"
        return 0
    fi

    if ! command -v launchctl >/dev/null 2>&1; then
        echo "  ⚠ launchctl unavailable — plist installed but NOT loaded" >&2
        DEGRADED=$((DEGRADED + 1))
        return 0
    fi

    local live
    live="$(loaded_plist_path "${service}")"
    if [[ -n "${live}" ]]; then
        if [[ "$(resolve_path "${live}")" == "$(resolve_path "${target}")" ]]; then
            echo "  ✓ already loaded: ${service}"
            return 0
        fi
        # Same label, different file. Booting ours in would silently displace an
        # installation this script does not own, so stop and say so.
        echo "  ✗ ${label} is already loaded from a DIFFERENT plist" >&2
        echo "      loaded: ${live}" >&2
        echo "      wanted: ${target}" >&2
        echo "    Not bootstrapping over it. Unload the other one first:" >&2
        echo "      launchctl bootout ${service}" >&2
        FAILURES=$((FAILURES + 1))
        return 1
    fi

    local rc=0
    launchctl bootstrap "${LAUNCHD_DOMAIN}" "${target}" || rc=$?

    # Verify by observation rather than by the bootstrap exit code: bootstrap
    # returns non-zero for "already loaded" races, and a zero exit is not by
    # itself proof the job is registered from the plist we just installed.
    live="$(loaded_plist_path "${service}")"
    if [[ -n "${live}" ]] && [[ "$(resolve_path "${live}")" == "$(resolve_path "${target}")" ]]; then
        if [[ ${rc} -ne 0 ]]; then
            echo "  ✓ loaded: ${service} (bootstrap returned ${rc}, job is registered)"
        else
            echo "  ✓ loaded: ${service}"
        fi
        return 0
    fi

    echo "  ✗ bootstrap failed (rc=${rc}) and ${service} is not registered" >&2
    echo "    Inspect with: launchctl print ${service}" >&2
    FAILURES=$((FAILURES + 1))
    return 1
}

# --- status ----------------------------------------------------------------

report_status() {
    local label required="$1"
    shift
    for label in "$@"; do
        local target="${LAUNCHAGENTS_DIR}/${label}.plist"
        local installed="missing" loaded="not loaded" live=""
        [[ -f "${target}" ]] && installed="installed"
        if ! command -v launchctl >/dev/null 2>&1; then
            loaded="unknown"
        else
            live="$(loaded_plist_path "${LAUNCHD_DOMAIN}/${label}")"
            if [[ -z "${live}" ]]; then
                loaded="not loaded"
            elif [[ "$(resolve_path "${live}")" == "$(resolve_path "${target}")" ]]; then
                loaded="loaded"
            else
                # Registered under this label, but from a plist we do not manage.
                # Reporting that as "loaded" would credit us with another
                # installation's state.
                loaded="foreign"
                FOREIGN_NOTES+=("${label} is loaded from ${live}, not ${target}")
            fi
        fi
        printf '  %-38s %-10s %-10s %s\n' "${label}" "${installed}" "${loaded}" "${required}"
    done
}

if [[ ${STATUS_ONLY} -eq 1 ]]; then
    FOREIGN_NOTES=()
    echo "LaunchAgents dir: ${LAUNCHAGENTS_DIR}"
    echo "launchd domain:   ${LAUNCHD_DOMAIN}"
    echo ""
    printf '  %-38s %-10s %-10s %s\n' "LABEL" "PLIST" "LAUNCHD" "ROLE"
    report_status "required by 'squad up'" "${REQUIRED_AGENTS[@]}"
    # Guard the expansion: macOS ships bash 3.2, where "${empty[@]}" under
    # `set -u` is an unbound-variable error rather than zero arguments.
    if [[ ${#OPTIONAL_AGENTS[@]} -gt 0 ]]; then
        report_status "optional" "${OPTIONAL_AGENTS[@]}"
    fi
    if [[ ${#FOREIGN_NOTES[@]} -gt 0 ]]; then
        echo ""
        echo "  'foreign' means launchd knows the label, but from a plist outside"
        echo "  ${LAUNCHAGENTS_DIR}. That is another installation's state, not this one's:"
        printf '    - %s\n' "${FOREIGN_NOTES[@]}"
    fi
    exit 0
fi

# --- main ------------------------------------------------------------------

echo "Installing Vibe Squad launchd routines"
echo "  vault root:       ${VAULT_ROOT}"
echo "  LaunchAgents dir: ${LAUNCHAGENTS_DIR}"
echo "  launchd domain:   ${LAUNCHD_DOMAIN}"
[[ ${DRY_RUN} -eq 1 ]] && echo "  mode:             dry run (nothing will be changed)"

if [[ ${DRY_RUN} -eq 0 ]]; then
    # These files are tracked as non-executable, so this leaves the working tree
    # dirty with mode-only changes (measured: 34 files, zero content changes).
    # Say so rather than letting a later `git status` look like unexplained drift.
    echo "  note:             making bin/ and scripts/ executable (mode-only git changes)"
    chmod +x "${VAULT_ROOT}/bin/"*.sh 2>/dev/null || true
    chmod +x "${VAULT_ROOT}/scripts/python/"*.py 2>/dev/null || true
    chmod +x "${VAULT_ROOT}/scripts/"*.sh 2>/dev/null || true
fi

# Pre-warm the uv ephemeral env cache for vibecoding-check + content-processing.
# Without this, the first run from a sandboxed CLI (Codex's workspace-write,
# launchd's restricted env) hangs on DNS while uv tries to fetch deps.
# Optional: an absent or offline uv degrades to a slower first run, nothing else.
if [[ ${DRY_RUN} -eq 0 ]]; then
    echo ""
    if ! command -v uv >/dev/null 2>&1; then
        echo "⚠ uv not found — skipping cache pre-warm; the first nightly run will fetch its deps."
        DEGRADED=$((DEGRADED + 1))
    else
        echo "Pre-warming uv cache..."
        if UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" uv run --quiet --no-project \
            --with pyyaml --with httpx --with feedparser --with trafilatura \
            python -c "import yaml, httpx, feedparser, trafilatura" 2>/dev/null; then
            echo "  ✓ pyyaml, httpx, feedparser, trafilatura cached"
        else
            echo "  ⚠ uv cache pre-warm failed (offline?) — first script run will fetch"
            DEGRADED=$((DEGRADED + 1))
        fi
    fi
fi

for label in "${AGENTS[@]}"; do
    install_agent "${label}" || true
done

echo ""
if [[ ${FAILURES} -gt 0 ]]; then
    echo "✗ ${FAILURES} agent(s) failed to install. 'bin/squad up' will refuse to launch"
    echo "  until com.vibesquad.daemon is installed and loaded."
    exit 1
fi

if [[ ${DRY_RUN} -eq 1 ]]; then
    echo "✓ Dry run complete: every template rendered, resolved, and passed plutil."
    exit 0
fi

echo "✓ Vibe Squad launchd routines installed"
[[ ${DEGRADED} -gt 0 ]] && echo "  (${DEGRADED} optional step(s) degraded — see warnings above)"
echo ""
echo "Verify:  bash bin/install-routines.sh --status"
echo "Launch:  bin/squad doctor && bin/squad up"
exit 0
