#!/bin/bash
# bin/canary.sh — live capability canary. Probes whether a capability WORKS,
# by performing or adjudicating a real action.
#
# WHY THIS EXISTS
#   Unit tests check CODE. bin/doctor.sh checks STATE. Neither checks
#   CAPABILITY. One build produced five capabilities that were green and dead
#   at the same time: board fan-out (1,779 unit tests passing, doctor 0 issues,
#   an anti-affinity APPROVE -- and every fan-out refused before host
#   admission); swarm (six test modules, 1,531 lines, no dispatch path at all);
#   the notification spine (doctor reported it, doctor could not measure it,
#   the reconciler exited 1); anti-affinity review (a 35-test suite that still
#   passed with three `must be cross-family` clauses replaced by `if False:`);
#   and advisory mode (a mode file, a protocol entry, a builder branch, and not
#   one successful dispatch in a month).
#
#   Every one of those is invisible to a test and to a state check, and visible
#   to a live action. That is the entire scope of this program.
#
# THREE OUTCOMES, NEVER TWO
#   PASS          the probe ran and the capability worked
#   FAIL          the probe ran and the capability is broken       (exit 1)
#   NOT MEASURED  the probe did not run, or its oracle is broken   (exit 2)
#
#   NOT MEASURED is never a pass. This mirrors doctor.sh's COULD NOT DETERMINE
#   and bin/test's BLOCKED, and it exists because a probe that returns "fine"
#   when the subsystem is absent is worse than no probe: it manufactures the
#   exact false confidence this program was written to destroy.
#
# EVERY PROBE HAS A POSITIVE CONTROL
#   Before any probe reports PASS or FAIL it first proves its own oracle can
#   see. The memory probe recalls its nonce BEFORE recording it and requires
#   zero hits. The skills probe requires its sentinel to still be present in
#   the skill file. The registry probes require a loadable, populated registry.
#   A control that cannot be established downgrades the probe to NOT MEASURED.
#
# EVERY PROBE HAS AN INVERTED CONTROL
#   `--self-test` breaks each capability against a fixture and asserts the
#   probe FAILS or reports NOT MEASURED. A canary that cannot fail is not a
#   gate; four green-but-broken cases above are what that costs.
#   scripts/python/tests/test_canary_suite.py pins the same inversions.
#
# WHAT A WORKER CANNOT DO
#   A board worker cannot launch a board dispatch, so probes 1-3 and 6 cannot be
#   EXECUTED from a lane. They are split instead: Chrono launches the two
#   role-specific canary packets, and this program ADJUDICATES the evidence
#   those tasks left in the registry, outbox and notify receipts. `--task` and
#   `--mcp-task` may adjudicate both results in one run.
#
# USAGE
#   bin/canary.sh                      probes that run here; 1-3, 6 NOT MEASURED
#   bin/canary.sh --task TASK-ID       adjudicate transport/skills evidence
#   bin/canary.sh --mcp-task TASK-ID   adjudicate Codex MCP evidence (may combine)
#   bin/canary.sh --emit-packet ID     print the transport/skills packet
#   bin/canary.sh --emit-mcp-packet ID print the Codex MCP-surface packet
#   bin/canary.sh --self-test          inverted controls (no live writes)
#   bin/canary.sh --no-memory-write    skip probe 4's one vault note
#
# EXIT CODES
#   0  every probe PASS
#   1  at least one FAIL
#   2  no FAIL, but at least one NOT MEASURED   (the default invocation)
#   64 usage error (EX_USAGE, matching doctor.sh)

set -uo pipefail
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

# The tree whose live state is under test. Defaults to this checkout. Run from
# a linked worktree, `_state/` is gitignored and therefore absent, so the
# registry probes report NOT MEASURED rather than inventing a clean answer --
# the same trap bin/send-task.sh documents, where a worktree's one-entry stub
# registry made a conflict check report "no conflicts" because it could no
# longer see any.
CANARY_ROOT="${CANARY_ROOT_UNDER_TEST:-${VAULT_ROOT}}"

# The vault venv, not system python3: notes/recall need the plugin's deps.
CHRONO_PY="${CHRONO_PY:-${VAULT_ROOT}/.venv/bin/python}"

# The oracle for probe 3. It is deliberately a phrase the lane can only produce
# by READING .claude/skills/probe-canary/SKILL.md, and it is deliberately
# absent from the packet this program emits -- a packet that quoted it would
# let a lane echo it back without ever firing the skill, which is precisely the
# projected-versus-fired distinction the probe exists to draw.
SKILL_SENTINEL='project-scoped skill loading works'

# Exact runtime MCP namespaces established by the systems-engineer@gpt-codex
# board probe documented in docs/board-mcp-surface.md. This is deliberately
# absent from the emitted packet: a worker must enumerate its live tool surface,
# not echo the expected answer. Any addition, removal, or failed bounded call is
# FAIL until the canonical document and this executable expectation are reviewed
# together.
MCP_SURFACE_EXPECTED_JSON='["chrono_research_arsenal","chrono_vault","codex_apps","sequential_thinking"]'
MCP_SURFACE_MARKER='MCP_SURFACE_JSON:'

TASK_ID=""
MCP_TASK_ID=""
SELF_TEST=0
MEMORY_WRITE=1
EMIT_PACKET_ID=""
EMIT_MCP_PACKET_ID=""

usage() {
    printf 'usage: canary.sh [--task TASK-ID] [--mcp-task TASK-ID] [--emit-packet ID | --emit-mcp-packet ID] [--self-test] [--no-memory-write]\n'
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --task)
            TASK_ID="${2:-}"
            [[ -z "${TASK_ID}" ]] && { printf 'canary.sh: --task needs a TASK-ID\n' >&2; exit 64; }
            shift 2
            ;;
        --mcp-task)
            MCP_TASK_ID="${2:-}"
            [[ -z "${MCP_TASK_ID}" ]] && { printf 'canary.sh: --mcp-task needs a TASK-ID\n' >&2; exit 64; }
            shift 2
            ;;
        --emit-packet)
            EMIT_PACKET_ID="${2:-}"
            [[ -z "${EMIT_PACKET_ID}" ]] && { printf 'canary.sh: --emit-packet needs an id\n' >&2; exit 64; }
            shift 2
            ;;
        --emit-mcp-packet)
            EMIT_MCP_PACKET_ID="${2:-}"
            [[ -z "${EMIT_MCP_PACKET_ID}" ]] && { printf 'canary.sh: --emit-mcp-packet needs an id\n' >&2; exit 64; }
            shift 2
            ;;
        --self-test)     SELF_TEST=1; shift ;;
        --no-memory-write) MEMORY_WRITE=0; shift ;;
        --help|-h)       usage; exit 0 ;;
        *)
            # Refused, never ignored: silently accepting `--tsk` would run the
            # default path while the caller believed a task was adjudicated.
            printf 'canary.sh: unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 64
            ;;
    esac
done

if [[ -n "${EMIT_PACKET_ID}" && -n "${EMIT_MCP_PACKET_ID}" ]]; then
    printf 'canary.sh: choose only one packet emitter\n' >&2
    usage >&2
    exit 64
fi

# --- Result vocabulary ------------------------------------------------------
PASSES=(); FAILURES=(); UNMEASURED=()
note_pass() { PASSES+=("$1"); printf '[PASS]         %-12s %s\n' "$1" "$2"; }
note_fail() { FAILURES+=("$1"); printf '[FAIL]         %-12s %s\n' "$1" "$2"; }
note_unmeasured() { UNMEASURED+=("$1"); printf '[NOT MEASURED] %-12s %s\n' "$1" "$2"; }

route() {  # route <probe> <STATUS> <detail>
    case "$2" in
        PASS) note_pass "$1" "$3" ;;
        FAIL) note_fail "$1" "$3" ;;
        *)    note_unmeasured "$1" "$3" ;;
    esac
}

# --- The packet Chrono dispatches -------------------------------------------
# Printed, never written: this program's write scope does not include an inbox,
# and Chrono owns dispatch. Redirect it into departments/coding/inbox/<id>.md.
emit_packet() {
    local id="$1"
    cat <<PACKET_EOF
---
id: ${id}
run_id: ${id}
to_model: claude
specialist: backend-engineer
source_namespace: coding
mode: project
memory_aperture: default
parallel_safe: true
direct_lane_work_allowed: true
review_triggers: []
return_artifact: departments/coding/outbox/${id}-response.md
write_scope: ["departments/coding/outbox/${id}-response.md"]
---

# Live capability canary

Do exactly three things and nothing else. This packet is deliberately trivial:
it measures the transport, not the work.

1. Run \`git rev-parse --short HEAD\` and paste the literal output.
2. Invoke the project skill named \`probe-canary\`. Quote, **verbatim**, the
   bolded claim its first sentence makes about what reaching that file proves.
   Do not paraphrase it and do not reconstruct it from memory -- the exact
   wording is the measurement.
3. Write your response envelope to the return_artifact path above.

If the skill does not resolve, say so and paste the literal error. An absent
skill is a real result; an invented quotation is not.
PACKET_EOF
}

emit_mcp_packet() {
    local id="$1"
    cat <<PACKET_EOF
---
id: ${id}
run_id: ${id}
to_model: gpt-codex
specialist: systems-engineer
source_namespace: coding
mode: project
memory_aperture: default
parallel_safe: true
direct_lane_work_allowed: true
review_triggers: []
return_artifact: departments/coding/outbox/${id}-response.md
write_scope: ["departments/coding/outbox/${id}-response.md"]
---

# Live Codex MCP-surface canary

Do exactly two things and nothing else. This packet measures the MCP surface of
the systems-engineer@gpt-codex board worker.

1. Enumerate the MCP server namespaces exposed by THIS worker's live tool
   inventory. Do not read an adapter or config file, and do not use a child
   \`codex mcp list\`: that starts a different process and reports configuration,
   not this worker's callable surface. If the runtime provides \`ALL_TOOLS\`,
   enumerate names beginning \`mcp__\`, extract the component between the first
   two \`__\` separators, deduplicate, and sort. Otherwise use the runtime's
   equivalent live tool-manifest operation. Also enumerate every complete tool
   name beginning \`mcp__codex_apps__\`; the bridge name alone is not a surface
   measurement. Make one bounded read-only call to every namespace found. Paste
   the literal inventory command/expression and literal output, then emit exactly
   one single-line record with sorted unique arrays (a prefix belongs in
   \`successful_probes\` only after a non-error call):

   \`MCP_SURFACE_JSON: {"codex_apps_tools":["mcp__codex_apps__<tool>"],"inventory_command":"<literal command or expression>","server_prefixes":["<runtime prefix>"],"successful_probes":["<runtime prefix>"]}\`

2. Write your response envelope to the return_artifact path above.
PACKET_EOF
}

if [[ -n "${EMIT_PACKET_ID}" ]]; then
    emit_packet "${EMIT_PACKET_ID}"
    exit 0
fi
if [[ -n "${EMIT_MCP_PACKET_ID}" ]]; then
    emit_mcp_packet "${EMIT_MCP_PACKET_ID}"
    exit 0
fi

# --- Probes 1, 2, 3, 5, 6: adjudicated from live board evidence ---------------
# One python pass over the registry, the outbox and the notify receipts. The
# registry is multi-megabyte, so it is loaded once and every probe reads that
# one parse.
run_evidence_probes() {
    CANARY_ROOT="${CANARY_ROOT}" \
    CANARY_TASK="${TASK_ID}" \
    CANARY_MCP_TASK="${MCP_TASK_ID}" \
    CANARY_SENTINEL="${SKILL_SENTINEL}" \
    CANARY_MCP_EXPECTED_JSON="${MCP_SURFACE_EXPECTED_JSON}" \
    CANARY_MCP_MARKER="${MCP_SURFACE_MARKER}" \
    python3 -B - <<'PY'
import json
import os
import re
import sys
from pathlib import Path

root = Path(os.environ["CANARY_ROOT"])
task_id = os.environ.get("CANARY_TASK", "").strip()
mcp_task_id = os.environ.get("CANARY_MCP_TASK", "").strip() or task_id
sentinel = os.environ["CANARY_SENTINEL"]

def emit(probe, status, detail):
    print(f"{probe}|{status}|{detail}")

registry_path = root / "_state" / "active-tasks.json"

# POSITIVE CONTROL for every registry-derived probe. An unreadable or empty
# registry is the case where a silent no-op would otherwise read as clean: no
# entries means no mismatches means "all good". It is NOT MEASURED instead.
registry = None
registry_problem = None
if not registry_path.exists():
    registry_problem = (
        f"no registry at {registry_path} -- `_state/` is gitignored, so a linked "
        "worktree never carries it; run this from the main checkout"
    )
else:
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        registry_problem = f"registry unreadable: {exc}"
    else:
        if not isinstance(registry, dict) or not registry:
            registry_problem = "registry parsed but holds no entries"
            registry = None

def entry_for(tid):
    return registry.get(tid) if isinstance(registry, dict) else None

def artifact_present(entry):
    """Is the entry's DECLARED return_artifact actually on disk, non-empty?"""
    declared = str((entry or {}).get("return_artifact") or "").strip()
    if not declared:
        return None, ""
    candidate = root / declared
    if candidate.is_file() and candidate.stat().st_size > 0:
        return True, declared
    return False, declared

def persisted_task_prompt(entry, tid):
    """Load the task/attempt-bound assembled brief that survives dispatch."""
    if not isinstance(entry, dict):
        return None, "registry entry is absent"
    attempt_id = str(entry.get("delivery_attempt_id") or "").strip()
    generation = entry.get("delivery_generation")
    safe_component = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}")
    if not safe_component.fullmatch(tid) or not safe_component.fullmatch(attempt_id):
        return None, "registry task or delivery attempt id is unsafe or absent"
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        return None, "registry delivery generation is absent or invalid"
    context_path = (
        root / "_state" / "board-dispatch" / f"{tid}.{attempt_id}.context.json"
    )
    if context_path.is_symlink() or not context_path.is_file():
        return None, f"persisted assembled brief is absent: {context_path.name}"
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"persisted assembled brief is unreadable: {exc}"
    authority = context.get("authority") if isinstance(context, dict) else None
    prompt = context.get("task_prompt") if isinstance(context, dict) else None
    if (
        not isinstance(context, dict)
        or context.get("schema") != "go-live-trusted-context/v1"
        or not isinstance(authority, dict)
        or authority.get("task_id") != tid
        or authority.get("attempt_id") != attempt_id
        or authority.get("generation") != generation
        or not isinstance(prompt, str)
        or not prompt.strip()
    ):
        return None, "persisted assembled brief failed task/attempt binding"
    return prompt, None

# --- Probe 1: dispatch ------------------------------------------------------
# "A trivial task reaches a lane and returns." The evidence is delivery_history:
# `queued` alone means the packet was accepted, not that any lane ever saw it --
# which is exactly the shape the refused-before-host-admission fan-out left
# behind while every unit test stayed green.
if registry is None:
    emit("dispatch", "NOT_MEASURED", registry_problem)
elif not task_id:
    emit("dispatch", "NOT_MEASURED",
         "no --task given; Chrono runs the dispatch, this adjudicates it")
else:
    entry = entry_for(task_id)
    if entry is None:
        emit("dispatch", "NOT_MEASURED",
             f"{task_id} is not in the registry -- nothing to adjudicate")
    else:
        events = [
            str(h.get("event"))
            for h in entry.get("delivery_history") or []
            if isinstance(h, dict)
        ]
        claimed = "board-claimed" in events
        returned = "terminal" in events
        if claimed and returned:
            reason = ""
            for h in reversed(entry.get("delivery_history") or []):
                if isinstance(h, dict) and h.get("event") == "terminal":
                    reason = str(h.get("reason") or "")
                    break
            emit("dispatch", "PASS",
                 f"{task_id} reached lane {entry.get('delivery_lane')} and returned "
                 f"({reason or 'terminal, no reason recorded'})")
        else:
            emit("dispatch", "FAIL",
                 f"{task_id} delivery_history is {events or ['<empty>']}: "
                 f"claimed={claimed} returned={returned}")

# --- Probe 2: round trip ----------------------------------------------------
# The full orchestrator<->specialist path, which is where the fan-out defect
# actually lived. Three independent facts, all required: the envelope was
# written, the artifact was promoted to its declared path, and the notification
# spine emitted a receipt for this task.
receipts_dir = root / "_state" / "chrono-notify-receipts"
if registry is None:
    emit("round_trip", "NOT_MEASURED", registry_problem)
elif not task_id:
    emit("round_trip", "NOT_MEASURED",
         "no --task given; the round trip needs a real dispatch to adjudicate")
else:
    entry = entry_for(task_id)
    if entry is None:
        emit("round_trip", "NOT_MEASURED", f"{task_id} is not in the registry")
    else:
        ns = str(entry.get("source_namespace") or "coding")
        envelope = root / "departments" / ns / "outbox" / f"{task_id}-response.md"
        archived = root / "departments" / ns / "archive" / f"{task_id}.md"
        have_envelope = envelope.is_file() or archived.is_file()

        promoted, declared = artifact_present(entry)

        # POSITIVE CONTROL for the spine leg. An absent receipts directory means
        # the spine was never observable here, which is unmeasured; a present
        # directory with no receipt for a terminal task is a real failure. Doctor
        # already reports the spine and by its own admission could not measure
        # it -- that is the distinction this control draws.
        spine = None
        if receipts_dir.is_dir():
            spine = any(
                task_id in p.read_text(encoding="utf-8", errors="replace")
                for p in receipts_dir.glob("*.sent")
            )

        legs = [
            f"envelope={'yes' if have_envelope else 'NO'}",
            f"artifact={'yes' if promoted else ('NO:' + declared if declared else 'UNDECLARED')}",
            f"notified={'yes' if spine else ('NO' if spine is False else 'unmeasurable')}",
        ]
        if spine is None or promoted is None:
            emit("round_trip", "NOT_MEASURED",
                 "; ".join(legs) + " -- a leg had no observable input")
        elif have_envelope and promoted and spine:
            emit("round_trip", "PASS", "; ".join(legs))
        else:
            emit("round_trip", "FAIL", "; ".join(legs))

# --- Probe 3: skills FIRE (not merely project) ------------------------------
# The oracle is a phrase the lane can only produce by reading the skill file.
# scripts/python/validate_skill_wiring.py already proves the file is wired and
# well-formed; wiring is projection. This asks the different question -- did a
# runtime actually load and execute it.
skill_file = root / ".claude" / "skills" / "probe-canary" / "SKILL.md"
if not skill_file.is_file():
    emit("skills", "NOT_MEASURED",
         f"oracle absent: no {skill_file.relative_to(root) if root in skill_file.parents else skill_file}")
elif sentinel not in skill_file.read_text(encoding="utf-8"):
    # The oracle drifted. Reporting PASS/FAIL off a sentinel the skill no longer
    # contains would be measuring nothing at all.
    emit("skills", "NOT_MEASURED",
         f"oracle broken: SKILL.md no longer contains the sentinel {sentinel!r}")
elif registry is None:
    emit("skills", "NOT_MEASURED", registry_problem)
elif not task_id:
    emit("skills", "NOT_MEASURED",
         "no --task given; only a lane's own artifact can show a skill fired")
else:
    entry = entry_for(task_id)
    promoted, declared = artifact_present(entry) if entry else (False, "")
    # A task that was never ASKED to fire the skill cannot answer the question.
    # Without this the probe reports FAIL for every ordinary board task, which
    # is a fabricated finding -- and a probe that cries wolf gets ignored
    # exactly like doctor's permanently-yellow warnings did.
    request_prompt, request_problem = persisted_task_prompt(entry, task_id)
    asked = request_prompt is not None and "probe-canary" in request_prompt
    if not entry or not promoted:
        emit("skills", "NOT_MEASURED",
             f"{task_id} promoted no artifact to read; the skills oracle needs one")
    elif request_problem:
        emit("skills", "NOT_MEASURED",
             f"{task_id} ask evidence is unavailable: {request_problem}")
    elif not asked:
        emit("skills", "NOT_MEASURED",
             f"{task_id} was never asked to invoke probe-canary "
             "(no such instruction in its task/attempt-bound assembled brief); "
             "dispatch the packet from --emit-packet to measure this")
    else:
        text = (root / declared).read_text(encoding="utf-8", errors="replace")
        if sentinel in text:
            emit("skills", "PASS",
                 f"{task_id} quoted the probe-canary sentinel: the skill was loaded and run")
        else:
            emit("skills", "FAIL",
                 f"{task_id} produced an artifact but never quoted the sentinel -- "
                 "projected, not fired")

# --- Probe 5: labelling / organisation --------------------------------------
# Do artifacts land where the contract said they would? Sampled over the most
# recent terminal tasks so the answer is about current behaviour, not history.
SAMPLE = 12
if registry is None:
    emit("labelling", "NOT_MEASURED", registry_problem)
else:
    terminal = [
        (tid, e) for tid, e in registry.items()
        if isinstance(e, dict)
        and str(e.get("status") or "") in {"complete", "completed", "needs_review"}
        and str(e.get("return_artifact") or "").strip()
    ]
    terminal.sort(key=lambda kv: str(kv[1].get("dispatched_at") or ""))
    sample = terminal[-SAMPLE:]
    if not sample:
        # POSITIVE CONTROL: an empty sample proves nothing. Zero mismatches out
        # of zero tasks is the silent no-op this vocabulary exists to catch.
        emit("labelling", "NOT_MEASURED",
             "no terminal task in the registry declares a return_artifact")
    else:
        missing = [tid for tid, e in sample if not artifact_present(e)[0]]
        if missing:
            emit("labelling", "FAIL",
                 f"{len(missing)}/{len(sample)} recent tasks: declared return_artifact "
                 f"absent on disk ({', '.join(missing[:4])})")
        else:
            emit("labelling", "PASS",
                 f"{len(sample)}/{len(sample)} recent tasks: artifact present at its "
                 "declared path")

# --- Probe 6: board-spawned MCP surface -------------------------------------
# Configuration is not evidence. The emitted packet asks the worker to derive
# server namespaces from its own live tool manifest and to make one bounded
# read-only call through every namespace. The expected list is NOT in the
# packet, so an artifact can only match it by measuring (or fabricating) the
# runtime result; the literal command/output requirement makes fabrication
# reviewable in the same way as the skill sentinel above.
expected_mcp_json = os.environ["CANARY_MCP_EXPECTED_JSON"]
mcp_marker = os.environ["CANARY_MCP_MARKER"]
try:
    expected_mcp = json.loads(expected_mcp_json)
except json.JSONDecodeError as exc:
    emit("mcp_surface", "NOT_MEASURED", f"canary expectation is invalid JSON: {exc}")
else:
    if (
        not isinstance(expected_mcp, list)
        or not expected_mcp
        or any(not isinstance(item, str) or not item for item in expected_mcp)
        or expected_mcp != sorted(set(expected_mcp))
    ):
        emit("mcp_surface", "NOT_MEASURED",
             "canary expectation is not a sorted unique non-empty string list")
    elif registry is None:
        emit("mcp_surface", "NOT_MEASURED", registry_problem)
    elif not mcp_task_id:
        emit("mcp_surface", "NOT_MEASURED",
             "no --mcp-task or --task given; only a board worker can expose its live tool manifest")
    else:
        entry = entry_for(mcp_task_id)
        promoted, declared = artifact_present(entry) if entry else (False, "")
        request_prompt, request_problem = persisted_task_prompt(entry, mcp_task_id)
        asked = request_prompt is not None and mcp_marker in request_prompt
        if not entry or not promoted:
            emit("mcp_surface", "NOT_MEASURED",
                 f"{mcp_task_id} promoted no artifact containing a live MCP report")
        elif request_problem:
            emit("mcp_surface", "NOT_MEASURED",
                 f"{mcp_task_id} ask evidence is unavailable: {request_problem}")
        elif not asked:
            emit("mcp_surface", "NOT_MEASURED",
                 f"{mcp_task_id} was never asked for {mcp_marker.rstrip(':')} evidence "
                 "in its task/attempt-bound assembled brief")
        else:
            artifact_text = (root / declared).read_text(
                encoding="utf-8", errors="replace"
            )
            reports = [
                line[len(mcp_marker):].strip()
                for line in artifact_text.splitlines()
                if line.startswith(mcp_marker)
            ]
            if len(reports) != 1:
                emit("mcp_surface", "NOT_MEASURED",
                     f"artifact contains {len(reports)} {mcp_marker.rstrip(':')} records; expected one")
            else:
                try:
                    report = json.loads(reports[0])
                except json.JSONDecodeError as exc:
                    emit("mcp_surface", "NOT_MEASURED",
                         f"artifact MCP report is invalid JSON: {exc}")
                else:
                    expected_keys = {
                        "codex_apps_tools", "inventory_command", "server_prefixes",
                        "successful_probes"
                    }
                    visible = report.get("server_prefixes") if isinstance(report, dict) else None
                    successful = report.get("successful_probes") if isinstance(report, dict) else None
                    codex_apps_tools = report.get("codex_apps_tools") if isinstance(report, dict) else None
                    command = report.get("inventory_command") if isinstance(report, dict) else None
                    lists_are_valid = all(
                        isinstance(values, list)
                        and all(isinstance(item, str) and item for item in values)
                        and values == sorted(set(values))
                        for values in (visible, successful)
                    )
                    codex_apps_tools_are_valid = (
                        isinstance(codex_apps_tools, list)
                        and all(
                            isinstance(item, str)
                            and item.startswith("mcp__codex_apps__")
                            and item != "mcp__codex_apps__"
                            for item in codex_apps_tools
                        )
                        and codex_apps_tools == sorted(set(codex_apps_tools))
                    )
                    if (
                        not isinstance(report, dict)
                        or set(report) != expected_keys
                        or not isinstance(command, str)
                        or not command.strip()
                        or "\n" in command
                        or not lists_are_valid
                        or not codex_apps_tools_are_valid
                    ):
                        emit("mcp_surface", "NOT_MEASURED",
                             "artifact MCP report has the wrong schema or unsorted values")
                    elif ("codex_apps" in visible) != bool(codex_apps_tools):
                        emit("mcp_surface", "NOT_MEASURED",
                             "artifact MCP report did not enumerate the visible codex_apps bridge")
                    elif visible == expected_mcp and successful == expected_mcp:
                        emit("mcp_surface", "PASS",
                             f"live prefixes and bounded calls match {expected_mcp}; "
                             f"codex_apps tools={len(codex_apps_tools)}")
                    else:
                        missing = sorted(set(expected_mcp) - set(visible))
                        unexpected = sorted(set(visible) - set(expected_mcp))
                        unprobed = sorted(set(visible) - set(successful))
                        emit("mcp_surface", "FAIL",
                             f"expected={expected_mcp}; visible={visible}; "
                             f"missing={missing}; unexpected={unexpected}; "
                             f"no successful bounded call={unprobed}")
PY
}

# --- Probe 4: memory record -> recall round trip -----------------------------
# A note COUNT cannot answer this. doctor.sh already warns that auto-capture
# wrote no note six times in seven days and still cannot say whether recall
# works; those are different subsystems and only a round trip separates them.
#
# The pre-recall of the nonce is the positive control: it must return ZERO
# hits. Without it a recall that matched everything, or one served from a stale
# index, would look identical to a working one.
run_memory_probe() {
    if [[ "${MEMORY_WRITE}" == 0 ]]; then
        route memory NOT_MEASURED "--no-memory-write given; a read-only check cannot prove record->recall"
        return
    fi
    if [[ ! -x "${CHRONO_PY}" ]]; then
        route memory NOT_MEASURED "no vault interpreter at ${CHRONO_PY}"
        return
    fi
    if [[ -z "${CHRONO_VAULT_ROOT:-}" ]]; then
        # Known board-spawn gotcha: the vault fails closed with the root unset,
        # and a failed-closed vault must not read as a working one.
        route memory NOT_MEASURED "CHRONO_VAULT_ROOT is unset; the vault fails closed"
        return
    fi
    local out
    out="$(PYTHONPATH="${VAULT_ROOT}/plugins/chrono-vault" "${CHRONO_PY}" -B - <<'PY' 2>&1
import uuid
try:
    import notes
    import recall as recall_mod
except Exception as exc:  # noqa: BLE001 - any import failure is unmeasured
    print(f"NOT_MEASURED|vault modules did not import: {exc}")
    raise SystemExit(0)

nonce = "canaryprobe" + uuid.uuid4().hex[:12]
try:
    pre = recall_mod.recall(query=nonce, limit=3)
except Exception as exc:  # noqa: BLE001
    print(f"NOT_MEASURED|pre-recall control could not run: {exc}")
    raise SystemExit(0)

if pre.get("results"):
    # The control failed, so nothing after it can be trusted.
    print(f"NOT_MEASURED|pre-recall control returned {len(pre['results'])} hits "
          f"for an unused nonce; the oracle is not discriminating")
    raise SystemExit(0)

try:
    written = notes.record("learning", {
        "title": f"canary memory round-trip probe {nonce}",
        "body": (f"bin/canary.sh live record->recall probe, token {nonce}. "
                 "Disposable telemetry, not a finding."),
        "status": "candidate",
    })
except Exception as exc:  # noqa: BLE001
    print(f"FAIL|record raised {type(exc).__name__}: {exc}")
    raise SystemExit(0)

note_id = written.get("id", "")
try:
    post = recall_mod.recall(query=nonce, limit=3)
except Exception as exc:  # noqa: BLE001
    print(f"FAIL|recorded {note_id} but recall raised {type(exc).__name__}: {exc}")
    raise SystemExit(0)

ids = [r.get("id") for r in post.get("results", [])]
if note_id and note_id in ids:
    print(f"PASS|recorded {note_id} and recalled it (pre-recall control: 0 hits, "
          f"index_dirty={written.get('index_dirty')})")
else:
    print(f"FAIL|recorded {note_id} but recall for its own nonce returned {ids or '[]'}")
PY
)"
    local status="${out%%|*}"
    local detail="${out#*|}"
    case "${status}" in
        PASS|FAIL|NOT_MEASURED) route memory "${status}" "${detail}" ;;
        *) route memory NOT_MEASURED "probe produced no verdict: ${out}" ;;
    esac
}

# --- Inverted controls ------------------------------------------------------
# Break each capability against a fixture and require the probe NOT to pass. If
# any inversion still reports PASS, this program is decoration and says so.
# Script-scoped, not `local`: the EXIT trap fires after the function has
# returned, so a function-local name is already out of scope by then and the
# fixture leaks (with `set -u`, loudly).
CANARY_FIXTURE=""
cleanup_fixture() { [[ -n "${CANARY_FIXTURE}" ]] && rm -rf "${CANARY_FIXTURE}"; }

run_self_test() {
    local bad=0
    CANARY_FIXTURE="$(mktemp -d "${TMPDIR:-/tmp}/canary-selftest.XXXXXX")" || exit 2
    trap cleanup_fixture EXIT
    local fixture="${CANARY_FIXTURE}"

    printf 'inverted controls (fixtures only, no live state touched)\n'

    # 1. Absent registry: everything registry-derived must be NOT MEASURED.
    local empty_root="${fixture}/empty"
    mkdir -p "${empty_root}"
    local out
    out="$(CANARY_ROOT_UNDER_TEST="${empty_root}" bash "${BASH_SOURCE[0]}" \
        --task TASK-X --no-memory-write 2>&1)"
    for probe in dispatch round_trip skills labelling mcp_surface; do
        if grep -q "^\[PASS\].* ${probe} " <<<"${out}"; then
            printf '  INVERSION FAILED  %-28s probe still reported PASS\n' "absent registry / ${probe}"
            bad=1
        else
            printf '  inversion holds    %-28s not a pass\n' "absent registry / ${probe}"
        fi
    done

    # 2. Broken capabilities against a populated fixture tree.
    local broken="${fixture}/broken"
    mkdir -p "${broken}/_state/chrono-notify-receipts" \
             "${broken}/departments/coding/outbox" \
             "${broken}/.claude/skills/probe-canary"
    printf 'this file deliberately omits the sentinel\n' \
        > "${broken}/.claude/skills/probe-canary/SKILL.md"
    cat > "${broken}/_state/active-tasks.json" <<'JSON_EOF'
{
  "TASK-2099-01-01-0001-brk": {
    "source_namespace": "coding",
    "status": "complete",
    "dispatched_at": "2099-01-01T00:00:00+00:00",
    "delivery_lane": "claude",
    "return_artifact": "departments/coding/outbox/TASK-2099-01-01-0001-brk-response.md",
    "delivery_history": [{"event": "queued", "at": "2099-01-01T00:00:00+00:00"}]
  }
}
JSON_EOF
    out="$(CANARY_ROOT_UNDER_TEST="${broken}" bash "${BASH_SOURCE[0]}" \
        --task TASK-2099-01-01-0001-brk --no-memory-write 2>&1)"
    # dispatch: queued but never claimed -> the refused-fan-out shape.
    grep -q '^\[FAIL\].* dispatch ' <<<"${out}" \
        && printf '  inversion holds    %-28s FAIL\n' "queued-but-never-claimed" \
        || { printf '  INVERSION FAILED  %-28s expected FAIL\n' "queued-but-never-claimed"; bad=1; }
    # round trip: no envelope, no artifact, no receipt.
    grep -qE '^\[(FAIL|NOT MEASURED)\].* round_trip ' <<<"${out}" \
        && printf '  inversion holds    %-28s not a pass\n' "severed round trip" \
        || { printf '  INVERSION FAILED  %-28s expected FAIL\n' "severed round trip"; bad=1; }
    # skills: the sentinel is gone from SKILL.md -> the oracle cannot see.
    grep -q '^\[NOT MEASURED\].* skills ' <<<"${out}" \
        && printf '  inversion holds    %-28s NOT MEASURED\n' "sentinel removed from skill" \
        || { printf '  INVERSION FAILED  %-28s expected NOT MEASURED\n' "sentinel removed from skill"; bad=1; }
    # labelling: the declared artifact was never promoted.
    grep -q '^\[FAIL\].* labelling ' <<<"${out}" \
        && printf '  inversion holds    %-28s FAIL\n' "artifact missing at declared path" \
        || { printf '  INVERSION FAILED  %-28s expected FAIL\n' "artifact missing at declared path"; bad=1; }

    # 3. Skills projected-but-not-fired: the sentinel is intact, the packet DID
    #    ask for the skill, and the artifact still never quotes it. This is the
    #    case the whole probe exists for, and it must be FAIL, not unmeasured.
    local mute="${fixture}/mute"
    mkdir -p "${mute}/_state/board-dispatch" \
             "${mute}/departments/coding/outbox" "${mute}/.claude/skills/probe-canary"
    printf 'If you are reading this, **%s** -- the runtime found this file.\n' \
        "${SKILL_SENTINEL}" > "${mute}/.claude/skills/probe-canary/SKILL.md"
    cat > "${mute}/_state/board-dispatch/TASK-2099-01-01-0002-mute.d-mute.context.json" <<'JSON_EOF'
{
  "schema": "go-live-trusted-context/v1",
  "authority": {
    "task_id": "TASK-2099-01-01-0002-mute",
    "attempt_id": "d-mute",
    "generation": 1
  },
  "task_prompt": "Invoke the project skill named probe-canary and quote it. Return MCP_SURFACE_JSON: evidence."
}
JSON_EOF
    printf '%s\n%s %s\n' \
        'I ran the task. I did not invoke any skill.' \
        "${MCP_SURFACE_MARKER}" \
        '{"codex_apps_tools":["mcp__codex_apps__fixture"],"inventory_command":"fixture inventory","server_prefixes":["chrono_research_arsenal","chrono_vault","codex_apps"],"successful_probes":["chrono_research_arsenal","chrono_vault","codex_apps"]}' \
        > "${mute}/departments/coding/outbox/TASK-2099-01-01-0002-mute-response.md"
    cat > "${mute}/_state/active-tasks.json" <<'JSON_EOF'
{
  "TASK-2099-01-01-0002-mute": {
    "source_namespace": "coding",
    "status": "complete",
    "dispatched_at": "2099-01-01T00:00:00+00:00",
    "delivery_attempt_id": "d-mute",
    "delivery_generation": 1,
    "return_artifact": "departments/coding/outbox/TASK-2099-01-01-0002-mute-response.md",
    "delivery_history": [
      {"event": "queued"}, {"event": "board-claimed"}, {"event": "terminal"}
    ]
  }
}
JSON_EOF
    out="$(CANARY_ROOT_UNDER_TEST="${mute}" bash "${BASH_SOURCE[0]}" \
        --task TASK-2099-01-01-0002-mute --no-memory-write 2>&1)"
    grep -q '^\[FAIL\].* skills ' <<<"${out}" \
        && printf '  inversion holds    %-28s FAIL\n' "skill asked for, never fired" \
        || { printf '  INVERSION FAILED  %-28s expected FAIL\n' "skill asked for, never fired"; bad=1; }
    # MCP surface: the worker returned a well-formed live report, but one
    # expected namespace is absent. This must be FAIL, not NOT MEASURED.
    grep -q '^\[FAIL\].* mcp_surface ' <<<"${out}" \
        && printf '  inversion holds    %-28s FAIL\n' "MCP namespace missing" \
        || { printf '  INVERSION FAILED  %-28s expected FAIL\n' "MCP namespace missing"; bad=1; }

    # 4. POSITIVE CONTROL for the adjudicator itself. A probe stuck at FAIL is
    #    as useless as one stuck at PASS: it would satisfy every inversion above
    #    while measuring nothing. On a fixture where all five capabilities work,
    #    all five must report PASS.
    local good="${fixture}/good"
    mkdir -p "${good}/_state/chrono-notify-receipts" \
             "${good}/_state/board-dispatch" "${good}/departments/coding/outbox" \
             "${good}/.claude/skills/probe-canary"
    printf 'If you are reading this, **%s** -- the runtime found this file.\n' \
        "${SKILL_SENTINEL}" > "${good}/.claude/skills/probe-canary/SKILL.md"
    cat > "${good}/_state/board-dispatch/TASK-2099-01-01-0003-good.d-good.context.json" <<'JSON_EOF'
{
  "schema": "go-live-trusted-context/v1",
  "authority": {
    "task_id": "TASK-2099-01-01-0003-good",
    "attempt_id": "d-good",
    "generation": 1
  },
  "task_prompt": "Invoke the project skill named probe-canary and quote it. Return MCP_SURFACE_JSON: evidence."
}
JSON_EOF
    printf 'HEAD abc1234. The skill says: %s.\n%s {"codex_apps_tools":["mcp__codex_apps__fixture"],"inventory_command":"fixture inventory","server_prefixes":%s,"successful_probes":%s}\n' \
        "${SKILL_SENTINEL}" "${MCP_SURFACE_MARKER}" \
        "${MCP_SURFACE_EXPECTED_JSON}" "${MCP_SURFACE_EXPECTED_JSON}" \
        > "${good}/departments/coding/outbox/TASK-2099-01-01-0003-good-response.md"
    printf '{"event_key":"25|TASK-2099-01-01-0003-good|complete"}\n' \
        > "${good}/_state/chrono-notify-receipts/good.sent"
    cat > "${good}/_state/active-tasks.json" <<'JSON_EOF'
{
  "TASK-2099-01-01-0003-good": {
    "source_namespace": "coding",
    "status": "complete",
    "dispatched_at": "2099-01-01T00:00:00+00:00",
    "delivery_lane": "claude",
    "delivery_attempt_id": "d-good",
    "delivery_generation": 1,
    "return_artifact": "departments/coding/outbox/TASK-2099-01-01-0003-good-response.md",
    "delivery_history": [
      {"event": "queued"},
      {"event": "board-claimed"},
      {"event": "terminal", "reason": "board-receipt:complete"}
    ]
  }
}
JSON_EOF
    out="$(CANARY_ROOT_UNDER_TEST="${good}" bash "${BASH_SOURCE[0]}" \
        --task TASK-2099-01-01-0003-good --no-memory-write 2>&1)"
    for probe in dispatch round_trip skills labelling mcp_surface; do
        if grep -q "^\[PASS\].* ${probe} " <<<"${out}"; then
            printf '  control holds      %-28s PASS\n' "working fixture / ${probe}"
        else
            printf '  CONTROL FAILED     %-28s probe never passes; it measures nothing\n' \
                "working fixture / ${probe}"
            bad=1
        fi
    done

    # 5. Memory: a vault that fails closed must never read as a working one.
    # No live write happens: the unset root is refused before record is reached.
    out="$(env -u CHRONO_VAULT_ROOT bash "${BASH_SOURCE[0]}" 2>&1)"
    grep -q '^\[PASS\].* memory ' <<<"${out}" \
        && { printf '  INVERSION FAILED  %-28s expected not-a-pass\n' "vault root unset"; bad=1; } \
        || printf '  inversion holds    %-28s not a pass\n' "vault root unset"

    if (( bad )); then
        printf '\nself-test FAILED: a probe cannot fail, so it is not a gate.\n'
        return 1
    fi
    printf '\nself-test passed: every probe demonstrably fails when its capability is broken.\n'
    return 0
}

if (( SELF_TEST )); then
    run_self_test
    exit $?
fi

# --- Run --------------------------------------------------------------------
printf '=== live capability canary ===\n'
printf 'root: %s\n' "${CANARY_ROOT}"
[[ -n "${TASK_ID}" ]] && printf 'adjudicating: %s\n' "${TASK_ID}"
[[ -n "${MCP_TASK_ID}" ]] && printf 'adjudicating MCP surface: %s\n' "${MCP_TASK_ID}"
printf '\n'

while IFS='|' read -r probe status detail; do
    [[ -z "${probe}" ]] && continue
    route "${probe}" "${status}" "${detail}"
done < <(run_evidence_probes)

run_memory_probe

printf '\nsummary: %d pass, %d fail, %d not measured\n' \
    "${#PASSES[@]}" "${#FAILURES[@]}" "${#UNMEASURED[@]}"

if (( ${#UNMEASURED[@]} )); then
    printf '\nNOT MEASURED is not a pass. Chrono runs the two role-specific packets:\n'
    printf '  CORE_ID=TASK-$(date -u +%%Y-%%m-%%d-%%H%%M)-canary\n'
    printf '  MCP_ID="${CORE_ID}-mcp"\n'
    printf '  bin/canary.sh --emit-packet "$CORE_ID" > departments/coding/inbox/"$CORE_ID".md\n'
    printf '  bin/canary.sh --emit-mcp-packet "$MCP_ID" > departments/coding/inbox/"$MCP_ID".md\n'
    printf '  bin/send-task.sh departments/coding/inbox/"$CORE_ID".md\n'
    printf '  bin/send-task.sh departments/coding/inbox/"$MCP_ID".md\n'
    printf '  # wait for both envelopes, then:\n'
    printf '  bin/canary.sh --task "$CORE_ID" --mcp-task "$MCP_ID"\n'
fi

if (( ${#FAILURES[@]} )); then
    exit 1
fi
if (( ${#UNMEASURED[@]} )); then
    exit 2
fi
exit 0
