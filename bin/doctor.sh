#!/bin/bash
# Claude-Vibe-Squad doctor — health check + token-bleed detection.
# Verifies environment, reports anomalies. Surfaced in morning brief.
#
# Phases:
#   1. CLI presence on this HOME's PATH (Claude / Codex / Gemini / Kimi)
#      (presence ONLY; login/auth state is deliberately NOT verified — the
#      program logs in to nothing and says so, see the auth note in Phase 1)
#   2. MCP servers reachable from each CLI
#   3. Secrets sourced
#   4. Private memory vault root + runtime repository accessible (resolves the
#      vault-root sentinel/path; it does NOT probe a live Obsidian REST API)
#   5. Persistent browser session alive
#   6. Disk space (>15% free)
#   7. tmux sessions present (the check counts sessions; the four
#      persistent model-lane panes were retired at the Phase-3 cutover)
#   8. Token-bleed proxy: LLM-artifact volume vs its 7-day average, plus the
#      24h dispatch-log count (there is NO per-CLI token counter — the per-pane
#      report was retired with the persistent-lane architecture)
#   9. Specialist dispatch volume last 24h
#   10. Process audit (long-running, orphaned)
#   11. Log/transcript volume audit
#
# Every status below has five possible values, not two -- see "Result
# vocabulary". A check that could not run reports COULD NOT DETERMINE and is
# never counted healthy; a check whose input this distribution does not carry
# reports NOT APPLICABLE. Adding a check means choosing all of its states.

set -uo pipefail

# launchd's spawn shell doesn't include ~/.local/bin (where claude + kimi live).
# Prepend it so CLI presence checks work the same as in operator's interactive shell.
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

check_private_vault_root() {
    PYTHONPATH="${VAULT_ROOT}/plugins/chrono-vault" python3 -B - <<'PY'
import sys
from vaultroot import VaultRootError, resolve_vault_root
try:
    resolve_vault_root()
except VaultRootError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
PY
}
if [[ "${1:-}" == "--check-private-vault-root" ]]; then
    check_private_vault_root
    exit $?
fi

# Root-independent durable state. Resolve this from the script's physical home,
# not VAULT_ROOT: the latter may be the broken path this run needs to report.
# shellcheck source-path=SCRIPTDIR source=doctor-log-home.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")" && pwd -P)/doctor-log-home.sh" || exit $?

DATE="$(date -u +%Y-%m-%d)"
DOCTOR_LOG="${CHRONO_DOCTOR_LOG_DIR}/${DATE}.md"
SUMMARY="${CHRONO_DOCTOR_LOG_DIR}/${DATE}-summary.json"

mkdir -p "$(dirname "${DOCTOR_LOG}")"

# Initialize report
cat > "${DOCTOR_LOG}" <<EOF
# Doctor Report — ${DATE}

Run at: $(date -u +%FT%TZ)

EOF

# --- Result vocabulary ------------------------------------------------------
# Every status this program prints has more than two possible values. The
# missing ones cost a release rehearsal: the process audit received three
# `/bin/ps: Operation not permitted` errors and printed "No long-running CLI
# processes detected", because a DENIED check and a CLEAN check produce the
# same empty output. Worse, the denied run looked *healthier* than the working
# one -- it lost a warning the working run had raised.
#
#   HEALTHY   the check ran and the thing is good                          OK
#   WARNINGS  the check ran; needs attention, or is simply not configured  WARN
#   ISSUES    the check ran and the thing is broken            ISSUE (gates exit 1)
#   UNKNOWNS  the check COULD NOT RUN. Never healthy, never a pass.        UNKNOWN
#   SKIPPED   the check does not apply to THIS distribution                N/A
#
# UNKNOWN and SKIPPED are different claims and must not be merged. "I could not
# measure this" is a defect in the health report; "this tree never carried the
# input" is a fact about the projection. The split mirrors bin/test's
# PASS/FAIL/BLOCKED/SKIP, which already draws the same line for test suites.
#
# ISSUES gate with exit 1. Most optional UNKNOWNs remain report-only: a first
# run has no secrets file or private vault, and treating setup as failure teaches
# users to ignore the exit code. A small set of mandatory integrity checks use
# GATE_UNKNOWN_LIST instead when an input EXISTS but cannot be read or
# enumerated, so doctor exits 2. A present, readable, empty target is the
# positive clean control and exits 0. An input that its producer has never
# created is the zero-state case below: still unknown and visible, but not a
# launch blocker. That keeps "broken", "clean", "absent", and "unreadable"
# distinct.
#
# ABSENT_INPUTS is the REPORTING split for producer-created inputs that do not
# exist yet (for example a browser keep-alive summary or the first dispatch
# ledger). It routes through note_unknown, stays loud and can never be counted
# healthy, but does not make first launch depend on state only later activity
# can create. Once an input exists, missing jq, malformed data, or a failed find
# uses note_gate_unknown and the exit-2 path.
ISSUES=()
WARNINGS=()
HEALTHY=()
UNKNOWNS=()
SKIPPED=()
ABSENT_INPUTS=()
# A count alone could not tell a reader WHICH unknowns were the gating ones, so
# the blocked user had no way to act on the exit code. Keep the list.
GATE_UNKNOWN_LIST=()

# Each helper takes the short summary phrase and, optionally, a longer report
# line. Routing every status through these is what makes the five states
# countable; an inline `echo` into the log is invisible to the summary.
note_ok()      { HEALTHY+=("$1");  printf -- '- \xe2\x9c\x93 %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_warn()    { WARNINGS+=("$1"); printf -- '- \xe2\x9a\xa0\xef\xb8\x8f %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_issue()   { ISSUES+=("$1");   printf -- '- \xf0\x9f\x94\x94 %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_unknown() { UNKNOWNS+=("$1"); printf -- '- ? COULD NOT DETERMINE: %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_gate_unknown() {
    note_unknown "$@"
    GATE_UNKNOWN_LIST+=("$1")
}
# The input this check needs has not been produced yet. Loud, never a pass,
# never healthy -- and never a launch blocker. See the vocabulary note above for
# why this is not a weakened check: the moment the input exists, any failure to
# read it goes back through note_gate_unknown and exits 2.
note_absent_input() {
    note_unknown "$@"
    ABSENT_INPUTS+=("$1")
}
note_skip()    { SKIPPED+=("$1");  printf -- '- \xe2\x97\x8b not applicable here: %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_info()    { printf -- '- \xe2\x84\xb9\xef\xb8\x8f %s\n' "$1" >> "${DOCTOR_LOG}"; }

# --- Tool liveness probes ---------------------------------------------------
# Presence on PATH is not usability. Each probe asks the tool a question whose
# right answer this script already knows, so an installed-but-denied tool
# cannot pass for a working one. A tool that silently failed and a tool that
# found nothing print the same empty output; only a positive control separates
# them.

# ps must be able to name this very process.
PS_USABLE=false
PS_DENIED_REASON=""
if command -v ps >/dev/null 2>&1; then
    if _ps_self="$(ps -o pid= -p "$$" 2>&1)" \
        && [[ "${_ps_self//[[:space:]]/}" == "$$" ]]; then
        PS_USABLE=true
    else
        PS_DENIED_REASON="$(printf '%s' "${_ps_self}" | head -1 | tr -d '\n')"
        [[ -n "${PS_DENIED_REASON}" ]] \
            || PS_DENIED_REASON="ps did not report this process"
    fi
else
    PS_DENIED_REASON="ps is not on PATH"
fi
unset _ps_self

# grep must find a string this script just produced.
GREP_USABLE=false
if command -v grep >/dev/null 2>&1 \
    && printf 'doctor-grep-canary\n' | grep -q 'doctor-grep-canary' 2>/dev/null; then
    GREP_USABLE=true
fi

# git must be able to answer questions about THIS tree, not merely exist.
GIT_USABLE=false
if command -v git >/dev/null 2>&1 \
    && git -C "${VAULT_ROOT}" rev-parse --git-dir >/dev/null 2>&1; then
    GIT_USABLE=true
fi

# Classify a file this program's own checks depend on. The public projection
# deliberately withholds several private inputs (tools/export/policy/
# path-policy.json), so a check needing one of them is NOT APPLICABLE in a
# projected tree. It is not failed, and its subject is certainly not healthy.
#
#   present      the file is here
#   missing      git tracks it in THIS tree, so it should be here and is not
#   unpublished  git does not track it here: this distribution never carried it
#   unknown      git could not answer, so neither of the above is established
#
# Keying on git rather than on a hardcoded list of "public" paths keeps the two
# facts in one home: the policy decides what ships, and this reads back what
# actually shipped. A path can move between distributions without editing here.
classify_dependency() {
    local rel="$1"
    if [[ -e "${VAULT_ROOT}/${rel}" ]]; then
        printf 'present\n'
    elif [[ "${GIT_USABLE}" != true ]]; then
        printf 'unknown\n'
    elif git -C "${VAULT_ROOT}" ls-files --error-unmatch -- "${rel}" \
        >/dev/null 2>&1; then
        printf 'missing\n'
    else
        printf 'unpublished\n'
    fi
}

# macOS ships no coreutils `timeout`, and a lane CLI that hangs on --version
# must not hang the health report. Only the PID this function started is ever
# signalled: the process table is shared with every other lane on this host,
# so a pattern-matched kill would reap siblings.
run_bounded() {
    local seconds="$1" outfile="$2"
    shift 2
    local pid watchdog rc=0
    "$@" >"${outfile}" 2>/dev/null &
    pid=$!
    ( sleep "${seconds}"; kill -TERM "${pid}" 2>/dev/null ) >/dev/null 2>&1 &
    watchdog=$!
    wait "${pid}" 2>/dev/null || rc=$?
    kill -TERM "${watchdog}" 2>/dev/null
    wait "${watchdog}" 2>/dev/null || true
    return "${rc}"
}

# --- 1. CLI presence + login ---
# Resolved on THIS HOME's PATH, which is the only question a health report can
# honestly answer for the person reading it.
#
# The dispatch rail resolves lane executables from the effective-UID passwd
# home (scripts/python/seatbelt_profile.py: HOST_HOME -> LANE_CLI_PATHS). That
# is correct where it lives -- a seatbelt profile has to name a fixed inode,
# and board spawns legitimately run with a $HOME that differs from the account
# home -- and wrong as an answer to "what did YOU install". Under a fresh HOME
# it reported the MAINTAINER's four CLIs as this installation's, while
# bin/mcp-audit.sh, which honours the temporary PATH, reported two of them
# absent: two checks in one program disagreeing about the same machine, with
# the wrong one printing the reassuring answer.
#
# Doctor now answers the HOME question itself, and reports the rail's answer
# below as provenance plus an explicit DISAGREEMENT line, instead of silently
# preferring one of the two.
echo "## CLI Status" >> "${DOCTOR_LOG}"
echo "" >> "${DOCTOR_LOG}"
echo "Resolved on this HOME's PATH (HOME=${HOME:-<unset>})." >> "${DOCTOR_LOG}"

CLI_PROBE_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-cli.XXXXXXXX" 2>/dev/null)" \
    || CLI_PROBE_OUT=""
for lane in claude codex gemini kimi; do
    lane_path="$(command -v "${lane}" 2>/dev/null || true)"
    if [[ -z "${lane_path}" ]]; then
        # Not installed is a setup step, not a fault: a clean install has none
        # of these yet and must still exit 0.
        note_warn "${lane} CLI not installed for this HOME" \
            "${lane}: not on this HOME's PATH — install it, or put it on PATH"
        continue
    fi
    if [[ -z "${CLI_PROBE_OUT}" ]]; then
        note_unknown "${lane} version probe had nowhere to write" \
            "${lane}: found at ${lane_path}, but no writable temp file for the probe"
        continue
    fi
    if run_bounded 10 "${CLI_PROBE_OUT}" "${lane_path}" --version; then
        lane_version="$(head -1 "${CLI_PROBE_OUT}" 2>/dev/null | tr -d '\r' | cut -c1-120)"
        if [[ -n "${lane_version}" ]]; then
            note_ok "${lane} CLI installed for this HOME" \
                "${lane}: ${lane_path} — ${lane_version}"
        else
            note_unknown "${lane} version probe returned nothing" \
                "${lane}: ${lane_path} ran but printed no version"
        fi
    else
        note_unknown "${lane} version probe failed or timed out" \
            "${lane}: ${lane_path} exists but did not answer --version within 10s"
    fi
done
[[ -n "${CLI_PROBE_OUT}" ]] && rm -f "${CLI_PROBE_OUT}"

# An auth CLASS is not an auth RESULT. "this lane uses subscription auth" is a
# statement about policy; a first-time user reads it as "you are logged in".
# Doctor logs in to nothing and spends no tokens, so the authentication state
# of every lane is UNDETERMINED here -- said once, plainly, rather than implied
# four times by a reassuring `auth=` field.
echo "" >> "${DOCTOR_LOG}"
note_unknown "CLI authentication state is not verified by doctor" \
    "Authentication: NOT VERIFIED for any lane. The auth-policy values below say how a lane is *meant* to authenticate; they are not evidence that you are authenticated. Run each CLI once to confirm."

echo "" >> "${DOCTOR_LOG}"
echo "Dispatch-rail view (authority paths the board will actually exec):" >> "${DOCTOR_LOG}"
DOCTOR_EUID_HOME=""
if command -v python3 >/dev/null 2>&1; then
    DOCTOR_EUID_HOME="$(python3 -B - <<'PY' 2>/dev/null || true
import os
import pwd

print(pwd.getpwuid(os.geteuid()).pw_dir)
PY
)"
fi
if [[ -z "${DOCTOR_EUID_HOME}" ]]; then
    note_unknown "dispatch lane inventory not probed: effective-UID account home is unknown" \
        "the dispatch rail resolves executable authority from the effective-UID account home, but doctor could not resolve that home safely"
elif [[ "${HOME:-}" != "${DOCTOR_EUID_HOME}" ]]; then
    # A clean-room HOME must not gain capabilities from the account that happens
    # to execute the rehearsal. lane-inventory resolves Claude/Kimi from the
    # passwd home, so invoking it here would execute another home's binaries and
    # contaminate the very check doctor is meant to perform.
    note_unknown "dispatch lane inventory not probed: HOME differs from effective-UID account home" \
        "authority-path cross-check NOT RUN because HOME=${HOME:-<unset>} while the effective-UID account home is ${DOCTOR_EUID_HOME}; probing it would import state from outside this HOME"
elif LANE_INVENTORY=$(PYTHONPATH="${VAULT_ROOT}/scripts/python" python3 -B \
    "${VAULT_ROOT}/scripts/python/dispatch_context_builder.py" lane-inventory \
    --repo-root "${VAULT_ROOT}" 2>/dev/null) && [[ -n "${LANE_INVENTORY}" ]]; then
    CLI_DISAGREEMENTS=0
    while IFS=$'\t' read -r lane installed literal resolved version auth selections; do
        [[ -n "${lane}" ]] || continue
        echo "- ${lane}: authority=${literal}; resolves_to=${resolved}; present_there=${installed}; version=${version:-unavailable}; auth-policy=${auth} (policy class, NOT an authentication result); profiles/models=${selections}" >> "${DOCTOR_LOG}"
        here="$(command -v "${lane}" 2>/dev/null || true)"
        if [[ -n "${here}" && "${here}" != "${literal}" ]]; then
            CLI_DISAGREEMENTS=$((CLI_DISAGREEMENTS + 1))
            note_warn "${lane}: this HOME's PATH and the dispatch authority path disagree" \
                "  ⚠️ this HOME resolves ${lane} to ${here}, but dispatch will exec ${literal}"
        elif [[ -z "${here}" && "${installed}" == true ]]; then
            CLI_DISAGREEMENTS=$((CLI_DISAGREEMENTS + 1))
            note_warn "${lane}: dispatch authority sees a CLI this HOME does not" \
                "  ⚠️ ${lane} is absent from this HOME's PATH but present at the authority path ${literal} — that is another account's install, not yours"
        fi
    done <<< "${LANE_INVENTORY}"
    if [[ "${CLI_DISAGREEMENTS}" -eq 0 ]]; then
        note_ok "PATH and dispatch authority agree on every lane"
    fi
else
    # Formerly an ISSUE. A rail inventory that will not run tells us nothing
    # about the lanes; it is an unmeasured cross-check, not a broken install.
    note_unknown "dispatch lane inventory could not be resolved" \
        "the dispatch rail's lane inventory did not return — the authority-path cross-check did not run"
fi
unset DOCTOR_EUID_HOME

# --- 2. MCP reachability — invoke bootstrap-mcps.sh in --status mode ---
echo "" >> "${DOCTOR_LOG}"
echo "## MCP Servers" >> "${DOCTOR_LOG}"
if [[ ! -f "${VAULT_ROOT}/scripts/bootstrap-mcps.sh" ]]; then
    note_unknown "MCP registration status could not be read" \
        "scripts/bootstrap-mcps.sh is absent — MCP registration state is UNKNOWN"
elif [[ "${GREP_USABLE}" != true ]]; then
    note_unknown "MCP registration status could not be parsed" \
        "grep is unavailable, so the --status rows could not be read"
else
    mcp_status_rc=0
    mcp_status_raw="$(bash "${VAULT_ROOT}/scripts/bootstrap-mcps.sh" --status 2>/dev/null)" \
        || mcp_status_rc=$?
    mcp_status=$(printf '%s\n' "${mcp_status_raw}" | grep -E '^[[:space:]]+[✓✗]' || true)
    if [[ -z "${mcp_status}" ]]; then
        # Formerly "MCP status indeterminate" as a WARNING, which reads like a
        # finding. It is not a finding; it is the absence of one.
        note_unknown "MCP registration status returned no rows" \
            "bootstrap-mcps.sh --status exited ${mcp_status_rc} and listed no server — registration state is UNKNOWN, not clean"
    else
        missing=$(printf '%s\n' "${mcp_status}" | grep -c '✗' | tr -d ' ')
        total=$(printf '%s\n' "${mcp_status}" | wc -l | tr -d ' ')
        if [[ ${missing} -eq 0 ]]; then
            note_ok "MCPs registered" "All MCPs registered across CLIs (${total} total)"
        else
            note_warn "${missing} MCP registrations missing — run scripts/bootstrap-mcps.sh" \
                "${missing}/${total} MCP registrations missing"
        fi
    fi
fi

# bin/mcp-audit.sh prints exactly one `summary: issues=N warnings=N log=...`
# line when it completes, then exits 0/1 on the issue count. No summary line
# means it did not finish -- which is not the same as finishing with findings,
# and is nothing like passing. Keying on the line rather than on the exit
# status alone is what separates the two.
if [[ ! -x "${VAULT_ROOT}/bin/mcp-audit.sh" ]]; then
    note_unknown "MCP usability audit could not run" \
        "bin/mcp-audit.sh is missing or not executable — MCP usability is UNKNOWN"
else
    mcp_audit_rc=0
    MCP_AUDIT_RAW="$("${VAULT_ROOT}/bin/mcp-audit.sh" 2>/dev/null)" || mcp_audit_rc=$?
    MCP_AUDIT_OUTPUT="$(printf '%s\n' "${MCP_AUDIT_RAW}" | grep -E '^summary: ' | tail -1)"
    if [[ -z "${MCP_AUDIT_OUTPUT}" ]]; then
        note_unknown "MCP usability audit did not complete" \
            "bin/mcp-audit.sh exited ${mcp_audit_rc} without a summary line — usability is UNKNOWN"
    elif [[ "${mcp_audit_rc}" -eq 0 ]]; then
        note_ok "MCP usability audit passed" \
            "MCP usability audit passed (${MCP_AUDIT_OUTPUT})"
    else
        note_warn "MCP usability audit reported registered/unusable drift" \
            "MCP usability audit reported issues (${MCP_AUDIT_OUTPUT})"
    fi
fi

# --- 2b. Product hygiene + memory discipline ---
echo "" >> "${DOCTOR_LOG}"
echo "## Product Hygiene" >> "${DOCTOR_LOG}"
# bin/product-hygiene.sh already distinguishes three outcomes and doctor used
# to collapse two of them: 0 = clean, 1 = real blockers found, 2 = COULD NOT
# RUN (its policy or the private identifier denylist is unavailable). Reporting
# 2 as "hygiene blockers present" turned "we could not scan" into "we scanned
# and found problems" -- and the normal state of a public projection is exactly
# 2, because the denylist is withheld by design.
if [[ ! -x "${VAULT_ROOT}/bin/product-hygiene.sh" ]]; then
    note_unknown "public export hygiene could not run" \
        "bin/product-hygiene.sh is missing or not executable — export hygiene is UNKNOWN"
else
    hygiene_rc=0
    HYGIENE_RAW="$("${VAULT_ROOT}/bin/product-hygiene.sh" --public-export 2>&1)" \
        || hygiene_rc=$?
    HYGIENE_TAIL="$(printf '%s\n' "${HYGIENE_RAW}" | tail -2 | tr '\n' ' ')"
    case "${hygiene_rc}" in
        0)
            note_ok "public export hygiene clean" \
                "Public export has no tracked runtime/private blockers (${HYGIENE_TAIL})"
            ;;
        1)
            note_warn "public export hygiene blockers present — run bin/product-hygiene.sh --public-export" \
                "Public export hygiene found tracked blockers (${HYGIENE_TAIL})"
            ;;
        2)
            # DECISION (2026-08-11) on the private identifier denylist: it stays
            # PRIVATE, and doctor stops treating its absence as a finding. The
            # file lists the private identifiers the export must strip, so
            # publishing it publishes precisely what it exists to hide. The
            # consequence is that this scan cannot run in a public tree, and
            # the honest report of that is "not applicable", never a warning
            # about blockers nobody looked for.
            if [[ "$(classify_dependency '_state/repo-split-2026-07-16/identifier-denylist.txt')" == unpublished ]]; then
                note_skip "public export hygiene needs the private identifier denylist, which this distribution does not carry" \
                    "Public export hygiene does not apply here: it requires the private identifier denylist, withheld from public projections by design (${HYGIENE_TAIL})"
            else
                note_unknown "public export hygiene could not run (exit 2)" \
                    "Public export hygiene could not run: ${HYGIENE_TAIL}"
            fi
            ;;
        *)
            note_unknown "public export hygiene exited ${hygiene_rc}, outside its 0/1/2 contract" \
                "Public export hygiene exited ${hygiene_rc} (${HYGIENE_TAIL})"
            ;;
    esac
fi

echo "" >> "${DOCTOR_LOG}"
echo "## Instruction Drift" >> "${DOCTOR_LOG}"
DRIFT_HITS=0
DRIFT_SCANNED=false
# A missing grep used to leave DRIFT_HITS at 0 and print the clean line: the
# scan that never happened reported as the scan that found nothing.
if [[ "${GREP_USABLE}" == true ]]; then
    DRIFT_PATHS=("${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/docs" "${VAULT_ROOT}/shared")
    for _drift_path in "${DRIFT_PATHS[@]}"; do
        [[ -e "${_drift_path}" ]] && DRIFT_SCANNED=true
    done
    unset _drift_path
    SPECIALIST_COUNT=$(awk -F '\t' 'NR > 1 && $1 != "" {count++} END {print count + 0}' \
        "${VAULT_ROOT}/shared/specialist-runtime-map.tsv" 2>/dev/null)
    STALE_COUNT_HITS=$(grep -RInE '[0-9][0-9]+ specialists' "${DRIFT_PATHS[@]}" 2>/dev/null \
        | grep -v 'bin/upgrade-specialists.py' \
        | awk -v expected="${SPECIALIST_COUNT:-0}" '
            {
                text = $0
                while (match(text, /[0-9][0-9]+ specialists/)) {
                    value = substr(text, RSTART, RLENGTH)
                    sub(/ specialists$/, "", value)
                    if ((value + 0) != expected) {
                        hits++
                        break
                    }
                    text = substr(text, RSTART + RLENGTH)
                }
            }
            END {print hits + 0}
        ')
    OTHER_DRIFT_HITS=$(grep -RInE 'scripts/send-req\.sh|currently has FILL placeholders|<FILL:|docs/handoffs/[0-9]{4}-|docs/specs/spec-[0-9]|docs/plans/[0-9]{4}-' \
        "${DRIFT_PATHS[@]}" 2>/dev/null \
        | awk '!/bin\/upgrade-specialists.py/ {count++} END {print count + 0}')
    DRIFT_HITS=$((STALE_COUNT_HITS + OTHER_DRIFT_HITS))
fi
if [[ "${DRIFT_SCANNED}" != true ]]; then
    note_unknown "instruction drift scan did not run" \
        "no instruction surface was readable (grep usable=${GREP_USABLE}) — drift is UNKNOWN, not clean"
elif [[ "${DRIFT_HITS:-0}" -eq 0 ]]; then
    note_ok "instruction drift clean" \
        "No stale count/FILL/script/spec-handoff references in public instruction surfaces"
else
    note_warn "instruction drift hits: ${DRIFT_HITS}" \
        "${DRIFT_HITS} stale instruction-reference hit(s); run bin/product-hygiene.sh --public-export for details"
fi

# The full gate asserts BOTH that the repository's specialist/routing content is
# coherent AND that every capability a specialist claims is live on this host's
# PATH. On a host that has not installed the arsenal -- a fresh clone, or a
# rehearsal under a temporary PATH -- the second half fails hundreds of times
# and says nothing whatever about the repository. Measured 2026-08-11 under a
# temp HOME: full gate exit 1 with 255 `capability claims host-PATH evidence
# but is absent from PATH` diagnostics, while the host-independent subset
# exited 0. Doctor reported that as "specialist/routing validation failed".
#
# SQUAD_CI_HOST_INDEPENDENT=1 is the discriminator the script already exposes:
# when the subset passes and the full gate does not, the difference is host
# evidence, so the live half is UNDETERMINED here and the content half passed.
#
# It also has its own could-not-run code, which doctor used to discard.
# scripts/python/validate_capability_homes.py returns 2 from its configuration
# handler and 1 only when it has real diagnostics, and bin/validate-specialists.sh
# propagates that verbatim. Exit 2 is the normal state of a public projection:
# the gate reads shared/registries/skill-tool-registry.tsv, which is withheld.
#
# DECISION (2026-08-11) on that registry: it stays PRIVATE. Its verified_state,
# lanes, evidence and notes columns are a census of what works on OUR machines
# plus the gotchas that cost us campaigns; publishing it hands over the arsenal
# rather than the method. A published substitute already exists and is generated
# from it -- tools/export/build_public_catalog.py emits
# shared/registries/recommended-toolchain.tsv, which carries name, purpose,
# technique class and target class and no liveness at all. validate_specialists.py
# already downgrades its absence to the non-fatal `registry-not-published`
# warning; doctor now agrees with it instead of reporting a failure.
report_specialist_gate_unavailable() {
    if [[ "$(classify_dependency 'shared/registries/skill-tool-registry.tsv')" == unpublished ]]; then
        note_skip "specialist/routing validation needs the private tool registry, which this distribution does not carry" \
            "Specialist/routing validation does not apply here: it reads shared/registries/skill-tool-registry.tsv, withheld from public projections by design (see shared/registries/recommended-toolchain.tsv)"
    else
        note_unknown "specialist/routing validation could not run (exit 2: configuration)" \
            "Specialist/routing validation could not run — a required input was unavailable"
    fi
}

if [[ ! -x "${VAULT_ROOT}/bin/validate-specialists.sh" ]]; then
    note_unknown "specialist/routing validation could not run" \
        "bin/validate-specialists.sh is missing or not executable — routing validity is UNKNOWN"
else
    specialist_gate_rc=0
    "${VAULT_ROOT}/bin/validate-specialists.sh" >/dev/null 2>&1 || specialist_gate_rc=$?
    case "${specialist_gate_rc}" in
        0)
            note_ok "specialist/routing validation passed" \
                "Specialist, routing, and generated-adapter validation passed"
            ;;
        2)
            report_specialist_gate_unavailable
            ;;
        1)
            # Real diagnostics, or merely this host's PATH. Re-run the subset to
            # tell them apart rather than guessing.
            specialist_subset_rc=0
            SQUAD_CI_HOST_INDEPENDENT=1 "${VAULT_ROOT}/bin/validate-specialists.sh" \
                >/dev/null 2>&1 || specialist_subset_rc=$?
            case "${specialist_subset_rc}" in
                0)
                    note_ok "specialist/routing content validation passed" \
                        "Specialist, routing, and generated-adapter CONTENT validation passed"
                    note_unknown "live capability evidence unavailable on this host" \
                        "The live-capability half of the gate could not be established on this host's PATH; repository content itself validated clean"
                    ;;
                2)
                    report_specialist_gate_unavailable
                    ;;
                *)
                    note_warn "specialist/routing validation failed" \
                        "Specialist/routing validation failed on the host-independent subset too; see bin/validate-specialists.sh output"
                    ;;
            esac
            ;;
        *)
            note_unknown "specialist/routing validation exited ${specialist_gate_rc}, outside its 0/1/2 contract"
            ;;
    esac
fi

# --- Externally-registered entry points ---------------------------------
# Scripts invoked by launchd have NO in-repo caller, so `git grep` calls them
# dead. A 2026-08-06 audit did exactly that for bin/squad-monitor.sh, which runs
# every 120 seconds via com.chrono.squad-monitor. Six repo scripts are bound
# this way; surfacing the mapping here makes it visible from a health run rather
# than only from ~/Library/LaunchAgents. It also catches the inverse -- a
# registered job whose script no longer exists -- which previously appeared only
# as a silent "No such file or directory" in a log nobody reads.
#
# Matched on the repo-relative TAIL, not on an absolute VAULT_ROOT prefix: under
# a git worktree VAULT_ROOT is the worktree, so a prefix match silently reports
# zero and the check quietly stops checking.
REGISTERED_MISSING=0
REGISTERED_COUNT=0
PLIST_COUNT=0
PLIST_UNREADABLE=0
for plist in "${HOME}"/Library/LaunchAgents/*.plist; do
    [[ -e "$plist" ]] || continue
    PLIST_COUNT=$((PLIST_COUNT + 1))
    # A plutil that cannot read a plist yields the same empty path list as a
    # plist that registers no repo script. Count the failures separately.
    if ! plist_dump="$(plutil -p "$plist" 2>/dev/null)"; then
        PLIST_UNREADABLE=$((PLIST_UNREADABLE + 1))
        continue
    fi
    while IFS= read -r abs_path; do
        [[ -n "$abs_path" ]] || continue
        rel="${abs_path##*/Obsidian-Claude-Vibe-Squad/}"
        [[ "$rel" == "$abs_path" ]] && continue
        REGISTERED_COUNT=$((REGISTERED_COUNT + 1))
        if [[ ! -e "${VAULT_ROOT}/${rel}" ]]; then
            REGISTERED_MISSING=$((REGISTERED_MISSING + 1))
            ISSUES+=("launchd job $(basename "$plist") points at a missing script: ${rel}")
        fi
    done < <(printf '%s\n' "${plist_dump}" | grep -oE '/[A-Za-z0-9._/-]+\.(sh|py)' | sort -u)
done
if ! command -v plutil >/dev/null 2>&1; then
    note_unknown "launchd registration audit could not run: plutil is unavailable"
elif [[ "${GREP_USABLE}" != true ]]; then
    note_unknown "launchd registration audit could not run: grep is unavailable"
elif [[ "${PLIST_COUNT}" -eq 0 ]]; then
    note_skip "no launchd agents are registered for this HOME" \
        "No ${HOME}/Library/LaunchAgents/*.plist to audit — nothing is scheduled from this HOME"
elif [[ "${PLIST_UNREADABLE}" -gt 0 ]]; then
    note_unknown "${PLIST_UNREADABLE}/${PLIST_COUNT} launchd plist(s) could not be read" \
        "${PLIST_UNREADABLE} of ${PLIST_COUNT} plist(s) were unreadable; the scripts they register were NOT checked"
elif [[ "${REGISTERED_MISSING}" -eq 0 ]]; then
    note_ok "launchd-registered scripts present" \
        "${REGISTERED_COUNT} launchd-registered repo script(s) across ${PLIST_COUNT} plist(s) all present"
else
    note_warn "${REGISTERED_MISSING}/${REGISTERED_COUNT} launchd-registered script(s) missing" \
        "${REGISTERED_MISSING}/${REGISTERED_COUNT} launchd-registered script(s) MISSING"
fi

# DECISION (2026-08-11) on docs/brain-map.md: it stays PRIVATE, and doctor
# stops requiring it.
#
# It is the internal source-of-truth map. Its own tables cite chrono/current.md
# and shared/lifecycle.md, both themselves denied by policy, and it documents
# the staged-versus-live V4 boundary -- internal navigation, not adopter
# documentation. tools/export/policy/path-policy.json denies it alongside
# docs/roadmap.md, docs/lineage.md and docs/design/**; docs/architecture.md is
# the published equivalent an adopter actually needs. Nothing in the runtime
# reads it: doctor's own check was its only non-prose consumer, and it was
# pushing a public install to exit 1 over a file that install was never meant
# to have. The export policy is unchanged.
#
# Tracked-but-absent stays an ISSUE, so deleting it in the private tree is
# still caught. Only "this distribution never carried it" is exempt.
case "$(classify_dependency 'docs/brain-map.md')" in
    present)
        note_ok "brain map present" "Brain map present"
        ;;
    missing)
        note_issue "brain map missing" \
            "docs/brain-map.md is tracked in this tree but absent from the working copy"
        ;;
    unpublished)
        note_skip "brain map is private and not part of this distribution" \
            "docs/brain-map.md is withheld from public projections by policy; not required here (see docs/architecture.md)"
        ;;
    *)
        note_unknown "brain map status could not be determined" \
            "git could not read this tree, so 'absent' cannot be told from 'never shipped'"
        ;;
esac

# Scans LIVE instruction surfaces only. docs/ is excluded by CLAUDE.md's own
# rule -- "old plans/specs are historical unless current state references them"
# -- and a dated design doc naming a since-removed script is an accurate record,
# not drift. Including docs/ made this warning uncleanable, and a warning that
# cannot reach zero is one people learn to ignore.
#
# A reference also counts as resolved when it matches the TAIL of a real tracked
# path: the pattern captures `bin/install-local.sh` out of the genuine
# `tools/radar/bin/install-local.sh`, which is an artifact of the match, not a
# missing file.
MISSING_SCRIPT_REFS=0
SCRIPT_REFS_SEEN=0
if [[ "${GREP_USABLE}" != true ]]; then
    note_unknown "referenced-script scan could not run: grep is unavailable"
elif [[ "${GIT_USABLE}" != true ]]; then
    # The tail-match exemption below needs `git ls-files`. Without it every
    # legitimately-relocated reference counts as missing, so the scan is not
    # merely degraded -- its answer is wrong in both directions.
    note_unknown "referenced-script scan could not run: git cannot read this tree"
else
    while IFS= read -r script_ref; do
        [[ -n "$script_ref" ]] || continue
        SCRIPT_REFS_SEEN=$((SCRIPT_REFS_SEEN + 1))
        [[ -e "${VAULT_ROOT}/${script_ref}" ]] && continue
        if git -C "${VAULT_ROOT}" ls-files 2>/dev/null | grep -qE "(^|/)${script_ref}$"; then
            continue
        fi
        MISSING_SCRIPT_REFS=$((MISSING_SCRIPT_REFS + 1))
    done < <(grep -RhoE '(bin|scripts|shared)/[A-Za-z0-9._/-]+\.(sh|py)' \
        "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/shared" 2>/dev/null | sort -u)
    if [[ "${SCRIPT_REFS_SEEN}" -eq 0 ]]; then
        note_unknown "referenced-script scan found no references at all" \
            "not one script reference was read from README/CLAUDE/chrono/shared — the scan found nothing to check, which is not the same as finding nothing wrong"
    elif [[ "${MISSING_SCRIPT_REFS}" -eq 0 ]]; then
        note_ok "referenced scripts exist" \
            "All ${SCRIPT_REFS_SEEN} referenced script path(s) resolve"
    else
        note_warn "missing referenced scripts: ${MISSING_SCRIPT_REFS}" \
            "${MISSING_SCRIPT_REFS}/${SCRIPT_REFS_SEEN} referenced script path(s) are missing"
    fi
fi

echo "" >> "${DOCTOR_LOG}"
echo "## Memory Discipline" >> "${DOCTOR_LOG}"
# Same summary-line contract as the MCP audit: one `summary: issues=N ...` line
# on completion. Its absence used to be indistinguishable from a real finding,
# and the "no summary" fallback text was itself the giveaway that nobody had
# decided what that case meant.
# An absent checker is an unmeasured cross-check, not a broken install -- the
# same call doctor already makes for bin/mcp-audit.sh, bin/product-hygiene.sh,
# bin/validate-specialists.sh and scripts/bootstrap-mcps.sh, all four of which
# use note_unknown here. This one branch was the outlier, and the inconsistency
# was the defect: five sibling checkers, one identical situation, five different
# consequences is not a policy.
if [[ ! -x "${VAULT_ROOT}/bin/memory-audit.sh" ]]; then
    note_unknown "memory audit could not run" \
        "bin/memory-audit.sh is missing or not executable — memory discipline is UNKNOWN"
else
    memory_rc=0
    MEMORY_RAW="$("${VAULT_ROOT}/bin/memory-audit.sh" 2>/dev/null)" || memory_rc=$?
    MEMORY_OUTPUT="$(printf '%s\n' "${MEMORY_RAW}" | grep -E '^summary: ' | tail -1)"
    if [[ -z "${MEMORY_OUTPUT}" ]]; then
        note_gate_unknown "memory audit did not complete" \
            "bin/memory-audit.sh exited ${memory_rc} without a summary line — memory discipline is UNKNOWN"
    else
        case "${memory_rc}" in
            0)
                if [[ "${MEMORY_OUTPUT}" =~ status=clean ]] \
                    && [[ "${MEMORY_OUTPUT}" =~ files_scanned=([1-9][0-9]*) ]]; then
                    note_ok "memory audit passed" "Memory audit passed (${MEMORY_OUTPUT})"
                else
                    note_gate_unknown "memory audit returned an invalid clean summary" \
                        "bin/memory-audit.sh exited 0 without proving files_scanned>0 and status=clean (${MEMORY_OUTPUT})"
                fi
                ;;
            1)
                note_issue "memory audit found missing discipline cite or secret-like pattern" \
                    "Memory audit found issues (${MEMORY_OUTPUT})"
                ;;
            2)
                # bin/memory-audit.sh returns 2 for BOTH "there was nothing to
                # scan" and "I lost a required command mid-scan", and its own
                # summary line already carries the fact that separates them
                # (memory-audit.sh:105-108,118). A tree with no
                # departments/*/memory.md has produced no memory that could be
                # undisciplined; a scan that READ files and still could not
                # conclude is a genuinely unmeasured integrity gate.
                if [[ "${MEMORY_OUTPUT}" =~ files_scanned=0([^0-9]|$) ]]; then
                    note_absent_input "memory audit had no memory file to scan yet" \
                        "Memory audit scanned zero files: no departments/*/memory.md exists yet, so memory discipline is unestablished rather than lost (${MEMORY_OUTPUT})"
                else
                    note_gate_unknown "memory audit could not determine memory discipline" \
                        "Memory audit read files but lost a required command (${MEMORY_OUTPUT})"
                fi
                ;;
            *)
                note_gate_unknown "memory audit failed unexpectedly with exit ${memory_rc}" \
                    "Memory audit returned an undocumented exit code (${MEMORY_OUTPUT})"
                ;;
        esac
    fi
fi

# --- 3. Secrets ---
echo "" >> "${DOCTOR_LOG}"
echo "## Secrets" >> "${DOCTOR_LOG}"
if [[ -f "${HOME}/.config/shell/secrets.zsh" ]]; then
    note_ok "secrets.zsh present" "secrets.zsh present at ${HOME}/.config/shell/secrets.zsh"
else
    # Demoted from ISSUE. The core markdown dispatch rail runs on subscription
    # CLI auth and needs no secrets file; this gates the OPTIONAL integrations
    # (research arsenal, media studio, recon). A first run on a clean machine
    # has no secrets file, and exiting 1 there teaches a new user that doctor's
    # exit code means nothing. The exit code means "this installation cannot do
    # its job", not "this installation is not finished being set up".
    note_warn "secrets.zsh not configured — optional integrations stay off" \
        "secrets.zsh not present at ${HOME}/.config/shell/secrets.zsh — optional MCP integrations stay off; see docs/private-config.md"
fi

# --- 4. Private memory vault + repository accessibility ---
echo "" >> "${DOCTOR_LOG}"
echo "## Vault" >> "${DOCTOR_LOG}"
# NOT CONFIGURED and CONFIGURED-BUT-BROKEN are different findings and only the
# second is a fault. An unset CHRONO_VAULT_ROOT is the state of every machine
# before the operator points it at a vault; a set-but-invalid one is a
# regression that must stay loud.
if PRIVATE_VAULT_ERROR="$(check_private_vault_root 2>&1)"; then
    note_ok "private memory vault valid" "Private memory vault root is valid"
elif [[ -z "${CHRONO_VAULT_ROOT:-}" ]]; then
    note_warn "private memory vault not configured (CHRONO_VAULT_ROOT unset)" \
        "Private memory vault is not configured: CHRONO_VAULT_ROOT is unset. Durable cross-session memory stays off; see docs/private-config.md"
else
    note_issue "private memory vault invalid: ${PRIVATE_VAULT_ERROR:-unknown error}" \
        "Private memory vault root is configured but INVALID: ${PRIVATE_VAULT_ERROR:-unknown error}"
fi
if [[ -d "${VAULT_ROOT}" ]] && [[ -w "${VAULT_ROOT}" ]]; then
    note_ok "runtime repository accessible" \
        "Runtime repository accessible at ${VAULT_ROOT}"
else
    note_issue "runtime repository not accessible" \
        "Runtime repository not accessible at ${VAULT_ROOT}"
fi

# --- 5. Browser session — read summary written by browser-keep-alive.sh ---
echo "" >> "${DOCTOR_LOG}"
echo "## Browser Session" >> "${DOCTOR_LOG}"
BROWSER_SUMMARY="${VAULT_ROOT}/_state/cleanup-logs/${DATE}-browser-summary.json"
if [[ ! -f "${BROWSER_SUMMARY}" ]]; then
    # Today's summary is written by browser-keep-alive.sh. Its absence means
    # that job has not run today -- always true of a fresh install, and
    # routinely true of a live one before the first keep-alive of the morning.
    # An unreadable or malformed summary stays gating below: that file existed
    # and doctor could not read it.
    note_absent_input "browser session status unavailable: no browser summary for today" \
        "no browser-keep-alive summary exists for ${DATE} — browser reachability was NOT measured"
elif ! command -v jq >/dev/null 2>&1; then
    note_gate_unknown "browser session status could not be parsed: jq is unavailable"
elif ! jq -e '
    (type == "object") and
    ((.reachable | type) == "boolean") and
    (((.platforms_open // 0) | type) == "number") and
    (((.platforms_expired // []) | type) == "array") and
    (((.platforms_missing // []) | type) == "array")
' "${BROWSER_SUMMARY}" >/dev/null 2>&1; then
    note_gate_unknown "browser session status could not be parsed: invalid summary schema" \
        "${BROWSER_SUMMARY} is unreadable or lacks the typed reachable/platform fields — browser reachability is UNKNOWN"
else
    reachable=$(jq -r '.reachable // false' "${BROWSER_SUMMARY}")
    if [[ "${reachable}" == "true" ]]; then
        open=$(jq -r '.platforms_open // 0' "${BROWSER_SUMMARY}")
        expired=$(jq -r '.platforms_expired // [] | length' "${BROWSER_SUMMARY}")
        missing=$(jq -r '.platforms_missing // [] | length' "${BROWSER_SUMMARY}")
        note_ok "browser CDP reachable" \
            "Chrome CDP reachable: ${open} session tab(s) open"
        if [[ ${expired} -gt 0 ]]; then
            expired_names=$(jq -r '.platforms_expired // [] | join(", ")' "${BROWSER_SUMMARY}")
            note_warn "browser sessions expired: ${expired_names}" \
                "${expired} session tab(s) need refresh: ${expired_names}"
        fi
        if [[ ${missing} -gt 0 ]]; then
            missing_names=$(jq -r '.platforms_missing // [] | join(", ")' "${BROWSER_SUMMARY}")
            note_warn "browser expected tabs missing: ${missing_names}" \
                "${missing} expected tab(s) missing: ${missing_names}"
        fi
    else
        note_warn "Chrome CDP not reachable — bounty browser tools won't work" \
            "Chrome not reachable on CDP debug port (run with --remote-debugging-port=9222)"
    fi
fi

# --- 6. Disk space ---
echo "" >> "${DOCTOR_LOG}"
echo "## Disk Space" >> "${DOCTOR_LOG}"
# A df that returns nothing used to leave disk_free_pct empty, which bash
# evaluates as 0 inside [[ -gt ]], so a FAILED MEASUREMENT fell straight through
# to "Disk: % free (CRITICAL)" -- an issue raised, with the number missing from
# its own sentence. Validate the figure before comparing it.
disk_free_pct=""
if command -v df >/dev/null 2>&1; then
    disk_free_pct=$(df -h "${HOME:-/}" 2>/dev/null \
        | awk 'NR==2 {gsub("%",""); print 100-$5}')
fi
if ! [[ "${disk_free_pct}" =~ ^-?[0-9]+$ ]]; then
    note_unknown "disk free space could not be measured" \
        "df returned no usable free-space figure for ${HOME:-/} — disk headroom is UNKNOWN"
elif [[ "${disk_free_pct}" -gt 15 ]]; then
    note_ok "disk OK" "Disk: ${disk_free_pct}% free"
elif [[ "${disk_free_pct}" -gt 5 ]]; then
    note_warn "disk at ${disk_free_pct}%" "Disk: ${disk_free_pct}% free (getting tight)"
else
    note_issue "disk critical at ${disk_free_pct}%" \
        "Disk: ${disk_free_pct}% free (CRITICAL)"
fi

# --- 7. tmux panes ---
echo "" >> "${DOCTOR_LOG}"
echo "## tmux Sessions" >> "${DOCTOR_LOG}"
if command -v tmux >/dev/null 2>&1; then
    if tmux ls >/dev/null 2>&1; then
        pane_count=$(tmux list-sessions 2>/dev/null | wc -l | tr -d ' ')
        note_ok "tmux running" "tmux running: ${pane_count} session(s)"
    else
        note_warn "tmux no sessions" "tmux installed but no sessions running"
    fi
else
    note_warn "tmux not installed" "tmux not installed"
fi

# --- 8. Token usage proxy (squad-driven LLM artifact volume) ---
# We don't have direct token counters per CLI, but we know the squad's own
# scripts produce one artifact per LLM call. Counting today's vs the trailing
# 7-day average gives an anomaly signal.
echo "" >> "${DOCTOR_LOG}"
echo "## Token Usage (proxy via artifact count)" >> "${DOCTOR_LOG}"
ARTIFACT_DIRS=()
for sub in blog-summaries podcast-briefs dream-logs; do
    [[ -d "${VAULT_ROOT}/_state/${sub}" ]] && ARTIFACT_DIRS+=("${VAULT_ROOT}/_state/${sub}")
done
if [[ "${#ARTIFACT_DIRS[@]}" -eq 0 ]]; then
    # An absent target set is not evidence of a clean artifact volume, but it
    # is normal before any artifact producer has run. Keep it loud and separate
    # from a present target that find could not enumerate.
    note_absent_input "token-bleed artifact scan has no source directories" \
        "none of _state/{blog-summaries,podcast-briefs,dream-logs} exists — artifact volume was NOT measured"
else
    artifact_scan_rc=0
    TODAY_ARTIFACTS=$(find "${ARTIFACT_DIRS[@]}" -name "${DATE}-*" -type f 2>/dev/null \
        | wc -l | tr -d ' ') || artifact_scan_rc=$?
    WEEKLY_ARTIFACTS=$(find "${ARTIFACT_DIRS[@]}" -name '*.md' -mtime -7 -type f 2>/dev/null \
        | wc -l | tr -d ' ') || artifact_scan_rc=$?
    if [[ "${artifact_scan_rc}" -ne 0 \
        || ! "${TODAY_ARTIFACTS}" =~ ^[0-9]+$ \
        || ! "${WEEKLY_ARTIFACTS}" =~ ^[0-9]+$ ]]; then
        note_gate_unknown "token-bleed artifact scan failed" \
            "find could not enumerate the artifact sources — artifact volume is UNKNOWN"
    else
        WEEKLY_AVG=$(( WEEKLY_ARTIFACTS / 7 ))
        note_info "Today: ${TODAY_ARTIFACTS} artifacts"
        note_info "7d total: ${WEEKLY_ARTIFACTS} (avg/day: ${WEEKLY_AVG})"
        # Flag if today is 3x the weekly average AND average isn't trivial.
        if [[ ${WEEKLY_AVG} -ge 3 ]] && [[ ${TODAY_ARTIFACTS} -gt $((WEEKLY_AVG * 3)) ]]; then
            note_issue "token-bleed suspect: today=${TODAY_ARTIFACTS} vs weekly_avg=${WEEKLY_AVG}" \
                "Anomaly: today's volume is >3x weekly average — possible token-bleed"
        else
            note_ok "token-bleed artifact volume within threshold" \
                "Artifact volume is within threshold (today=${TODAY_ARTIFACTS}, weekly_avg=${WEEKLY_AVG})"
        fi
    fi
fi

# Primary token-spend signal: dispatch count from dispatch-log.jsonl (last 24h).
# Catches retry loops with single-artifact output (which the artifact-count
# proxy above misses). This is a high-water-mark check, not a cost breakdown --
# the per-pane report that once complemented it belonged to the retired
# persistent-lane architecture and was removed with it.
if [[ ! -f "${VAULT_ROOT}/_state/dispatch-log.jsonl" ]]; then
    # No ledger is not a measured zero. A present empty ledger is the clean
    # control; an absent ledger is the loud, non-gating zero-state. A present
    # ledger that cannot be parsed remains gate-blocking below.
    note_absent_input "dispatch-log token-spend scan has no input" \
        "_state/dispatch-log.jsonl is absent — dispatch volume was NOT measured"
elif ! command -v jq >/dev/null 2>&1; then
    note_gate_unknown "dispatch-log token-spend scan could not parse input: jq is unavailable"
else
    yesterday_iso=$(date -u -v-1d +%FT%TZ 2>/dev/null \
        || date -u -d '1 day ago' +%FT%TZ 2>/dev/null || true)
    dispatch_scan_rc=0
    DISPATCHES_LAST_24H=$(jq -r --arg t "$yesterday_iso" \
        'if (type == "object") and ((.ts | type) == "string")
         then select(.ts > $t) | (.model_lane // .to_model // "?")
         else error("dispatch row lacks a string ts")
         end' \
        "${VAULT_ROOT}/_state/dispatch-log.jsonl" 2>/dev/null \
        | wc -l | tr -d ' ') || dispatch_scan_rc=$?
    if [[ -z "${yesterday_iso}" || "${dispatch_scan_rc}" -ne 0 \
        || ! "${DISPATCHES_LAST_24H}" =~ ^[0-9]+$ ]]; then
        note_gate_unknown "dispatch-log token-spend scan failed" \
            "the 24-hour cutoff or dispatch log could not be parsed — dispatch volume is UNKNOWN"
    elif [[ ${DISPATCHES_LAST_24H} -gt 200 ]]; then
        note_issue "dispatch volume ${DISPATCHES_LAST_24H} exceeds 200/24h baseline" \
            "High dispatch volume (>200/day) — possible runaway loop"
    else
        note_ok "dispatch volume within threshold" \
            "Total dispatches last 24h: ${DISPATCHES_LAST_24H} (threshold: 200)"
    fi
fi

# --- 9. Specialist dispatch volume ---
echo "" >> "${DOCTOR_LOG}"
echo "## Dispatch Activity (last 24h)" >> "${DOCTOR_LOG}"
ARCHIVE_DIRS=()
INBOX_DIRS=()
for dir in "${VAULT_ROOT}/departments"/*/archive; do
    [[ -d "${dir}" ]] && ARCHIVE_DIRS+=("${dir}")
done
for dir in "${VAULT_ROOT}/departments"/*/inbox; do
    [[ -d "${dir}" ]] && INBOX_DIRS+=("${dir}")
done
if [[ "${#ARCHIVE_DIRS[@]}" -eq 0 ]]; then
    note_absent_input "dispatch completion scan has no archive targets" \
        "found no departments/*/archive directory — completed dispatch activity is UNKNOWN"
else
    archive_scan_rc=0
    DISPATCHES_24H=$(find "${ARCHIVE_DIRS[@]}" -name 'TASK-*-response.md' -mtime -1 -type f 2>/dev/null \
        | wc -l | tr -d ' ') || archive_scan_rc=$?
    if [[ "${archive_scan_rc}" -ne 0 || ! "${DISPATCHES_24H}" =~ ^[0-9]+$ ]]; then
        note_gate_unknown "dispatch completion scan failed" \
            "find could not enumerate archive targets — completed dispatch activity is UNKNOWN"
    else
        note_info "Tasks completed (last 24h): ${DISPATCHES_24H}"
    fi
fi

# Count backlog independently. Before the first completed task there can be an
# inbox but no archive; coupling the two target sets made exactly that backlog
# invisible. A missing inbox is still indeterminate, not a measured zero, but
# is normal before the first launch creates mailbox state.
if [[ "${#INBOX_DIRS[@]}" -eq 0 ]]; then
    note_absent_input "inbox backlog scan has no inbox targets" \
        "found no departments/*/inbox directory — inbox backlog is UNKNOWN"
else
    inbox_scan_rc=0
    INBOX_BACKLOG=$(find "${INBOX_DIRS[@]}" -name 'TASK-*.md' -type f 2>/dev/null \
        | wc -l | tr -d ' ') || inbox_scan_rc=$?
    if [[ "${inbox_scan_rc}" -ne 0 || ! "${INBOX_BACKLOG}" =~ ^[0-9]+$ ]]; then
        note_gate_unknown "inbox backlog scan failed" \
            "find could not enumerate inbox targets — inbox backlog is UNKNOWN"
    elif [[ ${INBOX_BACKLOG} -gt 10 ]]; then
        note_issue "inbox backlog: ${INBOX_BACKLOG} unacknowledged tasks" \
            "Inbox backlog exceeds 10 — model leads may be stuck"
    else
        note_ok "inbox backlog within threshold" \
            "Inbox backlog: ${INBOX_BACKLOG} (threshold: 10)"
    fi
fi

# --- 10. Process audit (with pathology detection) ---
echo "" >> "${DOCTOR_LOG}"
echo "## Process Audit" >> "${DOCTOR_LOG}"
SQUAD_PIDS=""
if command -v tmux >/dev/null 2>&1 && tmux has-session -t squad 2>/dev/null; then
    SQUAD_PIDS=$(tmux list-panes -a -F '#{pane_pid}' 2>/dev/null | tr '\n' ' ')
    note_ok "squad tmux session present" \
        "squad tmux session is running with pane roots: ${SQUAD_PIDS}"
else
    note_warn "squad tmux session not running" "squad tmux session is not running"
fi

# THE defect this whole vocabulary exists for. On 2026-08-11 a rehearsal fed
# these three checks a ps that answered `/bin/ps: Operation not permitted` every
# time, and doctor printed "No long-running CLI processes detected" -- and
# dropped the "extra non-squad CLI roots" warning the working run had raised, so
# the machine it could not see looked HEALTHIER than the machine it could.
#
# The fix is not to make ps work. It is that a check which could not run must be
# distinguishable from one that passed. PS_USABLE is established by a positive
# control at the top of this file: ps must name this very process.
if [[ "${PS_USABLE}" != true ]]; then
    note_unknown "process audit could not run: ${PS_DENIED_REASON}" \
        "Process audit COULD NOT RUN — ${PS_DENIED_REASON}. Long-running CLI processes, extra non-squad CLI roots, and runaway-CPU processes are ALL UNDETERMINED. None of them were found absent; none of them were looked for."
else
    # Long-running claude/codex/gemini/kimi processes are expected for the daily
    # driver, but extra interactive CLIs outside the squad pane roots can leave
    # MCP children around. Report them separately; never kill them here.
    long_procs=$(ps -eo pid,ppid,etime,pcpu,comm | awk '$5 ~ /(claude|codex|gemini|kimi)/ && $3 ~ /^[0-9]+-[0-9]+/ {print}' | head -10)
    if [[ -n "${long_procs}" ]]; then
        note_info "Long-running CLI processes (>1 day; may be active non-squad sessions):"
        echo "${long_procs}" | sed 's/^/  /' >> "${DOCTOR_LOG}"
        HEALTHY+=("persistent CLI processes present")
    else
        note_ok "no long-running CLI processes" "No long-running CLI processes detected"
    fi

    extra_cli=$(ps -eo pid,ppid,etime,pcpu,command | awk -v squad_pids="${SQUAD_PIDS}" '
        function is_squad(pid) {
            return index(" " squad_pids " ", " " pid " ") > 0
        }
        $0 ~ /(claude|codex|gemini|kimi)( |$)/ && $0 !~ /bin\/(launch-squad|squad-stop|doctor)\.sh/ {
            if (!is_squad($1) && !is_squad($2)) print
        }
    ' | head -20)
    if [[ -n "${extra_cli}" ]]; then
        note_warn "extra non-squad CLI sessions detected; use normal terminal cleanup if stale" \
            "🟡 Extra non-squad CLI roots detected (informational; may be active terminals):"
        echo "${extra_cli}" | sed 's/^/  /' >> "${DOCTOR_LOG}"
    fi

    # Pathology: high-CPU CLI processes (likely retry storm or runaway loop)
    runaway=$(ps -eo pid,etime,pcpu,comm | awk '$4 ~ /(claude|codex|gemini|kimi)/ && $3+0 > 80 {print}' | head -3)
    if [[ -n "${runaway}" ]]; then
        note_issue "CLI process consuming >80% CPU — kill if stuck in retry loop" \
            "High-CPU CLI processes (>80% CPU — possible runaway):"
        echo "${runaway}" | sed 's/^/  /' >> "${DOCTOR_LOG}"
    fi
fi

# Pathology: MCP retry storms — search recent CLI stdout for connection-failure patterns.
# tmux-logs are pane stdout (where CLIs actually log connection issues), not
# cleanup-logs (which are short structured docs that don't reflect real retry
# spam). Time-windowed to last hour; pattern targets MCP-specific failures.
# Read only the recent TAIL of each log (default 8MB), not the whole file:
# these are append-only pane-stdout captures that can reach many GB (a runaway
# gemini TUI log hit 11.6GB), and grepping them in full took ~40s and blew past
# the doctor gate. A retry storm is an ONGOING pathology, so the recent tail is
# the right — and bounded — signal.
# "0 connection-failure lines" came out identical whether the logs were clean,
# the directory did not exist, or no pane had written in the last hour. Only the
# first of those is evidence of anything, and a zero-state install is always one
# of the other two.
RETRY_STORM_FILES=0
if [[ ! -d "${VAULT_ROOT}/_state/tmux-logs" ]]; then
    note_skip "retry-storm scan: this tree has no tmux log directory" \
        "No _state/tmux-logs to scan — MCP retry behaviour is not observable here"
elif [[ "${GREP_USABLE}" != true ]]; then
    note_unknown "retry-storm scan could not run: grep is unavailable"
else
    RETRY_STORM_FILES=$(find "${VAULT_ROOT}/_state/tmux-logs" -name '*.log' -mmin -60 2>/dev/null \
        | wc -l | tr -d ' ')
    RETRY_STORM_LOG=$(find "${VAULT_ROOT}/_state/tmux-logs" -name '*.log' -mmin -60 2>/dev/null \
        | while IFS= read -r _logf; do
            tail -c "${DOCTOR_LOG_SCAN_BYTES:-8000000}" "$_logf" 2>/dev/null \
                | grep -cE 'Failed to connect|connection refused|retrying.*MCP|MCP.*timeout|reconnect attempt'
          done \
        | awk '{sum+=$1} END {print sum+0}')
    if [[ "${RETRY_STORM_FILES}" -eq 0 ]]; then
        note_skip "retry-storm scan: no pane wrote in the last hour" \
            "No tmux log was modified in the last hour — there was no recent output to scan, so a quiet hour reads as quiet, not as clean"
    elif [[ ${RETRY_STORM_LOG} -gt 100 ]]; then
        note_warn "MCP retry storm suspect — ${RETRY_STORM_LOG} connection failures in last hour" \
            "Possible MCP retry storm: ${RETRY_STORM_LOG} connection-failure lines in last hour of ${RETRY_STORM_FILES} tmux-log(s)"
    elif [[ ${RETRY_STORM_LOG} -gt 30 ]]; then
        note_info "🟡 Elevated MCP retry activity: ${RETRY_STORM_LOG} connection-failure lines in last hour"
    else
        note_ok "no retry-storm pattern" \
            "No retry-storm pattern detected (${RETRY_STORM_LOG} connection-failure lines across ${RETRY_STORM_FILES} recently-written log(s))"
    fi
fi

# Pathology: stale tmp files in _state (signal of crashed atomic writes). This
# used to pass in silence, which is the one outcome a reader cannot audit.
if [[ ! -d "${VAULT_ROOT}/_state" ]]; then
    note_skip "stale atomic-write fragment scan: this tree has no _state directory"
else
    STALE_TMPS=$(find "${VAULT_ROOT}/_state" -name '*.tmp.*' -type f -mmin +30 2>/dev/null | wc -l | tr -d ' ')
    if [[ ${STALE_TMPS} -gt 0 ]]; then
        note_warn "${STALE_TMPS} stale temp-file fragments in _state" \
            "${STALE_TMPS} stale .tmp.* files in _state (atomic-write fragments — crash residue?)"
    else
        note_ok "no stale atomic-write fragments" \
            "No stale .tmp.* fragments in _state"
    fi
fi

# --- 11. Log volume ---
echo "" >> "${DOCTOR_LOG}"
echo "## Log Volume" >> "${DOCTOR_LOG}"
state_size=$(du -sh "${VAULT_ROOT}/_state" 2>/dev/null | cut -f1)
echo "- _state/ size: ${state_size}" >> "${DOCTOR_LOG}"

# --- Summary ---
echo "" >> "${DOCTOR_LOG}"
echo "## Summary" >> "${DOCTOR_LOG}"
echo "- Healthy: ${#HEALTHY[@]}" >> "${DOCTOR_LOG}"
echo "- Warnings: ${#WARNINGS[@]}" >> "${DOCTOR_LOG}"
echo "- Issues: ${#ISSUES[@]}" >> "${DOCTOR_LOG}"
echo "- Could not determine: ${#UNKNOWNS[@]}" >> "${DOCTOR_LOG}"
echo "- Gate-blocking unknowns: ${#GATE_UNKNOWN_LIST[@]}" >> "${DOCTOR_LOG}"
echo "- Inputs not produced yet (loud, non-gating): ${#ABSENT_INPUTS[@]}" >> "${DOCTOR_LOG}"
echo "- Not applicable to this install: ${#SKIPPED[@]}" >> "${DOCTOR_LOG}"

# Listed under their own heading because a count alone lets an unmeasured
# subsystem hide behind a healthy-looking total.
if [[ "${#UNKNOWNS[@]}" -gt 0 ]]; then
    echo "" >> "${DOCTOR_LOG}"
    echo "### Could not determine — these are NOT passes" >> "${DOCTOR_LOG}"
    for _unknown in "${UNKNOWNS[@]}"; do
        echo "- ? ${_unknown}" >> "${DOCTOR_LOG}"
    done
    unset _unknown
fi
if [[ "${#ABSENT_INPUTS[@]}" -gt 0 ]]; then
    echo "" >> "${DOCTOR_LOG}"
    echo "### Inputs not produced yet — these do not block a launch" >> "${DOCTOR_LOG}"
    echo "" >> "${DOCTOR_LOG}"
    echo "Each of these checks ran and found its input had never been written." \
        "That is the normal state of an installation that has not been used" \
        "yet. They are counted above as could-not-determine, never as passes." >> "${DOCTOR_LOG}"
    for _absent in "${ABSENT_INPUTS[@]}"; do
        echo "- ? ${_absent}" >> "${DOCTOR_LOG}"
    done
    unset _absent
fi
if [[ "${#SKIPPED[@]}" -gt 0 ]]; then
    echo "" >> "${DOCTOR_LOG}"
    echo "### Not applicable to this install" >> "${DOCTOR_LOG}"
    for _skipped in "${SKIPPED[@]}"; do
        echo "- ○ ${_skipped}" >> "${DOCTOR_LOG}"
    done
    unset _skipped
fi

# Write JSON summary for morning-brief.sh to consume
# Build arrays as proper JSON
json_array() {
    local arr=("$@")
    if [[ "${#arr[@]}" -eq 0 ]]; then
        echo "[]"
    else
        local out="["
        local first=1
        for item in "${arr[@]}"; do
            # Escape backslashes and double-quotes for JSON
            local esc="${item//\\/\\\\}"
            esc="${esc//\"/\\\"}"
            # ...and control characters, which are illegal RAW inside a JSON
            # string. A multi-line value used to emit a summary jq could not
            # parse, and every consumer reads it with a `// 0` fallback -- so
            # bin/morning-brief.sh printed "0 issues" for a run that had just
            # exited 1. Measured against HEAD 2026-08-11: a `vaultroot`
            # ModuleNotFoundError traceback landed in .issues verbatim and the
            # whole file stopped being JSON. A health report whose machine-
            # readable half fails open is worse than none.
            esc="$(printf '%s' "${esc}" | tr -d '\000-\010\013\014\016-\037')"
            esc="${esc//$'\t'/\\t}"
            esc="${esc//$'\r'/\\r}"
            esc="${esc//$'\n'/\\n}"
            if [[ ${first} -eq 1 ]]; then
                out+="\"${esc}\""
                first=0
            else
                out+=",\"${esc}\""
            fi
        done
        out+="]"
        echo "${out}"
    fi
}

# Bash empty-array under set -u needs the +expansion guard
WARNINGS_JSON=$(json_array ${WARNINGS[@]+"${WARNINGS[@]}"})
ISSUES_JSON=$(json_array ${ISSUES[@]+"${ISSUES[@]}"})
UNKNOWNS_JSON=$(json_array ${UNKNOWNS[@]+"${UNKNOWNS[@]}"})
SKIPPED_JSON=$(json_array ${SKIPPED[@]+"${SKIPPED[@]}"})
# Both are SUBSETS of unknowns, published so a consumer can gate on either
# without re-deriving the split from prose. gate_unknowns is what exit 2 means;
# absent_inputs is what a never-run installation looks like.
GATE_UNKNOWNS_JSON=$(json_array ${GATE_UNKNOWN_LIST[@]+"${GATE_UNKNOWN_LIST[@]}"})
ABSENT_INPUTS_JSON=$(json_array ${ABSENT_INPUTS[@]+"${ABSENT_INPUTS[@]}"})

# unknown_* and skipped_* are ADDITIVE: bin/morning-brief.sh,
# bin/where-are-we.sh and bin/chrono-status-segment.sh all read the three
# original counts with `// 0` defaults, so they keep working unchanged. They do
# not yet SHOW the unknown count, which means a status line can still read
# "healthy" while subsystems went unmeasured -- those files are outside this
# change's write scope and are flagged for follow-up.
cat > "${SUMMARY}" <<EOF
{
  "date": "${DATE}",
  "healthy_count": ${#HEALTHY[@]},
  "warning_count": ${#WARNINGS[@]},
  "issue_count": ${#ISSUES[@]},
  "unknown_count": ${#UNKNOWNS[@]},
  "gate_unknown_count": ${#GATE_UNKNOWN_LIST[@]},
  "absent_input_count": ${#ABSENT_INPUTS[@]},
  "skipped_count": ${#SKIPPED[@]},
  "warnings": ${WARNINGS_JSON},
  "issues": ${ISSUES_JSON},
  "unknowns": ${UNKNOWNS_JSON},
  "gate_unknowns": ${GATE_UNKNOWNS_JSON},
  "absent_inputs": ${ABSENT_INPUTS_JSON},
  "skipped": ${SKIPPED_JSON}
}
EOF

# --- Console report ---------------------------------------------------------
# Until 2026-08-14 this program wrote every one of its ~35 findings to
# ${DOCTOR_LOG} and printed NOTHING to stdout. README.md:50 and
# docs/getting-started.md:127 both tell a new user to run `bin/squad doctor`, so
# the documented health check answered with a blank line and a failed exit
# status, and never named the file where the report it had just written landed.
# A health tool that prints nothing and fails is worse than no health tool: the
# reader cannot tell a broken install from a broken health check.
#
# This prints the summary, every actionable list, and the log paths. It does not
# re-measure anything and it does not change any exit code -- presentation was
# the whole defect. ASCII markers only: the report is legible under LANG=C,
# which is what a sealed/CI environment gives you.
print_list() {
    local heading="$1" marker="$2"
    shift 2
    [[ "$#" -gt 0 ]] || return 0
    printf '\n%s\n' "${heading}"
    # One printf per item, not `printf FMT "${marker}" "$@"`: printf recycles
    # its format over the remaining arguments, so a two-slot format would pair
    # item 2 with item 3 on a single line and drop every marker after the first.
    local item
    for item in "$@"; do
        printf '  %s %s\n' "${marker}" "${item}"
    done
}

printf '\nVibe Squad doctor — %s\n' "${DATE}"
printf '  HEALTHY ................. %d\n' "${#HEALTHY[@]}"
printf '  WARNINGS ................ %d\n' "${#WARNINGS[@]}"
printf '  ISSUES .................. %d\n' "${#ISSUES[@]}"
printf '  COULD NOT DETERMINE ..... %d  (%d gate-blocking, %d not produced yet)\n' \
    "${#UNKNOWNS[@]}" "${#GATE_UNKNOWN_LIST[@]}" "${#ABSENT_INPUTS[@]}"
printf '  NOT APPLICABLE HERE ..... %d\n' "${#SKIPPED[@]}"

print_list "ISSUES — measured breakage (exit 1):" "!" \
    ${ISSUES[@]+"${ISSUES[@]}"}
print_list "GATE-BLOCKING UNKNOWNS — input was there and could not be read (exit 2):" "x" \
    ${GATE_UNKNOWN_LIST[@]+"${GATE_UNKNOWN_LIST[@]}"}
print_list "COULD NOT DETERMINE — not passes, but nothing here blocks a launch:" "?" \
    ${ABSENT_INPUTS[@]+"${ABSENT_INPUTS[@]}"}
print_list "WARNINGS — works, but wants attention or is simply not set up:" "-" \
    ${WARNINGS[@]+"${WARNINGS[@]}"}
print_list "NOT APPLICABLE — this distribution never carried the input:" "o" \
    ${SKIPPED[@]+"${SKIPPED[@]}"}

printf '\nFull report:       %s\n' "${DOCTOR_LOG}"
printf 'Machine-readable:  %s\n' "${SUMMARY}"

# Exit 1 for a measured issue; exit 2 when a mandatory gate could not determine
# its result. Optional UNKNOWNs remain loud but non-gating.
if [[ "${#ISSUES[@]}" -gt 0 ]]; then
    printf '\nVERDICT: %d issue(s) found. This installation is broken; fix them before launching. (exit 1)\n' \
        "${#ISSUES[@]}"
    exit 1
fi
if [[ "${#GATE_UNKNOWN_LIST[@]}" -gt 0 ]]; then
    printf '\nVERDICT: %d mandatory check(s) could not read an input that was present. Not proven broken, not proven healthy. (exit 2)\n' \
        "${#GATE_UNKNOWN_LIST[@]}"
    exit 2
fi
if [[ "${#ABSENT_INPUTS[@]}" -gt 0 ]]; then
    printf '\nVERDICT: healthy. %d check(s) had no input to read yet, which is what a fresh install looks like — they are reported above, not counted as passes. (exit 0)\n' \
        "${#ABSENT_INPUTS[@]}"
    exit 0
fi
printf '\nVERDICT: healthy. (exit 0)\n'
exit 0
