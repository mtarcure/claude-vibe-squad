#!/usr/bin/env bash
# Persistent NON-model V2 controller for one admitted, boundary-scoped launch.
set -euo pipefail
umask 077
trusted_host_path="${TRUSTED_HOST_PATH:-${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}}"
unset TRUSTED_HOST_PATH
board_transcript_fd="${BOARD_TRANSCRIPT_FD:-}"
unset BOARD_TRANSCRIPT_FD
board_dispatch_descriptor="${BOARD_DISPATCH_DESCRIPTOR_PATH:-}"
unset BOARD_DISPATCH_DESCRIPTOR_PATH
PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

# Runtime authority for the memory audit home.  It must not follow VAULT_ROOT:
# a missing vault is the failure this trail exists to retain.  The launcher has
# the same entry-point default, held byte-identical by
# _state/v4-audit/vault-audit-dir/test_worker_unavailable_event.py; this
# supervisor remains authoritative for plain-shell board launches.
export CHRONO_VAULT_AUDIT_DIR="${CHRONO_VAULT_AUDIT_DIR:-${HOME:-/var/tmp/chrono-vault-${EUID}}/.local/state/chrono-vault/audit}"

usage() {
  echo "Usage: board-supervisor.sh trusted-launch CONTEXT.json"
  echo "       board-supervisor.sh trusted-launch --strict CONTEXT.json"
  echo "       board-supervisor.sh detached-launch CONTEXT.json LOG RECEIPT FAILURE_MARKER BUILDER REPO_ROOT TASK_ID LANE RETURN_ARTIFACT NAMESPACE RECONCILER"
  echo "NON-model controller: validate -> sealed boundary launch + attestation"
  echo "  trusted-launch  DEFAULT trusted path (operator threat-model reframe 2026-07-22)."
  echo "                  Normal env, own worktree (2.3), scheduler-safe (2.1),"
  echo "                  lineage-rooted (2.4), no broker custody required."
  echo "  --strict        Opt-in untrusted-input path: authenticated FD-3 authority"
  echo "                  and final worker execution inside the settled Seatbelt profile."
  echo "  detached-launch Internal board transport: bounded trusted launch with a"
  echo "                  durable combined transcript, settlement, and reconciliation."
}

# Syntax is dependency-free. A caller with a malformed invocation must receive
# the precise usage contract even when a copied or partially deployed supervisor
# has none of its launch-time siblings yet.
if [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
case "${1:-}" in
  detached-launch)
    if [[ "$#" -ne 12 ]]; then
      usage >&2
      exit 64
    fi
    ;;
  trusted-launch)
    if [[ "${2:-}" == "--strict" ]]; then
      if [[ "$#" -ne 3 ]]; then
        usage >&2
        exit 64
      fi
    elif [[ "$#" -ne 2 ]]; then
      usage >&2
      exit 64
    fi
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac

# Doctor evidence uses the same root-independent local-state pattern. This
# entry point remains authoritative for plain-shell board launches. It is a
# required dependency for a valid launch, so report its exact path if a partial
# deployment omitted it.
# shellcheck source=doctor-log-home.sh disable=SC1091
doctor_log_home_resolver="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/doctor-log-home.sh"
if [[ ! -f "$doctor_log_home_resolver" ]]; then
  printf 'board-supervisor.sh: required launch infrastructure is missing: %s\n' \
    "$doctor_log_home_resolver" >&2
  exit 1
fi
source "$doctor_log_home_resolver" || exit $?
export CHRONO_DOCTOR_LOG_DIR

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Six downstream consumers fall back to a hardcoded "v2" when SQUAD_BASE_BRANCH
# is unset -- the worktree pool, the trusted launch request, the integration
# target branch, launch hygiene (x2) and worktree isolation. On any branch that
# is not literally "v2" those defaults silently branch workers off the wrong
# ref, and the failure is invisible: the worker gets a clean worktree holding
# somebody else's code. send-task.sh derives the value from the checkout and
# exports it, so the literals normally never fire; derive it here too so a
# supervisor reached by any other path cannot quietly disagree with the
# checkout it is running from. git is present on the restricted PATH above.
if [[ -z "${SQUAD_BASE_BRANCH:-}" ]]; then
    _vs_branch="$(git -C "$repo_root" branch --show-current 2>/dev/null || true)"
    if [[ -n "$_vs_branch" ]]; then
        SQUAD_BASE_BRANCH="$_vs_branch"
        export SQUAD_BASE_BRANCH
    fi
    unset _vs_branch
fi
readonly python_bin="/usr/bin/python3"
# Structured receipts go to STDOUT, always. The detached transport reads this
# process's stdout as the one machine channel and hands it to the finalizer;
# stderr is the transcript. Until 2026-08-10 both denials below printed a
# receipt to stderr and were only ever read because the detached wrapper merged
# the streams with `2>&1`. Now that stderr goes to the transcript descriptor
# instead, a receipt written there would vanish from the machine channel and the
# attempt would terminalise as an unexplained empty capture.
if [[ ! -x "$python_bin" ]]; then
  echo '{"status":"denied","reason":"canonical /usr/bin/python3 unavailable"}'
  exit 74
fi

if [[ "$EUID" -eq 0 ]]; then
  echo '{"status":"denied","reason":"supervisor refuses root execution"}'
  exit 74
fi

if [[ "${1:-}" == "detached-launch" ]]; then
  context_file="$2"
  log_path="$3"
  receipt_path="$4"
  failure_marker="$5"
  context_builder="$6"
  vault_root="$7"
  task_id="$8"
  lane="$9"
  return_artifact="${10}"
  compatibility_namespace="${11}"
  reconciler="${12}"
  require_vault_root() {
    if [[ ! -d "$vault_root" ]]; then
      # A vanished root cannot publish or reconcile any further state. This is
      # terminal, not an uncertain process-identity condition: never route it
      # through the resumable SIGSTOP path used by trusted-launch cleanup.
      printf 'board supervisor blocked: vault root disappeared: %s\n' \
        "$vault_root" >&2
      exit 75
    fi
  }
  require_vault_root
  if [[ -z "$board_dispatch_descriptor" ]]; then
    echo '{"status":"denied","reason":"board dispatch descriptor path unavailable"}' \
      >>"$log_path"
    exit 74
  fi
  descriptor_ready=0
  for _ in {1..100}; do
    require_vault_root
    if [[ -f "$board_dispatch_descriptor" ]]; then
      descriptor_ready=1
      break
    fi
    /bin/sleep 0.01
  done
  require_vault_root
  if [[ "$descriptor_ready" -ne 1 ]]; then
    echo '{"status":"denied","reason":"board dispatch descriptor was not published"}' \
      >>"$log_path"
    exit 74
  fi
  set +e
  receipt_capture="$(/usr/bin/mktemp "${receipt_path}.capture.XXXXXX")"
  if [[ -z "$receipt_capture" ]]; then
    printf "receipt capture staging failed\n" >"$failure_marker"
    exit 70
  fi
  exec 4>>"$log_path"
  # STREAM SEPARATION. stdout is the machine channel and carries exactly one
  # structured receipt; stderr is diagnostics and goes to the transcript
  # descriptor, never into the capture.
  #
  # This was `2>&1` until 2026-08-10, which put both into `$receipt_capture`.
  # The finalizer parses the ENTIRE capture as one JSON object and substitutes a
  # blocked receipt when it is not, so a single stderr line -- a Python warning,
  # an `import` trace, a subprocess note -- was enough to make a SUCCESSFUL
  # launch terminalise as blocked, and enough to reduce a specific early
  # exception to a generic "invalid launch receipt". Board observability failed
  # in exactly the moment it was needed.
  #
  # FD 4 is already open (append) on the transcript above and is the same
  # descriptor the child frames its own child-transcript into, so diagnostics
  # stay durable and readable -- they are relocated, not discarded.
  TRUSTED_HOST_PATH="$trusted_host_path" BOARD_TRANSCRIPT_FD=4 \
    "$repo_root/bin/board-supervisor.sh" trusted-launch "$context_file" \
    >"$receipt_capture" 2>&4
  supervisor_rc=$?
  require_vault_root
  exec 4>&-
  /bin/cat "$receipt_capture" >>"$log_path"
  capture_rc=$?

  # trusted-launch fsyncs the private child-transcript FD. Force the separate
  # canonical receipt and the appended controller record to stable storage
  # before interpreting status or settling the detached run.
  "$python_bin" - "$log_path" "$receipt_capture" <<'PYEOF'
import os
import sys

for value in sys.argv[1:]:
    descriptor = os.open(value, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PYEOF
  sync_rc=$?
  "$python_bin" "$repo_root/scripts/python/board_process_truth.py" \
    finalize-receipt "$receipt_capture" "$board_dispatch_descriptor" \
    "$receipt_path" >>"$log_path" 2>&1
  finalize_rc=$?
  /bin/rm -f -- "$receipt_capture"
  supervisor_status="$(
    "$python_bin" - "$receipt_path" "$context_file" "$task_id" <<'PYEOF' \
      2>/dev/null
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    receipt = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    context = json.load(stream)
authority = context.get("authority")
if not isinstance(receipt, dict) or not isinstance(authority, dict):
    raise SystemExit(1)
expected_task = authority.get("task_id")
expected_attempt = authority.get("attempt_id")
expected_generation = authority.get("generation")
if expected_task != sys.argv[3]:
    raise SystemExit(1)
status = receipt.get("status")
if status not in {"launched", "blocked", "denied"}:
    raise SystemExit(1)
if (
    receipt.get("schema") != "board-dispatch-receipt/v2"
    or receipt.get("task_id") != expected_task
    or receipt.get("attempt_id") != expected_attempt
    or receipt.get("generation") != expected_generation
    or not isinstance(receipt.get("completed_at"), str)
    or not isinstance(receipt.get("terminal_outcome"), str)
):
    raise SystemExit(1)
print(status)
PYEOF
  )"
  if [[ "$capture_rc" -ne 0 || "$sync_rc" -ne 0 || "$finalize_rc" -ne 0 || "$supervisor_rc" -ne 0 || "$supervisor_status" != "launched" ]]; then
    # The receipt already records WHY the launch failed. Without lifting it here the
    # envelope only said "status blocked exit N; inspect <log>", so every block cost a
    # round trip into the log to learn whether the packet was too large, the mode
    # unknown, return_artifact missing, or the response envelope malformed -- four
    # distinct causes that presented identically. Fail-open: an unreadable receipt
    # falls back to the previous generic line rather than breaking dispatch.
    blocked_detail="$(
      "$python_bin" - "$receipt_path" <<'PYBLOCKED' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        receipt = json.load(fh)
except Exception:
    raise SystemExit(0)
reason = receipt.get("reason")
if isinstance(reason, str) and reason.strip():
    print(" ".join(reason.split())[:600])
PYBLOCKED
    )"
    if ! "$python_bin" "$context_builder" blocked \
      --repo-root "$vault_root" \
      --context-file "$context_file" \
      --task-id "$task_id" \
      --lane "$lane" \
      --return-artifact "$return_artifact" \
      --compatibility-namespace "$compatibility_namespace" \
      --reason "${blocked_detail:+${blocked_detail} | }detached board supervisor status ${supervisor_status:-invalid} exit ${supervisor_rc}; inspect ${log_path}"; then
      printf "blocked completion publication failed\n" >"$failure_marker"
      exit 70
    fi
  fi
  if ! env RESPONSE_MIN_AGE_SECONDS=0 "$reconciler" --task-id "$task_id"; then
    printf "registry reconciliation failed\n" >"$failure_marker"
    exit 70
  fi
  child_worktree="$(
    "$python_bin" - "$receipt_path" "$context_file" "$vault_root" <<'PYEOF' \
      2>/dev/null
import json
from pathlib import Path
import re
import sys

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
context = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
authority = context.get("authority", {})
task_id = authority.get("task_id", "")
attempt_id = authority.get("attempt_id", "")
if (
    receipt.get("status") != "launched"
    or not isinstance(task_id, str)
    or not (
        re.search(r"-fanout-member-[1-9][0-9]*$", task_id)
        or re.search(r"-swarm-(?:gpt-codex|claude|gemini|kimi)$", task_id)
    )
):
    raise SystemExit(0)
expected = (
    Path(sys.argv[3]).resolve()
    / "_state"
    / "board-worktrees"
    / str(attempt_id)
)
observed = Path(str(receipt.get("worktree_root", ""))).resolve()
if observed != expected or not observed.is_dir():
    raise SystemExit(1)
print(observed)
PYEOF
  )"
  cleanup_select_rc=$?
  if [[ "$cleanup_select_rc" -ne 0 ]]; then
    printf "board child worktree cleanup identity failed\n" >"$failure_marker"
    exit 70
  fi
  if [[ -n "$child_worktree" ]]; then
    # A successful response proves its declared artifact, not that every extra
    # PoC/file in this child worktree was promoted. Retain it as a cleanup
    # candidate until an exact promotion manifest exists.
    printf 'worktree_cleanup_candidate=%s reason=promotion-proof-unavailable\n' \
      "$child_worktree" >>"$log_path"
  fi
  if ! "$python_bin" "$context_builder" cleanup-canary \
    --repo-root "$vault_root" \
    --context-file "$context_file" >/dev/null; then
    printf "canary cleanup failed\n" >"$failure_marker"
    exit 70
  fi
  printf 'board_supervisor_rc=%s status=%s\n' \
    "$supervisor_rc" "$supervisor_status" >>"$log_path"
  "$python_bin" - "$log_path" <<'PYEOF'
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PYEOF
  [[ "$capture_rc" -eq 0 && "$sync_rc" -eq 0 && "$finalize_rc" -eq 0 && "$supervisor_rc" -eq 0 && "$supervisor_status" == "launched" ]]
  exit
fi

if [[ "${1:-}" == "trusted-launch" ]]; then
  launch_mode="trusted"
  if [[ "${2:-}" == "--strict" ]]; then
    launch_mode="strict"
    context_file="$3"
  else
    context_file="$2"
  fi
  if [[ ! -f "$context_file" ]]; then
    echo '{"status":"denied","reason":"trusted-launch context file missing"}'
    exit 74
  fi
  # This controller composes the settled 1.2/2.1/2.2/2.3/2.4 primitives by
  # import. seatbelt_profile supplies audited literal exec grants for the
  # installed lane entrypoints and their exact runtimes. The final OS spawn is
  # never mocked: launch success means a real child returned zero, and every
  # nonzero result is blocked for reconciliation.
  REPO_ROOT="$repo_root" \
  LAUNCH_MODE="$launch_mode" \
  TRUSTED_HOST_PATH="$trusted_host_path" \
  BOARD_TRANSCRIPT_FD_VALUE="$board_transcript_fd" \
    exec "$python_bin" - "$context_file" <<'PYEOF'
import json
import os
import sys
import traceback

# --- structured receipt funnel -------------------------------------------------
# Deliberately ABOVE every other import, which is why the import block below is
# split. stdout of this process is the board's machine channel: the detached
# transport reads exactly one JSON object from it and the finalizer terminalises
# whatever it finds. Every EXPECTED failure here is already structured --
# deny() and block_after_provision() each print one JSON object -- but an
# UNEXPECTED exception during module initialisation printed a raw traceback
# instead, which the finalizer could only reduce to a generic "invalid launch
# receipt". The exception type, message and location were lost from the machine
# channel, so the most informative failures produced the least informative
# receipts.
#
# This covers the surface a local handler cannot: a failing repo import, and the
# plain OSError that WorktreePool construction can raise (its call site catches
# only WorktreeIsolationError). SystemExit is never routed to an excepthook, so
# deny() and block_after_provision() keep their exact payloads and exit codes;
# this fires only on a genuine crash.
#
# The traceback is not discarded. It goes to the board transcript -- the human
# channel -- so stdout stays one object while the detail stays readable.
def _funnel_note(text):
    """Best-effort transcript write, usable before write_board_note is defined."""
    writer = globals().get("write_board_note")
    if writer is not None:
        writer(text)
        return
    raw_descriptor = os.environ.get("BOARD_TRANSCRIPT_FD_VALUE", "")
    if not raw_descriptor:
        return
    try:
        descriptor = int(raw_descriptor)
        payload = ("board: " + str(text).strip() + "\n").encode("utf-8", "replace")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                return
            offset += written
        os.fsync(descriptor)
    except (OSError, TypeError, ValueError):
        return


def _uncaught_launch_exception(kind, value, trace):
    detail = "unreportable exception during trusted launch"
    try:
        try:
            message = " ".join(str(value).split())
        except Exception:  # noqa: BLE001 - a raising __str__ must not hide the type
            message = "<exception message is unprintable>"
        where = ""
        frames = traceback.extract_tb(trace)
        if frames:
            where = " at %s:%s" % (
                os.path.basename(frames[-1].filename or "<string>"),
                frames[-1].lineno,
            )
        detail = "%s%s: %s" % (
            getattr(kind, "__name__", None) or str(kind), where, message
        )
        detail = detail[:600]
        _funnel_note("uncaught trusted-launch exception: " + detail)
        _funnel_note("".join(traceback.format_exception(kind, value, trace))[-8192:])
    except Exception:  # noqa: BLE001 - the funnel itself must never crash
        pass
    try:
        print(json.dumps(
            {
                "status": "blocked",
                "reason": "trusted launch raised an uncaught exception: " + detail,
            },
            sort_keys=True,
        ))
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    # os._exit, not sys.exit: an excepthook cannot raise its way out, and 75 is
    # the same nonzero the post-provision block path uses.
    os._exit(75)


sys.excepthook = _uncaught_launch_exception
# --- end structured receipt funnel ---------------------------------------------

import hashlib
import hmac
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path
from types import MappingProxyType

repo_root = Path(os.environ["REPO_ROOT"])
sys.path.insert(0, str(repo_root / "scripts" / "python"))
sys.path.insert(0, str(repo_root / "plugins" / "chrono-vault"))
def deny(reason, failure_class=None):
    payload = {"status": "denied", "reason": str(reason)}
    if failure_class is not None:
        if failure_class not in globals().get("CLI_TRANSPORT_FAILURE_CLASSES", ()):
            raise ValueError("invalid CLI transport failure class")
        payload["failure_class"] = failure_class
    print(json.dumps(payload, sort_keys=True))
    sys.exit(74)


# Gemini is the only lane whose process cwd is not the worktree root. It must run
# from its lane directory: that is where `.gemini/settings.json` and `.gemini/agents`
# live, and it is the same cwd used to enumerate the authorized MCP inventory, so a
# launch from anywhere else would authorize servers the child never loads. Packet
# paths stay worktree-root relative, so this offset is reconciled after the run by
# reclaim_lane_cwd_outputs().
GEMINI_LANE_CWD_RELATIVE = "model-lanes/gemini"

# Set True once a launcher has streamed the child's stdout live to the board
# transcript fd, so the post-exec transcript write appends only stderr instead of
# duplicating the whole stdout block. Live streaming is what gives the dashboard a
# tailable .log instead of 0 bytes until the process exits.
_board_stdout_streamed = [False]


def write_board_note(text):
    """Append one controller-side line to the board transcript.

    Distinct from write_board_transcript(), which frames a child's stdout/stderr:
    a note is the board speaking, so it must not masquerade as child output.
    """
    raw_descriptor = os.environ.get("BOARD_TRANSCRIPT_FD_VALUE", "")
    if not raw_descriptor:
        return
    try:
        descriptor = int(raw_descriptor)
    except (TypeError, ValueError):
        return
    payload = ("board: " + str(text).strip() + "\n").encode("utf-8", "replace")
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                return
            offset += written
        os.fsync(descriptor)
    except OSError:
        return


def hold_for_operator_stop(reason):
    """Freeze once, resumably, after telling the operator exactly how to clear it.

    This used to be `while True: SIGSTOP`, which made SIGCONT useless -- resuming
    the process only looped it straight back into another stop, so the only exit
    was SIGKILL. On 2026-08-09 that froze a lane in state T for 48 minutes with a
    live descriptor, no receipt and no artifact, while the registry showed it
    in-flight forever. `vs-cancel-spawn.sh` refuses the same attempt for the same
    identity reason that got us here, so the documented cancel path could not
    clear it either.

    The freeze itself is right: the process-identity guard fired because a PID may
    have been recycled, and signalling an unverifiable process is worse than
    stalling. What was wrong is that the stall was permanent, undocumented and
    unresumable. Now it stops ONCE -- SIGCONT resumes it -- and the note carries
    the exact command to terminalise the attempt.
    """
    detail = " ".join(str(reason).split())[:600]
    recovery = (
        f"recover with: python3 {os.environ.get('BOARD_PROCESS_TRUTH', 'scripts/python/board_process_truth.py')} "
        f"reap {os.environ.get('VAULT_ROOT', '<vault>')} {os.environ.get('BOARD_LOG_PATH', '<attempt>.log')}"
    )
    write_board_note(
        f"process cleanup uncertain; operator Stop required: {detail} | {recovery} | "
        "or SIGCONT this pid to let it terminalise itself"
    )
    os.kill(os.getpid(), signal.SIGSTOP)
    # Reached only on SIGCONT. The attempt cannot be trusted to have cleaned up,
    # so it terminalises as blocked rather than pretending to have succeeded --
    # but it does terminalise, which is what stops the registry stranding it.
    block_after_provision(
        f"resumed after an operator stop; process cleanup was never confirmed: {detail}",
        failure_class="other",
    )


def write_board_transcript(stdout, stderr):
    raw_descriptor = os.environ.get("BOARD_TRANSCRIPT_FD_VALUE", "")
    if not raw_descriptor:
        return
    try:
        descriptor = int(raw_descriptor)
        descriptor_stat = os.fstat(descriptor)
    except (OSError, TypeError, ValueError) as exc:
        deny(f"board transcript descriptor is invalid: {exc}")
    if not stat.S_ISREG(descriptor_stat.st_mode):
        deny("board transcript descriptor is not a regular file")

    def bounded(value):
        data = str(value).encode("utf-8", errors="replace")
        limit = 1024 * 1024
        if len(data) <= limit:
            return data
        half = limit // 2
        omitted = len(data) - limit
        marker = (
            f"\n... board transcript truncated {omitted} bytes ...\n"
        ).encode("ascii")
        return data[:half] + marker + data[-half:]

    payload = (
        b"=== board child stdout ===\n"
        + bounded(stdout)
        + b"\n=== board child stderr ===\n"
        + bounded(stderr)
        + b"\n=== end board child transcript ===\n"
    )
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            deny("board transcript write made no progress")
        offset += written
    os.fsync(descriptor)


context_path = Path(sys.argv[1])
try:
    context = json.loads(context_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    deny(f"trusted-launch context is unreadable or not JSON: {exc}")

authority_fields = {
    "schema", "task_id", "attempt_id", "generation", "run_id",
    "author_family", "workload_class", "specialist", "lane", "mode_profile",
    "execution_kind",
    "repo_root", "pool_root", "canonical_role_path", "canonical_role_sha256",
    "lane_overlay_path", "lane_overlay_sha256", "executable", "executable_sha256",
    "lane_args", "write_paths", "read_scope", "depends_on", "resources",
    "scheduler_concurrency", "scheduler_capacities", "scheduler_settled",
    "network_scope",
    "action_scope", "budgets", "expected_result_path", "expected_outbox_path",
    "evidence_outputs",
    # CC-03: pins/fences the promoted response envelope must echo so the
    # reconciler can settle a capability/swarm/worker completion.
    "reconciliation_echo",
    "required_phase_ids", "verification_kinds", "operator_gates",
    "packet_sha256", "plan_sha256", "verification_contract_sha256",
    "selected_model_sha256", "profile_bundle_sha256", "capability_surface_sha256",
    "auth_class", "lane_policy_row_sha256",
    "memory_context",
    "active_board_tasks",
    "created_at", "expires_at",
    "nonce",
}
authority = None
authority_signing_key = None
authority_sha256 = ""
scheduler_snapshot_sha256 = ""
launch_mode = os.environ.get("LAUNCH_MODE")
# Backward compatibility: the authenticated schema is itself an explicit
# request for the strict ABI.  New callers should spell this as ``--strict``;
# unsigned/default trusted contexts can never enter this branch.
if (
    launch_mode == "trusted"
    and isinstance(context, dict)
    and set(context) == {"schema", "authority", "mac_sha256"}
    and context.get("schema") == "go-live-launch-context/v1"
):
    launch_mode = "strict"
strict_context = (
    launch_mode == "strict"
    and isinstance(context, dict)
    and set(context) == {"schema", "authority", "mac_sha256"}
    and context.get("schema") == "go-live-launch-context/v1"
)
trusted_context = (
    launch_mode == "trusted"
    and isinstance(context, dict)
    and set(context) == {"schema", "authority", "task_prompt"}
    and context.get("schema") == "go-live-trusted-context/v1"
)
raw_trusted_task_prompt = context.get("task_prompt", "") if trusted_context else ""
if strict_context or trusted_context:
    authority = context.get("authority")
    if (
        not isinstance(authority, dict)
        or set(authority) != authority_fields
        or authority.get("schema") != "go-live-authority/v1"
    ):
        deny("authenticated launch authority has the wrong fields")
    try:
        authority_bytes = json.dumps(
            authority,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        deny("authenticated launch authority is not canonical JSON")
    if strict_context:
        # Strict/untrusted ABI pins its one-shot authority key to FD 3.  The
        # trusted default deliberately does not require an external controller
        # identity; it uses a fresh in-process key only for internal envelope
        # integrity.
        try:
            authority_fd = 3
            authority_signing_key = os.read(authority_fd, 64)
            os.close(authority_fd)
        except OSError:
            deny("controller-held launch authority key FD is unavailable")
        if len(authority_signing_key) != 32:
            deny("controller-held launch authority key has the wrong length")
        expected_authority_mac = hmac.new(
            authority_signing_key, authority_bytes, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(
            expected_authority_mac, str(context.get("mac_sha256", ""))
        ):
            deny("launch authority MAC mismatch")
    else:
        authority_signing_key = os.urandom(32)
    authority_sha256 = hashlib.sha256(authority_bytes).hexdigest()
    now_for_authority = int(time.time())
    if (
        isinstance(authority["created_at"], bool)
        or not isinstance(authority["created_at"], int)
        or isinstance(authority["expires_at"], bool)
        or not isinstance(authority["expires_at"], int)
        or not authority["created_at"] <= now_for_authority <= authority["expires_at"]
    ):
        deny("launch authority is stale, expired, or not yet valid")
    for hash_field in (
        "packet_sha256", "plan_sha256", "verification_contract_sha256",
        "selected_model_sha256", "profile_bundle_sha256", "capability_surface_sha256",
        "lane_policy_row_sha256",
        "canonical_role_sha256", "lane_overlay_sha256", "executable_sha256",
        "nonce",
    ):
        value = authority[hash_field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            or value == "0" * 64
        ):
            deny(f"launch authority has an invalid {hash_field}")
    if authority["auth_class"] not in {"subscription", "managed-login", "gemini-api-key"}:
        deny("launch authority has an invalid auth_class")
    context = {
        "task_id": authority["task_id"],
        "attempt_id": authority["attempt_id"],
        "generation": authority["generation"],
        "specialist": authority["specialist"],
        "lane": authority["lane"],
        "repo_root": authority["repo_root"],
        "pool_root": authority["pool_root"],
        "canonical_role_path": authority["canonical_role_path"],
        "lane_overlay_path": authority["lane_overlay_path"],
        "executable": authority["executable"],
        "profile_bundle_sha256": authority["profile_bundle_sha256"],
        "workload_class": authority["workload_class"],
        "active_board_tasks": authority["active_board_tasks"],
    }
else:
    if launch_mode == "strict":
        deny("strict authenticated launch authority is required")
    deny(
        "trusted launch requires go-live-trusted-context/v1 fields "
        "or an authenticated strict context"
    )

trusted_task_prompt = raw_trusted_task_prompt
if trusted_context and (
    not isinstance(trusted_task_prompt, str)
    or not trusted_task_prompt.strip()
    or len(trusted_task_prompt.encode("utf-8")) > 32768
    or "\x00" in trusted_task_prompt
):
    deny("trusted task prompt is empty, invalid, or too large")

try:
    import worktree_isolation as wti
    import board_router
    import delegation_lineage
    from held_action_gate import HELD_CATEGORIES
    from board_process_truth import ProcessTruthError
    from clearance import (
        ClearanceError,
        project_worker_vault_environment,
        validate_memory_context,
    )
    from dispatch_context_builder import (
        CLI_TRANSPORT_FAILURE_CLASSES,
        DispatchContextError,
        ModeExitVerificationError,
        prepare_worktree_outputs,
        publish_prepared_worktree_outputs,
        reclaim_lane_cwd_outputs,
        lane_policy_evidence_for,
        selected_model_sha256_for,
        trusted_lane_args_for,
    )
    from lane_capability_enforcement import (
        CapabilityDenied,
        adapter_path_for,
        broker_chrono_vault_plan,
        chrono_vault_relay_server,
        cli_args_for_materialized,
        codex_chrono_vault_relay_args,
        load_json_mcp_servers,
        load_projection,
        load_tool_classes,
        materialize_role_config,
        parse_claude_enabled_plugins,
        parse_claude_project_plugin_dirs,
        parse_live_mcp_listing,
        plan_lane,
        _tool_gates_launch,
    )
    from role_context_compiler import compile_role_context
    from verification_contract import (
        ContractError,
        read_yaml_frontmatter,
        validate_verification_contract,
        verification_contract_sha256,
    )
    from runtime_envelope import RuntimeEnvelopeClaims, launch_task, seal_runtime_envelope
    from launch_hygiene import (
        HygieneError,
        ProcessGroupReaper,
        ResourceLimits,
        _load_task_request,
        _request_digest,
        audit_writable_scopes,
        close_writable_scopes,
        launch_if_canary_passes,
        run_preflight_canary,
    )
    from seatbelt_profile import (
        BROKER_RELAY_PYTHON,
        DEFAULT_LANE_PATH,
        HOST_HOME,
        LANE_CLI_PATHS,
        OFFLINE_LAUNCH_EXECUTABLES,
        scoped_lane_launch_profile,
    )
    from broker import (
        BrokerBinding,
        BrokerError,
        CONTEXT_ENV as VAULT_CONTEXT_ENV,
        ROOT_ALIASES as VAULT_ROOT_ALIASES,
        TOKEN_ENV as VAULT_BROKER_TOKEN_ENV,
        VaultBroker,
    )
except Exception as exc:  # noqa: BLE001 - fail-closed report, not a crash
    deny(f"trusted-launch dependency import failed: {exc}")

task_id = str(context["task_id"])
attempt_id = str(context["attempt_id"])
generation = context["generation"]
specialist = str(context["specialist"])
lane = str(context["lane"])
repo_path = Path(str(context["repo_root"]))
pool_root = Path(str(context["pool_root"]))
executable = Path(str(context["executable"]))


def sha256_file(path, failure_class=None):
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        deny(f"authenticated launch file is unavailable: {exc}", failure_class)
    return digest.hexdigest()

execution_kind = authority["execution_kind"]
if execution_kind == "lane":
    expected_executable = LANE_CLI_PATHS.get(lane)
    if expected_executable is None or executable != expected_executable:
        deny("lane launch executable does not match the installed lane entrypoint")
elif execution_kind == "offline-probe":
    if executable not in OFFLINE_LAUNCH_EXECUTABLES:
        deny("offline probe executable is not an approved inert probe")
else:
    deny("authenticated launch authority has an invalid execution kind")
if (
    not isinstance(authority["lane_args"], list)
    or any(not isinstance(item, str) for item in authority["lane_args"])
):
    deny("authenticated launch authority has invalid lane arguments")
board_dispatch_context = trusted_context and execution_kind == "lane"
if board_dispatch_context:
    try:
        controller_lane_args = trusted_lane_args_for(
            repo_path,
            lane=lane,
            specialist=specialist,
        )
        controller_model_sha256 = selected_model_sha256_for(
            repo_path,
            lane=lane,
            specialist=specialist,
        )
        controller_lane_policy = lane_policy_evidence_for(repo_path, lane)
    except DispatchContextError as exc:
        deny(f"trusted launch profile cannot be resolved: {exc}")
    if tuple(authority["lane_args"]) != controller_lane_args:
        deny("trusted launch lane arguments do not match the closed controller ABI")
    if authority["selected_model_sha256"] != controller_model_sha256:
        deny("trusted launch selected model does not match the profile registry")
    if any(authority[key] != controller_lane_policy[key] for key in controller_lane_policy):
        deny("trusted launch auth policy does not match the lane registry")
packet_path = None
packet_frontmatter = {}
pinned_contract = {}
canary_cleanup_requested = False
if board_dispatch_context:
    packet_scope_pattern = re.compile(
        rf"^departments/[^/]+/inbox/{re.escape(task_id)}\.md$"
    )
    packet_scope_entries = [
        item for item in authority["read_scope"] if packet_scope_pattern.fullmatch(item)
    ]
    if len(packet_scope_entries) != 1:
        deny("scheduler authority must name the exact inbox packet in read_scope")
    packet_path = repo_path / packet_scope_entries[0]
    if sha256_file(packet_path) != authority["packet_sha256"]:
        deny("inbox packet content does not match authenticated authority")
    try:
        packet_frontmatter = read_yaml_frontmatter(packet_path)
        pinned_contract = validate_verification_contract(
            packet_frontmatter.get("verification_contract")
        )
    except ContractError as exc:
        deny(f"canonical packet verification contract is invalid: {exc}")
    if verification_contract_sha256(pinned_contract) != authority[
        "verification_contract_sha256"
    ]:
        deny("canonical packet contract does not match the authenticated contract hash")
    canary_cleanup_requested = packet_frontmatter.get("board_canary_autoclean") is True
if (
    not isinstance(authority["action_scope"], list)
    or any(not isinstance(item, str) for item in authority["action_scope"])
    or not isinstance(authority["operator_gates"], list)
    or any(not isinstance(item, str) for item in authority["operator_gates"])
    or set(authority["operator_gates"]) != HELD_CATEGORIES
    or set(authority["action_scope"]).intersection(HELD_CATEGORIES)
):
    deny("lane authority must hold every effect category outside worker scope")
if sha256_file(authority["canonical_role_path"]) != authority["canonical_role_sha256"]:
    deny("canonical role content does not match authenticated authority")
if sha256_file(authority["lane_overlay_path"]) != authority["lane_overlay_sha256"]:
    deny("lane overlay content does not match authenticated authority")
resolved_executable = Path(os.path.realpath(executable))
if sha256_file(resolved_executable, "cli_missing") != authority["executable_sha256"]:
    deny("lane executable content does not match authenticated authority")


def load_gemini_api_key():
    home = os.environ.get("HOME", "")
    if not home or "\x00" in home:
        deny("Gemini credential home is unavailable")
    try:
        completed = subprocess.run(
            (
                "/bin/zsh",
                "-f",
                "-c",
                'source "$HOME/.config/shell/secrets.zsh" 2>/dev/null; '
                'print -rn -- "${GEMINI_API_KEY:-}"',
            ),
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={
                "HOME": home,
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
            timeout=10,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        deny(f"Gemini credential source failed: {exc}")
    value = completed.stdout
    if (
        completed.returncode != 0
        or not value
        or len(value) > 16384
        or "\x00" in value
        or "\n" in value
    ):
        deny("Gemini credential source did not provide one safe GEMINI_API_KEY")
    return value


def load_solodit_api_key():
    # The guarded-solodit MCP (Cyfrin Solodit findings search) authenticates
    # with SOLODIT_API_KEY, which lives only in the off-repo secret store — it
    # is never ambient in the board process. Source it the same bounded way as
    # the Gemini key, but BEST-EFFORT: a missing/unreadable key returns None so
    # guarded-solodit degrades to an upstream 401 at call time instead of
    # failing every board launch. This is not a launch gate.
    home = os.environ.get("HOME", "")
    if not home or "\x00" in home:
        return None
    try:
        completed = subprocess.run(
            (
                "/bin/zsh",
                "-f",
                "-c",
                'source "$HOME/.config/shell/secrets.zsh" 2>/dev/null; '
                'print -rn -- "${SOLODIT_API_KEY:-}"',
            ),
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={
                "HOME": home,
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
            timeout=10,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout
    if (
        completed.returncode != 0
        or not value
        or len(value) > 16384
        or "\x00" in value
        or "\n" in value
    ):
        return None
    return value


def load_research_api_keys():
    # Operator-approved credential widening (2026-07-28). The chrono-research-
    # arsenal MCP (xai_search, perplexity_search) authenticates with XAI_API_KEY
    # and PERPLEXITY_API_KEY, which live only in the off-repo secret store and are
    # never ambient in the board process. Source them the same bounded way as the
    # Gemini/Solodit keys, BEST-EFFORT: a missing/unreadable key is simply omitted
    # so the tool degrades to its own "key missing"/upstream error at call time
    # instead of failing the launch. Least-privilege: ONLY these two research
    # search keys, and only injected for lanes that host the research arsenal.
    home = os.environ.get("HOME", "")
    if not home or "\x00" in home:
        return {}
    try:
        completed = subprocess.run(
            (
                "/bin/zsh",
                "-f",
                "-c",
                'source "$HOME/.config/shell/secrets.zsh" 2>/dev/null; '
                'print -rn -- "${XAI_API_KEY:-}\t${PERPLEXITY_API_KEY:-}"',
            ),
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={
                "HOME": home,
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
            timeout=10,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0 or "\n" in completed.stdout:
        return {}
    parts = completed.stdout.split("\t")
    if len(parts) != 2:
        return {}
    keys = {}
    for name, value in (("XAI_API_KEY", parts[0]), ("PERPLEXITY_API_KEY", parts[1])):
        if value and len(value) <= 16384 and "\x00" not in value:
            keys[name] = value
    return keys


def load_github_mcp_token():
    # The `github` MCP (plugin:github:github -> api.githubcopilot.com) sends
    # GITHUB_PERSONAL_ACCESS_TOKEN as its bearer credential. It is never ambient
    # in the board process, so the scrubbed worker env rendered an EMPTY header
    # and GitHub answered `HTTP 400: Authorization header is badly formatted`.
    #
    # That was fatal until 2026-08-10: the launch gate read an unhealthy
    # authorized server as a hard denial, so every role authorizing github was
    # undispatchable while the same server stayed healthy in Chrono's own
    # session (measured 2026-08-09 on the research role, TASK-2026-08-09-0330).
    # This comment used to claim the tool "degrades at call time"; production
    # denied. `plan_lane` now separates structural absence (still fails closed)
    # from runtime health (degrades and is named in the receipt and the worker's
    # context), so the claim and the code agree.
    #
    # Bounded and best-effort, like the Solodit/research keys: a missing key is
    # omitted from the snapshot and reported under `credential_missing` rather
    # than failing the launch. Least-privilege: only this one token, and only
    # for a role that actually authorizes the github MCP.
    #
    # PREFER GITHUB_MCP_TOKEN. The MCP server itself reads
    # GITHUB_PERSONAL_ACCESS_TOKEN, so that is the name we must inject under, but
    # the VALUE is taken from GITHUB_MCP_TOKEN whenever it is set. That matters:
    # measured 2026-08-09, the ambient GITHUB_PERSONAL_ACCESS_TOKEN is a classic
    # PAT carrying `gist, read:org, repo, workflow` -- full write to every repo the
    # operator can reach, including the public release repo, plus workflow edit.
    # The two roles that authorize this MCP (research, bounty-researcher) both
    # ingest untrusted external web content, which is exactly the prompt-injection
    # combination the 2026-07-27 trust-boundary ratification named as the one real
    # risk. Setting a read-only fine-grained GITHUB_MCP_TOKEN in the secret store
    # downgrades that exposure with no code change here.
    home = os.environ.get("HOME", "")
    if not home or "\x00" in home:
        return None
    try:
        completed = subprocess.run(
            (
                "/bin/zsh",
                "-f",
                "-c",
                'source "$HOME/.config/shell/secrets.zsh" 2>/dev/null; '
                'print -rn -- "${GITHUB_MCP_TOKEN:-${GITHUB_PERSONAL_ACCESS_TOKEN:-}}"',
            ),
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={
                "HOME": home,
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
            timeout=10,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or "\n" in completed.stdout:
        return None
    token = completed.stdout
    if not token or len(token) > 16384 or "\x00" in token:
        return None
    return token


GUARDED_MCP_PREFIX = "guarded-"


def _mcp_server_tables(text):
    """Split raw TOML into ``[mcp_servers.<name>]`` table ranges.

    Raw text on purpose.  The canonical interpreter is /usr/bin/python3 (3.9),
    which has no ``tomllib``, and round-tripping the operator's live config
    through any serializer would silently drop its comments, ordering, and
    formatting.  We only ever slice whole line ranges out of the repo config
    and append them, so the operator's bytes are never rewritten.

    Multi-line basic/literal strings are tracked so a ``[`` inside one is not
    mistaken for a table header.  The parse is deliberately conservative: an
    unrecognized construct yields an *extra* detected name at worst, which can
    only suppress an overlay (fail-closed), never overwrite a live definition.
    """
    lines = text.splitlines(keepends=True)
    tables = []
    current = None
    in_multiline = False
    for index, line in enumerate(lines):
        odd_quotes = (line.count('"""') % 2 == 1) or (line.count("'''") % 2 == 1)
        if in_multiline:
            if odd_quotes:
                in_multiline = False
            continue
        if odd_quotes:
            in_multiline = True
            continue
        stripped = line.strip()
        if not stripped.startswith("[") or not stripped.endswith("]"):
            continue
        if current is not None:
            tables.append((current[0], current[1], index))
            current = None
        match = re.match(r"^\[\[?mcp_servers\.([A-Za-z0-9_-]+)", stripped)
        if match:
            current = (match.group(1), index)
    if current is not None:
        tables.append((current[0], current[1], len(lines)))
    return lines, tables


def _prepare_codex_home(base_home, repo_config, spawn_home):
    """Build a per-spawn CODEX_HOME that unions the live config with guarded MCPs.

    Design B: the operator's live ``~/.codex/config.toml`` is the base and stays
    authoritative for every server it names; we overlay ONLY
    ``[mcp_servers.guarded-*]`` tables from the repo lane config, and never over
    a server the base already defines.  Every other home entry (auth.json,
    sessions, history, skills, plugins, ...) is symlinked through, so the child
    keeps the operator's real Codex state and credentials.
    """
    base_config = base_home / "config.toml"
    base_text = base_config.read_text(encoding="utf-8") if base_config.is_file() else ""
    overlay_text = repo_config.read_text(encoding="utf-8") if repo_config.is_file() else ""

    _base_lines, base_tables = _mcp_server_tables(base_text)
    defined = {name for name, _start, _end in base_tables}
    overlay_lines, overlay_tables = _mcp_server_tables(overlay_text)

    overlaid = []
    blocks = []
    for name, start, end in overlay_tables:
        # Only the guarded security trio is ever added, and only when the live
        # config is silent about it.  chrono-vault and every other live server
        # therefore survive exactly as the operator configured them.
        if not name.startswith(GUARDED_MCP_PREFIX) or name in defined:
            continue
        blocks.append("".join(overlay_lines[start:end]).rstrip("\n") + "\n")
        if name not in overlaid:
            overlaid.append(name)

    merged = base_text
    if blocks:
        if merged and not merged.endswith("\n"):
            merged += "\n"
        merged += (
            "\n# --- generated by board-supervisor: spawn-time guarded-MCP overlay.\n"
            "# Source: model-lanes/gpt-codex/.codex/config.toml. Do not edit here.\n"
        )
        merged += "\n".join(blocks)

    spawn_home.mkdir(parents=True, exist_ok=True)
    os.chmod(spawn_home, 0o700)
    for entry in sorted(os.listdir(base_home)):
        if entry == "config.toml":
            continue
        link = spawn_home / entry
        if link.is_symlink() or link.exists():
            continue
        os.symlink(base_home / entry, link)

    target = spawn_home / "config.toml"
    staging = spawn_home / "config.toml.tmp"
    with open(staging, "w", encoding="utf-8") as handle:
        handle.write(merged)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, target)
    return overlaid


def _validated_trusted_host_path():
    candidate = os.environ.get("TRUSTED_HOST_PATH", DEFAULT_LANE_PATH)
    components = candidate.split(os.pathsep)
    if (
        not components
        or any(
            not component
            or component == "."
            or not Path(component).is_absolute()
            or any(ord(character) < 32 for character in component)
            for component in components
        )
    ):
        deny(
            "TRUSTED_HOST_PATH must contain only non-empty absolute "
            "components"
        )
    return candidate


def trusted_worker_environment(worker_lane):
    # Subscription lanes authenticate through their existing home/config
    # files.  Deliberately do not copy ambient API keys or unrelated secrets.
    allowed = {
        "HOME", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
        "USER", "LOGNAME",
        "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR",
        "SSL_CERT_FILE", "SSL_CERT_DIR",
        # Vault filesystem roots (PATHS, not secrets) are provisionally allowed;
        # the return below projects them by the validated aperture. Entitled
        # workers need CHRONO_VAULT_ROOT to record/recall, while `none` must not
        # receive either address. The Obsidian REST credential is deliberately
        # NOT here (optional human lens, off the recall correctness path).
        "CHRONO_VAULT_ROOT", "OBSIDIAN_VAULT_ROOT",
        # Independent audit home: unlike the roots above, this must survive an
        # unset/broken CHRONO_VAULT_ROOT and an attempt-worktree release.
        "CHRONO_VAULT_AUDIT_DIR",
        # Doctor reports must survive those same failures and remain visible to
        # worker-side status consumers.
        "CHRONO_DOCTOR_LOG_DIR",
    }
    environment = {
        key: value for key, value in os.environ.items()
        if key in allowed and isinstance(value, str) and "\x00" not in value
    }
    environment["PATH"] = _validated_trusted_host_path()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["NO_COLOR"] = "1"
    # The allowlist above only FORWARDS a variable that the supervisor already
    # has; it does not supply one. bin/launch-squad.sh defaults
    # CHRONO_VAULT_ROOT, the board path did not, so whether a worker got vault
    # access depended on who launched the supervisor -- silently, and
    # differently per spawn. Measured 2026-08-08: one lane reported
    # root_valid:true while a sibling in the same run got
    # "CHRONO_VAULT_ROOT must be set". Default it the same way launch-squad
    # does, and only to a directory that actually exists so a wrong path is
    # never injected.
    if not environment.get("CHRONO_VAULT_ROOT"):
        _default_vault_root = os.path.join(
            os.path.expanduser("~"), "Obsidian-Chrono"
        )
        if os.path.isdir(_default_vault_root):
            environment["CHRONO_VAULT_ROOT"] = _default_vault_root
    # Provide a CA trust store so TLS-using bounty tools in the worker have
    # anchors (the semgrep OCaml OTel client aborts exit 2 on "empty trust
    # anchors" without one). SSL_CERT_FILE is already in the allowlist above.
    for _ca_bundle in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem"):
        if os.path.exists(_ca_bundle):
            environment["SSL_CERT_FILE"] = _ca_bundle
            break
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        environment.pop(key, None)
    if worker_lane == "gemini":
        # Gemini CLI's configured gemini-api-key auth is the sole lane-specific
        # exception. Match launch-squad.sh: retain only GEMINI_API_KEY.
        environment["GEMINI_API_KEY"] = load_gemini_api_key()
    if worker_lane == "codex":
        # The Codex CLI reads ONE config.toml from CODEX_HOME (default
        # ~/.codex), and the operator's live config does not declare the
        # guarded security MCPs -- they live in the repo lane config. Codex has
        # no config-merge flag, so without this the capability gate below denies
        # every security spawn with "requires unconfigured MCP servers".
        # Build a per-spawn home that unions the two (design B) and point both
        # the `codex mcp list --json` enumeration and the child launch at it.
        base_home = Path(environment.get("HOME", "")) / ".codex"
        if base_home.is_dir():
            try:
                _prepare_codex_home(
                    base_home,
                    repo_path / "model-lanes" / "gpt-codex" / ".codex" / "config.toml",
                    repo_path / "_state" / "board-codex-homes" / attempt_id,
                )
            except OSError as exc:
                deny(f"Codex guarded-MCP home could not be prepared: {exc}")
            environment["CODEX_HOME"] = str(
                repo_path / "_state" / "board-codex-homes" / attempt_id
            )
    # Per-attempt scratch root, so build caches die with the attempt that made
    # them. Previously every lane inherited the ambient TMPDIR and pointed
    # GOCACHE/CARGO_TARGET_DIR at a fresh /tmp path that nothing ever reclaimed.
    # Measured 2026-08-06: 88 GB in /tmp, 52 GB of it in 32 GOCACHE-shaped
    # directories, one per finished Go/Cosmos lane. macOS only auto-purges /tmp
    # after 3 untouched days, which an active campaign keeps resetting.
    #
    # Deliberately /tmp/vs/<attempt>, NOT _state/board-scratch/<attempt>: a unix
    # socket path caps near 104 bytes and the _state form already consumes 97,
    # leaving 7 for a socket name. The /tmp form uses 43 and leaves 61.
    #
    # GOMODCACHE and the cargo registry are deliberately NOT scoped here. They
    # are download caches that dedup across lanes; per-attempt copies would
    # re-fetch every dependency on every dispatch.
    #
    # Best-effort by design: scratch that cannot be created falls back to the
    # ambient TMPDIR. A disk-hygiene optimisation must never block a dispatch.
    scratch_root = Path("/tmp/vs") / attempt_id if attempt_id else None
    if scratch_root is not None:
        try:
            (scratch_root / "gocache").mkdir(parents=True, exist_ok=True)
            (scratch_root / "cargo-target").mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        else:
            environment["TMPDIR"] = str(scratch_root)
            environment["GOCACHE"] = str(scratch_root / "gocache")
            environment["CARGO_TARGET_DIR"] = str(scratch_root / "cargo-target")
    # Projection happens at the call site after this controller-only copy has
    # been retained for the out-of-sandbox broker backend.  Keeping the two
    # objects distinct is what prevents a worker scrub from also erasing the
    # backend's required root, or a backend entitlement from leaking back into
    # the final CLI environment.
    return environment


memory_context_value = authority.get("memory_context")
try:
    memory_context_value = validate_memory_context(
        memory_context_value,
        task_id=authority["task_id"],
        attempt_id=authority["attempt_id"],
        generation=authority["generation"],
        mode=authority["mode_profile"],
        created_at=authority["created_at"],
    )
except (ClearanceError, TypeError, ValueError, UnicodeEncodeError):
    deny("launch authority has an invalid memory_context")


MANAGED_CREDENTIAL_NAMES = (
    "SOLODIT_API_KEY",
    "XAI_API_KEY",
    "PERPLEXITY_API_KEY",
    "GITHUB_PERSONAL_ACCESS_TOKEN",
)


def load_managed_credentials(worker_lane, authorized_mcps):
    """Read every managed credential ONCE per attempt into a frozen snapshot.

    This used to be fused into `project_worker_credentials`, which pops each
    managed name and then RE-INVOKES the secret loaders. That was fine while it
    ran once; it is called twice per attempt since the health probe started
    running against the projected environment, and two reads of a mutable
    secret store are a real TOCTOU: if the first read returns a token and the
    second returns None -- an unreadable/rotating `secrets.zsh`, a transient
    zsh failure, a timeout -- the health gate passes WITH the credential and
    the worker then launches WITHOUT it, which is precisely the silent,
    unattributable failure the gate exists to prevent.

    So the read happens exactly once, here, after direct-MCP authorization is
    known, and the resulting snapshot is the single object handed to both the
    health probe and the launcher. Never re-source the secret file to "refresh"
    inside one attempt.

    Returns `(snapshot, missing)`; `missing` names the credentials this role's
    authorized MCPs need and the secret store did not supply, so the launch can
    say so in the receipt and in the worker's context instead of letting the
    worker find out by calling a dead tool.
    """
    if worker_lane not in {"claude", "codex"}:
        return MappingProxyType({}), ()

    authorized = set(authorized_mcps)
    values = {}
    missing = []
    if "guarded-solodit" in authorized:
        solodit_key = load_solodit_api_key()
        if solodit_key is not None:
            values["SOLODIT_API_KEY"] = solodit_key
        else:
            missing.append("SOLODIT_API_KEY")
    if "chrono-research-arsenal" in authorized:
        research_keys = load_research_api_keys()
        values.update(research_keys)
        missing.extend(
            name
            for name in ("XAI_API_KEY", "PERPLEXITY_API_KEY")
            if name not in research_keys
        )
    if "github" in authorized:
        github_token = load_github_mcp_token()
        if github_token is not None:
            values["GITHUB_PERSONAL_ACCESS_TOKEN"] = github_token
        else:
            missing.append("GITHUB_PERSONAL_ACCESS_TOKEN")
    return MappingProxyType(values), tuple(sorted(missing))


def project_worker_credentials(environment, credential_snapshot):
    """Apply ONE already-loaded credential snapshot to a scrubbed environment.

    Pure and idempotent: it reads no secret of its own, so calling it for the
    health probe and again for the launcher cannot produce two different
    environments. Every managed name is popped first, so an ambient value can
    never survive into a role that did not authorize the MCP behind it.
    """
    projected = dict(environment)
    for name in MANAGED_CREDENTIAL_NAMES:
        projected.pop(name, None)
    projected.update(credential_snapshot)
    return projected


# Loaded exactly once per attempt (see `load_managed_credentials`). `None` here
# means "not yet read"; the codex gate below fills it after its own adapter
# parse, since that is where its authorized set first becomes known.
credential_snapshot = None
credential_missing = ()

trusted_environment = trusted_worker_environment(lane)
controller_vault_environment = dict(trusted_environment)
trusted_environment = project_worker_vault_environment(
    controller_vault_environment,
    aperture=memory_context_value["aperture"],
)
trusted_environment["CHRONO_VAULT_CONTEXT"] = json.dumps(
    memory_context_value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
)
controller_vault_environment["CHRONO_VAULT_CONTEXT"] = trusted_environment[
    "CHRONO_VAULT_CONTEXT"
]


def controller_vault_backend_environment():
    """Return the minimal controller-owned environment for the MCP backend."""

    projected = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONUNBUFFERED": "1",
        "CHRONO_VAULT_CLEARANCE": "internal",
        VAULT_CONTEXT_ENV: controller_vault_environment[VAULT_CONTEXT_ENV],
    }
    for name in (*VAULT_ROOT_ALIASES, "CHRONO_VAULT_AUDIT_DIR", "TMPDIR", "LANG", "LC_ALL"):
        value = controller_vault_environment.get(name)
        if isinstance(value, str) and value and "\x00" not in value:
            projected[name] = value
    return projected


def controller_vault_denied_subtrees():
    """Keep the documented lexical root plus every controller-supplied alias."""

    values = {HOST_HOME / "Obsidian-Chrono"}
    for name in VAULT_ROOT_ALIASES:
        value = controller_vault_environment.get(name)
        if isinstance(value, str) and value:
            values.add(Path(value))
    values.update(Path(os.path.realpath(value)) for value in tuple(values))
    return tuple(sorted(values, key=str))


def acknowledge_gemini_agents(project_root):
    agents_dir = project_root / ".gemini" / "agents"
    if not agents_dir.exists():
        return
    ack_path = (
        Path(trusted_environment["HOME"])
        / ".gemini"
        / "acknowledgments"
        / "agents.json"
    )
    try:
        data = json.loads(ack_path.read_text()) if ack_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    project = str(project_root)
    data.setdefault(project, {})
    for path in sorted(agents_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        data[project][path.stem] = hashlib.sha256(path.read_bytes()).hexdigest()
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ack_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ack_path)


if execution_kind == "lane" and lane == "gemini":
    acknowledge_gemini_agents(repo_root / "model-lanes" / "gemini")
capability_projection = {
    "schema": "role-capability-projection/v1",
    "lane": lane,
    "specialist": specialist,
    "mcps": [],
    "brokered_mcps": [],
    "tools": [],
    "skills": [],
    "sources": [],
}
capability_lane_args = []
configured_mcps = []
authorized_mcps = []
disabled_mcps = []
available_tools = []
missing_tools = []
# F6: declared tools that are unreachable on this headless spawn but do not
# gate it (GUI app bundles, operator-install-only tools, MCP-provided ops).
capability_gaps = []
# Authorized MCP servers that are configured but did not answer the launch
# health probe. Degraded, not denied -- see `plan_lane`.
unhealthy_mcps = []
unhealthy_mcp_status = {}
brokered_mcps = []
capability_enforcement = "not-applicable"
capability_plan = None
capability_plugin_args = []


def declared_array(path, key):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        deny(f"role capability source is unavailable: {exc}")
    matches = re.findall(
        rf"(?m)^[ \t]*{re.escape(key)}[ \t]*[:=][ \t]*(\[[^\r\n]*\])[ \t]*$",
        text,
    )
    values = []
    for match in matches:
        try:
            parsed = json.loads(match)
        except json.JSONDecodeError:
            deny(f"role capability source has an invalid {key} declaration")
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            deny(f"role capability source has an invalid {key} declaration")
        values.extend(parsed)
    return values


def canonical_capability_surface(worker_lane, projection, overlay_path):
    arrays = {key: list(projection[key]) for key in ("skills", "tools", "mcps")}
    if worker_lane == "gemini":
        arrays = {key: declared_array(overlay_path, f"capability_{key}") for key in arrays}
    raw_mcps = arrays.pop("mcps")
    brokered = set() if worker_lane == "gemini" else set(projection.get("brokered_mcps", ()))
    brokered.update(item[5:] for item in raw_mcps if item.startswith("lead:"))
    return {
        "schema": "capability-surface/v1", "lane": "gpt-codex" if worker_lane == "codex" else worker_lane,
        **{key: sorted(set(value), key=str.casefold) for key, value in arrays.items()},
        "mcps": sorted({item for item in raw_mcps if not item.startswith("lead:")}, key=str.casefold),
        "brokered_mcps": sorted(brokered, key=str.casefold),
    }

def trap_cli_missing(exc):
    if isinstance(exc, (FileNotFoundError, PermissionError)): deny(f"native lane CLI is unavailable: {exc}", "cli_missing")

if execution_kind == "lane" and lane in {"claude", "gemini", "kimi"}:
    try:
        native_adapter_path = adapter_path_for(
            repo_root=repo_root,
            lane=lane,
            specialist=specialist,
        )
        capability_projection = load_projection(
            lane=lane,
            specialist=specialist,
            adapter_path=native_adapter_path,
            overlay_path=Path(authority["lane_overlay_path"]),
        )
        # Read the worker's credentials ONCE, here, and measure the health probe
        # in an environment that carries them.
        #
        # The probe runs `<cli> mcp list` -- but it used to run against the bare
        # scrubbed env while credentials were not projected until much later
        # (just before the child launch). It therefore measured an environment
        # the worker would never run in, and any authorized MCP that
        # authenticates with a projected key was guaranteed to look broken. That
        # stayed invisible while the only projected keys belonged to the LOCAL
        # research-arsenal server, which connects fine unauthenticated; the
        # first remote bearer-token MCP to be authorized -- github -- turned it
        # into a hard denial of every role that lists it (measured 2026-08-09).
        #
        # `credential_snapshot` is the exact object the launcher projects below,
        # so the environment the gate measures and the one the worker gets can
        # no longer disagree.
        credential_snapshot, credential_missing = load_managed_credentials(
            lane,
            capability_projection.get("mcps", ()),
        )
        # Short-lived: the health probe is the ONLY child that needs a bearer
        # token. `claude plugin list --json` is a local inventory command with
        # no use for one, so it keeps the scrubbed environment -- a credential
        # is handed to the smallest number of processes that can be correct.
        health_probe_environment = project_worker_credentials(
            trusted_environment,
            credential_snapshot,
        )
        if lane in {"claude", "gemini"}:
            try:
                mcp_listing = subprocess.run(
                    (str(executable), "mcp", "list"),
                    check=False,
                    capture_output=True,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    cwd=str(repo_root / "model-lanes" / lane),
                    env=health_probe_environment,
                    timeout=30,
                    close_fds=True,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                trap_cli_missing(exc)
                raise CapabilityDenied(f"{lane} MCP configuration cannot be enumerated: {exc}") from exc
            if mcp_listing.returncode != 0:
                raise CapabilityDenied(
                    f"{lane} MCP configuration enumeration returned nonzero"
                )
            configured_servers = parse_live_mcp_listing(
                lane=lane,
                output=(
                    mcp_listing.stdout
                    if lane == "claude"
                    else mcp_listing.stdout + "\n" + mcp_listing.stderr
                ),
            )
            project_config_path = (
                repo_root / "model-lanes" / "claude" / ".mcp.json"
                if lane == "claude"
                else repo_root
                / "model-lanes"
                / "gemini"
                / ".gemini"
                / "settings.json"
            )
            project_servers = load_json_mcp_servers(project_config_path)
            missing_project_servers = sorted(
                set(project_servers) - set(configured_servers)
            )
            if missing_project_servers:
                raise CapabilityDenied(
                    f"{lane} live inventory omitted project MCP servers: "
                    + ", ".join(missing_project_servers)
                )
            for server_name, server_config in project_servers.items():
                configured_servers[server_name]["project_config"] = server_config
            native_tool_names = set(configured_servers)
            project_plugin_dirs = {}
            if lane == "claude":
                try:
                    plugin_listing = subprocess.run(
                        (str(executable), "plugin", "list", "--json"),
                        check=False,
                        capture_output=True,
                        text=True,
                        stdin=subprocess.DEVNULL,
                        cwd=str(repo_root / "model-lanes" / lane),
                        env=trusted_environment,
                        timeout=30,
                        close_fds=True,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    trap_cli_missing(exc)
                    raise CapabilityDenied(f"Claude plugin inventory cannot be enumerated: {exc}") from exc
                if plugin_listing.returncode != 0:
                    raise CapabilityDenied(
                        "Claude plugin inventory enumeration returned nonzero"
                    )
                native_tool_names.update(
                    parse_claude_enabled_plugins(plugin_listing.stdout)
                )
                project_plugin_dirs = parse_claude_project_plugin_dirs(
                    plugin_listing.stdout
                )
        else:
            configured_servers = {}
        capability_plan = plan_lane(
            lane=lane,
            projection=capability_projection,
            configured_servers=configured_servers,
            repo_root=repo_root,
            broker_chrono_vault=(launch_mode == "strict"),
            kimi_vault_environment=(
                {
                    name: trusted_environment[name]
                    for name in ("CHRONO_VAULT_ROOT", "CHRONO_VAULT_CONTEXT")
                    if name in trusted_environment
                }
                if lane == "kimi"
                else None
            ),
            # F6: a GUI app bundle / operator-install tool is not a PATH lookup,
            # so a `which()` miss must record a capability gap, not deny a
            # headless spawn. Unclassified tools stay fail-closed.
            tool_classes=load_tool_classes(
                repo_root=repo_root,
                lane=lane,
                specialist=specialist,
            ),
            tool_lookup=(
                (
                    lambda name: (
                        name
                        if name in native_tool_names
                        else shutil.which(
                            name,
                            path=trusted_environment["PATH"],
                        )
                    )
                )
                if lane in {"claude", "gemini"}
                else lambda name: shutil.which(
                    name,
                    path=trusted_environment["PATH"],
                )
            ),
        )
        if lane == "claude":
            selected_plugin_dirs = set()
            for server_name in capability_plan.authorized_mcps:
                if launch_mode == "strict" and server_name == "chrono-vault":
                    # The explicit path-free relay record below is the only
                    # strict-mode provider for this server name. Loading the
                    # direct plugin as well would make native merge precedence
                    # part of the security boundary.
                    continue
                live_name = configured_servers[server_name].get("live_name")
                if not isinstance(live_name, str) or not live_name.startswith(
                    "plugin:"
                ):
                    continue
                plugin_name = live_name.split(":", 2)[1]
                install_path = project_plugin_dirs.get(plugin_name)
                if install_path is None:
                    continue
                repo_plugin = repo_root / "plugins" / plugin_name
                resolved_plugin = (
                    repo_plugin.resolve(strict=True)
                    if repo_plugin.is_dir()
                    else Path(install_path).resolve(strict=True)
                )
                if not resolved_plugin.is_dir():
                    raise CapabilityDenied(
                        "Claude project plugin path is not a directory"
                    )
                selected_plugin_dirs.add(str(resolved_plugin))
            for plugin_dir in sorted(selected_plugin_dirs):
                capability_plugin_args.extend(("--plugin-dir", plugin_dir))
    except CapabilityDenied as exc:
        deny(f"role capability enforcement denied launch: {exc}")
    capability_lane_args = capability_plugin_args + list(capability_plan.cli_args)
    configured_mcps = list(capability_plan.configured_mcps)
    authorized_mcps = list(capability_plan.authorized_mcps)
    disabled_mcps = list(capability_plan.disabled_mcps)
    available_tools = list(capability_plan.available_tools)
    missing_tools = list(capability_plan.missing_tools)
    capability_gaps = list(capability_plan.capability_gaps)
    unhealthy_mcps = list(capability_plan.unhealthy_mcps)
    unhealthy_mcp_status = dict(capability_plan.unhealthy_mcp_status)
    brokered_mcps = list(capability_plan.brokered_mcps)
    capability_enforcement = capability_plan.capability_enforcement


if execution_kind == "lane" and lane == "codex":
    if lane != "codex":
        deny(
            f"per-role MCP/tool scoping is not implemented for lane {lane!r}; "
            "prompt-only differentiation is forbidden"
        )
    adapter_directory = (
        repo_root / "model-lanes" / "gpt-codex" / ".codex" / "agents"
    )
    adapter_path = adapter_directory / f"{specialist.replace('-', '_')}.toml"
    if not adapter_path.is_file():
        adapter_path = adapter_directory / f"{specialist}.toml"
    if not adapter_path.is_file():
        deny("native Codex specialist adapter is missing")
    capability_sources = (adapter_path, Path(authority["lane_overlay_path"]))
    for source in capability_sources:
        capability_projection["sources"].append({
            "path": str(source),
            "sha256": sha256_file(source),
        })
        for key in ("mcps", "tools", "skills"):
            capability_projection[key].extend(declared_array(source, key))
    for key in ("mcps", "tools", "skills"):
        values = capability_projection[key]
        if any(
            not value
            or value != value.strip()
            or any(marker in value for marker in ("\x00", "\n", "\r"))
            for value in values
        ):
            deny(f"native adapter has an invalid {key} capability")
        capability_projection[key] = sorted(set(values))

    try:
        mcp_listing = subprocess.run(
            (str(executable), "mcp", "list", "--json"),
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            cwd=str(repo_path),
            env=trusted_environment,
            timeout=30,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        trap_cli_missing(exc)
        deny(f"Codex MCP configuration cannot be enumerated: {exc}")
    if mcp_listing.returncode != 0:
        deny("Codex MCP configuration enumeration returned nonzero")
    try:
        listing_payload = json.loads(mcp_listing.stdout)
    except json.JSONDecodeError:
        deny("Codex MCP configuration enumeration returned invalid JSON")
    if (
        not isinstance(listing_payload, list)
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            for item in listing_payload
        )
    ):
        deny("Codex MCP configuration enumeration has the wrong schema")
    configured_mcps = sorted({item["name"] for item in listing_payload})
    authorized_mcps = capability_projection["mcps"]
    missing_mcps = sorted(set(authorized_mcps) - set(configured_mcps))
    if missing_mcps:
        deny(
            "native adapter requires unconfigured MCP servers: "
            + ", ".join(missing_mcps)
        )
    disabled_mcps = sorted(set(configured_mcps) - set(authorized_mcps))
    for server_name in configured_mcps:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", server_name):
            deny("configured MCP server has a name unsafe for a CLI override")
        if server_name in authorized_mcps:
            capability_lane_args.extend(
                ("-c", f"mcp_servers.{server_name}.enabled=true")
            )
        else:
            # Replace, rather than merge with, the configured table.  Codex
            # validates remote transports even when disabled, which would
            # otherwise force unrelated role credentials (for example a
            # GitHub bearer token) into this child merely to turn them off.
            capability_lane_args.extend(
                (
                    "-c",
                    (
                        f'mcp_servers.{server_name}='
                        '{enabled=false,command="/usr/bin/false"}'
                    ),
                )
            )
    # F6: the Codex path carries its own copy of the required-tool gate. Apply
    # the same rule as `plan_lane`: only a tool whose declared evidence claims
    # it is on the shell PATH may be denied for a `which()` miss; anything else
    # (a `.app` bundle, an operator-install tool, an MCP operation) is recorded
    # as a capability gap. Unclassified tools stay fail-closed.
    codex_tool_classes = load_tool_classes(
        repo_root=repo_root,
        lane="codex",
        specialist=specialist,
    )
    for tool_name in capability_projection["tools"]:
        if not re.fullmatch(r"[A-Za-z0-9._+-]+", tool_name):
            deny("native adapter declares an unsafe local tool name")
        if shutil.which(tool_name, path=trusted_environment["PATH"]):
            available_tools.append(tool_name)
        elif _tool_gates_launch(codex_tool_classes.get(tool_name)):
            missing_tools.append(tool_name)
        else:
            capability_gaps.append(tool_name)
    if missing_tools:
        deny(
            "native adapter requires unavailable local tools: "
            + ", ".join(missing_tools)
        )
    capability_enforcement = "codex-cli-mcp-table-replacement-overrides/v1"

if execution_kind == "lane":
    if credential_snapshot is None:
        # Codex reaches here without a snapshot: its authorized set is only
        # known after its own adapter parse above. Every other lane already
        # loaded one before the health probe and MUST reuse it -- re-reading
        # the secret store here is the TOCTOU this refactor removed.
        credential_snapshot, credential_missing = load_managed_credentials(
            lane,
            authorized_mcps,
        )
    trusted_environment = project_worker_credentials(
        trusted_environment,
        credential_snapshot,
    )
    if trusted_context and (unhealthy_mcps or credential_missing):
        # Tell the worker BEFORE it spends a call on a dead tool. The receipt is
        # the audit record; this is the operational one.
        notice = ["\n\n## Degraded capability notice (measured at launch)\n\n"]
        if unhealthy_mcps:
            notice.append(
                "These MCP servers are authorized for your role but did NOT "
                "answer the launch health probe. This did not block your "
                "launch and it is not your task to repair them. Expect a "
                "failure at call time; declare a `capability_gap` and use the "
                "task-approved fallback rather than debugging them:\n\n"
            )
            notice.extend(
                f"- `{name}` -- {unhealthy_mcp_status.get(name, 'unhealthy')}\n"
                for name in unhealthy_mcps
            )
            notice.append("\n")
        if credential_missing:
            notice.append(
                "The secret store did not supply these credentials, so any "
                "tool that authenticates with one will fail at call time:\n\n"
            )
            notice.extend(f"- `{name}`\n" for name in credential_missing)
        degraded_notice = "".join(notice)
        # The 32 KiB bound above guards OPERATOR-supplied prompt text. This
        # suffix is controller-authored and separately bounded, so a pathological
        # status string cannot push the prompt past a lane's input limit.
        if len(degraded_notice.encode("utf-8")) > 4096:
            degraded_notice = (
                degraded_notice.encode("utf-8")[:4096].decode("utf-8", "ignore")
                + "\n(truncated; see the launch receipt for the full list)\n"
            )
        trusted_task_prompt = trusted_task_prompt.rstrip() + degraded_notice

capability_projection_bytes = json.dumps(
    capability_projection,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
).encode("ascii")
capability_projection_sha256 = hashlib.sha256(
    capability_projection_bytes
).hexdigest()
observed_capability_surface_sha256 = ""
if execution_kind == "lane":
    capability_surface = canonical_capability_surface(lane, capability_projection, authority["lane_overlay_path"])
    observed_capability_surface_sha256 = hashlib.sha256(json.dumps(
        capability_surface, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("ascii")).hexdigest()
    if not hmac.compare_digest(observed_capability_surface_sha256, authority["capability_surface_sha256"]):
        deny("capability surface does not match launch authority")


def canonical_logical_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        deny("scheduler authority contains an invalid logical path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repo_path / candidate
    normalized = Path(os.path.normpath(candidate))
    try:
        if os.path.commonpath((str(normalized), str(repo_path))) != str(repo_path):
            deny("scheduler authority path escapes the repository")
    except ValueError:
        deny("scheduler authority path is not comparable to the repository")
    return str(normalized)

write_paths = authority["write_paths"]
read_paths = authority["read_scope"]
if (
    not isinstance(write_paths, list)
    or not write_paths
    or not isinstance(read_paths, list)
    or any(not isinstance(item, str) for item in (*write_paths, *read_paths))
):
    deny("scheduler authority has invalid logical read/write scopes")
launch_timeout = 180.0
# Deletion authority is a CONTROLLER capability with a deny-by-default value.
# It is never read from the worktree (the worker can edit its copy of the
# packet) and never inferred from write_scope; it is populated below only from
# the main-repo canonical packet, and only after that packet's bytes and its
# verification contract both match the authenticated authority.
authorized_delete_paths = ()
if board_dispatch_context:
    authorized_delete_paths = tuple(
        pinned_contract.get("authorized_delete_paths") or ()
    )
    if authorized_delete_paths:
        # Launch-side operator gate: a delete-carrying packet must not start at
        # all unless it carries the operator's approval. Hard Rule 6 is answered
        # at dispatch time, where the operator actually is -- not at integration
        # time, after a worker has already spent its budget.
        #
        # A second branch here also required "delete" to be a controller-held
        # category. It was removed on 2026-08-08 as provably unreachable: the
        # authority check above refuses dispatch unless operator_gates equals
        # HELD_CATEGORIES exactly, and "delete" is always a member, so the
        # membership test was a constant. It read as a deletion control while
        # enforcing nothing -- operator_approved is, and always was, the gate.
        if packet_frontmatter.get("operator_approved") is not True:
            deny(
                "packet authorizes deletions without operator_approved: true in the "
                "canonical packet"
            )
    budgets = authority["budgets"]
    if (
        not isinstance(budgets, dict)
        or set(budgets) != {"timeout_seconds"}
        or isinstance(budgets["timeout_seconds"], bool)
        or not isinstance(budgets["timeout_seconds"], int)
        or not (
            30 <= budgets["timeout_seconds"] <= 2700
            or (
                authority["mode_profile"] == "bounty"
                and 2700 < budgets["timeout_seconds"] <= 3600
            )
        )
    ):
        deny("authenticated launch budget is invalid")
    launch_timeout = float(budgets["timeout_seconds"])


def scheduler_dependencies(values):
    if not isinstance(values, list):
        deny("scheduler authority dependencies are not a list")
    result = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {
            "task_id", "generation", "artifact_sha256"
        }:
            deny("scheduler authority has an invalid dependency")
        result.append(board_router.DepEdge(**item))
    return tuple(result)


def scheduler_resources(values):
    if not isinstance(values, list):
        deny("scheduler authority resources are not a list")
    result = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {
            "resource_class", "target", "mode", "units"
        }:
            deny("scheduler authority has an invalid resource claim")
        result.append(board_router.ResourceClaim(**item))
    return tuple(result)


current_task = board_router.BoardTask(
    task_id=task_id,
    write_paths=tuple(canonical_logical_path(item) for item in write_paths),
    read_paths=tuple(canonical_logical_path(item) for item in read_paths),
    depends_on=scheduler_dependencies(authority["depends_on"]),
    resources=scheduler_resources(authority["resources"]),
    worktree_root=str(repo_path),
    metadata_complete=True,
    priority=0,
)
active_tasks = []
active_fields = {
    "task_id", "write_paths", "read_paths", "worktree_root",
    "depends_on", "resources", "metadata_complete", "priority",
}
if not isinstance(authority["active_board_tasks"], list):
    deny("scheduler authority active task snapshot is not a list")
for entry in authority["active_board_tasks"]:
    if (
        not isinstance(entry, dict)
        or set(entry) != active_fields
        or entry.get("metadata_complete") is not True
        or not isinstance(entry.get("write_paths"), list)
        or not isinstance(entry.get("read_paths"), list)
    ):
        deny("scheduler authority contains incomplete active task metadata")
    active_tasks.append(
        board_router.BoardTask(
            task_id=str(entry["task_id"]),
            write_paths=tuple(
                canonical_logical_path(item) for item in entry["write_paths"]
            ),
            read_paths=tuple(
                canonical_logical_path(item) for item in entry["read_paths"]
            ),
            depends_on=scheduler_dependencies(entry["depends_on"]),
            resources=scheduler_resources(entry["resources"]),
            worktree_root=str(entry["worktree_root"]),
            metadata_complete=True,
            priority=int(entry["priority"]),
        )
    )
try:
    concurrency = authority["scheduler_concurrency"]
    capacities = authority["scheduler_capacities"]
    settled_json = authority["scheduler_settled"]
    if (
        isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or concurrency <= 0
        or not isinstance(capacities, dict)
        or not isinstance(settled_json, dict)
    ):
        raise ValueError("authenticated scheduler settings are invalid")
    settled = {}
    for settled_task, settled_value in settled_json.items():
        if (
            not isinstance(settled_task, str)
            or not isinstance(settled_value, list)
            or len(settled_value) != 2
        ):
            raise ValueError("authenticated settled snapshot is invalid")
        settled[settled_task] = (settled_value[0], settled_value[1])
    active_reservations = tuple(
        board_router._reservation_for(item) for item in active_tasks
    )
    active_snapshot = board_router._reservation_snapshot_sha256(
        active_reservations
    )
    schedule_result = board_router.schedule(
        (current_task,),
        concurrency=concurrency,
        settled=settled,
        capacities=capacities,
        active_reservations=active_reservations,
        active_snapshot_sha256=active_snapshot,
        logical_only=True,
    )
except Exception as exc:  # noqa: BLE001 - authenticated scheduler fails closed
    deny(f"scheduler authority validation failed: {exc}")
if task_id not in schedule_result.run_now:
    reason = schedule_result.reasons.get(task_id, "scheduler did not reserve task")
    deny(f"scheduler authority denied launch: {reason}")
scheduler_snapshot_sha256 = schedule_result.reservation_snapshot_sha256

try:
    pool = wti.WorktreePool(repo_path, pool_root, base_branch=os.environ.get("SQUAD_BASE_BRANCH", "v2"))
    handle = pool.provision(task_id, attempt_id)
except wti.WorktreeIsolationError as exc:
    deny(f"worktree provisioning failed: {exc}")


def _classify_block_reason(reason):
    """Typed failure class so downstream shows the real cause, not a bare 'exit 75'.

    Classify ordinary reasons by their leading clause. Several reasons append
    offending file lists whose names match these keywords, so the evidence must
    not outvote the diagnosis. A timeout exception is the deliberate exception
    only when a generic launch clause wraps it: inspect that clause's tail for
    an actual timeout phrase before falling back to the generic launch class.

    A timeout word that is part of a *filename* is never a timeout signal --
    `analysis timed out.md` names a report. That guard has to cover the leading
    clause too, not just a wrapped tail: a reason carrying no diagnostic clause
    at all reaches neither the launch branch nor the tail inspection, so without
    it a bare report name was diagnosed `timeout`.
    """
    full_reason = str(reason).lower()
    r, separator, tail = full_reason.partition(": ")

    def matched_a_filename(value, start, end):
        # The whole word the match landed in has to be a filename, not just the
        # characters straight after it: `timeouts.md` and `timeout-notes.md` are
        # report names exactly as much as `timed out.md` is.
        while end < len(value) and not value[end].isspace() and value[end] not in ",;":
            end += 1
        stem, dot, extension = value[start:end].rstrip(",;:)]}").rpartition(".")
        return bool(dot) and bool(stem) and extension.isalnum()

    def matches_outside_a_filename(value, tokens):
        for token in tokens:
            search_from = 0
            while (match_at := value.find(token, search_from)) != -1:
                if not matched_a_filename(value, match_at, match_at + len(token)):
                    return True
                search_from = match_at + len(token)
        return False

    def has_timeout_signal(value):
        # The tail is evidence, not diagnosis, so a bare `timeout` word is not
        # enough here: it is often the subject ("timeout policy file could not
        # be loaded"). Only an actual timeout *event* phrase promotes.
        normalized = value.strip()
        if normalized in {"timeout", "deadline"}:
            return True

        timeout_phrases = (
            "timed out",
            "timeoutexpired",
            "timeout expired",
            "timeout exceeded",
            "timeout after",
            "timeout while",
            "timeout waiting",
            "timeout reached",
            "operation timeout",
            "deadline exceeded",
            "deadline expired",
            "deadline reached",
        )
        return matches_outside_a_filename(normalized, timeout_phrases)

    if "canary" in r:
        return "launch_canary"
    generic_launch = "trusted launch failed" in r or ("launch" in r and "fail" in r)
    if generic_launch and separator and has_timeout_signal(tail):
        return "timeout"
    if generic_launch:
        return "launch"
    if "worktree" in r:
        return "worktree"
    if matches_outside_a_filename(r, ("timeout", "timed out", "deadline")):
        return "timeout"
    if "vault" in r or "chrono_vault_root" in r or "memory" in r:
        return "memory_proof"
    if "envelope" in r or "missing" in r:
        return "missing_envelope"
    if "integration" in r or "drift" in r:
        return "integration"
    if "verification" in r or "verifier" in r:
        return "verification"
    if "capability" in r or "denied" in r or "authoriz" in r:
        return "capability"
    if "validation" in r:
        return "request_validation"
    return "other"


def block_after_provision(reason, *, failure_class=None, returncode=None, cli_stdout="", cli_stderr=""):
    if failure_class is not None and failure_class not in CLI_TRANSPORT_FAILURE_CLASSES:
        raise ValueError("invalid CLI transport failure class")
    print(json.dumps({
        "status": "blocked",
        "reason": str(reason),
        "failure_class": failure_class or _classify_block_reason(reason),
        "task_id": task_id,
        "attempt_id": attempt_id,
        "worktree_root": str(handle.worktree_root),
        "worktree_state": "retained-blocked",
        "reservation_state": "blocked-awaiting-reconciliation",
        "returncode": returncode,
        "cli_exec_succeeded": False,
        "execution_mode": "real",
        "execution_kind": execution_kind,
        "authority_mode": (
            "strict-fd3-seatbelt" if launch_mode == "strict"
            else "trusted-host-unpinned"
        ),
        "authority_sha256": authority_sha256,
        "scheduler_reservation_snapshot_sha256": scheduler_snapshot_sha256,
        "role_context_sha256": getattr(globals().get("role"), "sha256", ""),
        "capability_projection_sha256": capability_projection_sha256,
        "capability_enforcement": capability_enforcement,
        "authorized_mcps": authorized_mcps,
        "brokered_mcps": brokered_mcps,
        "vault_broker_required": bool(globals().get("vault_broker_required", False)),
        "vault_broker_started": bool(globals().get("vault_broker_started", False)),
        "capability_config_path": (
            str(globals().get("capability_config_path"))
            if globals().get("capability_config_path") is not None
            else None
        ),
        "cli_stdout_sha256": hashlib.sha256(
            str(cli_stdout).encode("utf-8")
        ).hexdigest(),
        "cli_stderr_sha256": hashlib.sha256(
            str(cli_stderr).encode("utf-8")
        ).hexdigest(),
    }, sort_keys=True))
    sys.exit(75)


capability_config_path = None


lineage = delegation_lineage.root_lineage(originating_parent=task_id, requester_specialist=specialist)

request_payload = {
    "task_id": task_id,
    "attempt_id": attempt_id,
    "generation": generation,
    "branch": os.environ.get("SQUAD_BASE_BRANCH", "v2"),
    "task_root": str(handle.worktree_root),
    "write_paths": [str(handle.worktree_root)],
    "profile_bundle_sha256": str(context["profile_bundle_sha256"]),
}
request_file = handle.worktree_root / ".trusted-launch-request.json"
request_file.write_text(json.dumps(request_payload, sort_keys=True), encoding="utf-8")

try:
    request = _load_task_request(request_file)
except HygieneError as exc:
    block_after_provision(f"task request validation failed: {exc}")

audited_scopes = audit_writable_scopes((handle.worktree_root,))
prepared = None
vault_broker = None
vault_broker_started = False
vault_broker_closed = False
vault_broker_required = (
    launch_mode == "strict"
    and execution_kind == "lane"
    and "chrono-vault" in authorized_mcps
)
try:
    request_sha256 = _request_digest(request)
    with scoped_lane_launch_profile(
        lane=(lane if execution_kind == "lane" else None),
        offline_probe=(execution_kind == "offline-probe"),
        broker_relay=vault_broker_required,
        denied_subtrees=(
            controller_vault_denied_subtrees()
            if launch_mode == "strict" and execution_kind == "lane"
            else ()
        ),
    ):
        prepared = run_preflight_canary(
            handle.worktree_root,
            request_sha256=request_sha256,
            audited_scopes=audited_scopes,
            retain_launch=True,
        )
    if not prepared.canary.passed:
        block_after_provision(f"Stage-1 canary failed: {prepared.canary.to_json()}")

    if vault_broker_required:
        broker_token = os.urandom(32).hex()
        try:
            relay = chrono_vault_relay_server(
                repo_root=handle.worktree_root,
                broker_port=prepared.broker_listener.getsockname()[1],
                broker_token=broker_token,
                task_id=task_id,
                attempt_id=attempt_id,
                generation=int(generation),
                python_executable=BROKER_RELAY_PYTHON,
            )
            if lane == "codex":
                capability_lane_args.extend(
                    codex_chrono_vault_relay_args(
                        relay=relay,
                        broker_token=broker_token,
                    )
                )
            else:
                if capability_plan is None:
                    raise CapabilityDenied(
                        "chrono-vault broker has no lane capability plan"
                    )
                capability_plan = broker_chrono_vault_plan(
                    capability_plan,
                    repo_root=handle.worktree_root,
                    broker_port=prepared.broker_listener.getsockname()[1],
                    broker_token=broker_token,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    generation=int(generation),
                    python_executable=BROKER_RELAY_PYTHON,
                )
                capability_lane_args = capability_plugin_args + list(
                    capability_plan.cli_args
                )
        except (CapabilityDenied, OSError, ValueError) as exc:
            block_after_provision(
                f"chrono-vault broker plan rewrite failed closed: {exc}"
            )

    if capability_plan is not None and capability_plan.role_config_json is not None:
        try:
            capability_config_path = materialize_role_config(
                capability_plan,
                worktree_root=handle.worktree_root,
                task_id=task_id,
                attempt_id=attempt_id,
            )
            capability_lane_args = capability_plugin_args + list(
                cli_args_for_materialized(
                    capability_plan,
                    capability_config_path,
                )
            )
        except (CapabilityDenied, OSError) as exc:
            block_after_provision(
                f"role capability config materialization failed: {exc}"
            )

    if vault_broker_required:
        worker_plan_text = "\n".join(capability_lane_args)
        if capability_plan is not None and capability_plan.role_config_json is not None:
            worker_plan_text += "\n" + capability_plan.role_config_json
        exposed_paths = sorted(
            {
                str(path)
                for path in controller_vault_denied_subtrees()
                if str(path) in worker_plan_text
            }
        )
        if exposed_paths:
            block_after_provision(
                "chrono-vault broker plan exposed a private filesystem path"
            )

    if vault_broker_required:
        backend_environment = controller_vault_backend_environment()
        backend_command = (
            ("/usr/bin/false",)
            if memory_context_value["aperture"] == "none"
            else (
                str(repo_path / ".venv" / "bin" / "python"),
                str(repo_path / "plugins" / "chrono-vault" / "mcp_server.py"),
            )
        )
        try:
            vault_broker = VaultBroker(
                listener=prepared.broker_listener,
                token=broker_token,
                binding=BrokerBinding(
                    task_id=task_id,
                    attempt_id=attempt_id,
                    generation=int(generation),
                ),
                backend_command=backend_command,
                backend_environment=backend_environment,
                backend_cwd=repo_path / "plugins" / "chrono-vault",
            )
            vault_broker.start()
            vault_broker_started = True
        except (BrokerError, OSError, RuntimeError, ValueError) as exc:
            diagnostics = (
                vault_broker.diagnostics() if vault_broker is not None else ""
            )
            block_after_provision(
                "chrono-vault broker startup failed closed: "
                + str(exc)
                + (f"; {diagnostics}" if diagnostics else "")
            )

    if execution_kind == "lane" and lane == "gemini":
        acknowledge_gemini_agents(
            handle.worktree_root / "model-lanes" / "gemini"
        )
        capability_lane_args.extend(
            ("--include-directories", str(handle.worktree_root))
        )
    if execution_kind == "lane" and lane == "kimi":
        capability_lane_args.extend(
            (
                "--agent-file",
                str(handle.worktree_root / "model-lanes" / "kimi" / "main.yaml"),
                "--add-dir",
                str(handle.worktree_root),
            )
        )
    if execution_kind == "lane" and lane == "codex":
        try:
            for git_write_dir in wti.linked_worktree_commit_write_dirs(handle):
                capability_lane_args.extend(("--add-dir", str(git_write_dir)))
        except wti.WorktreeIsolationError as exc:
            block_after_provision(
                f"linked worktree commit scope derivation failed: {exc}"
            )

    launch_overlay_path = Path(str(context["lane_overlay_path"]))
    if launch_mode == "trusted" and execution_kind == "lane":
        launch_overlay_path = handle.worktree_root / ".trusted-task-overlay.md"
        authenticated_overlay = Path(
            str(context["lane_overlay_path"])
        ).read_text(encoding="utf-8")
        launch_overlay_path.write_text(
            authenticated_overlay.rstrip()
            + "\n\n## Trusted task instruction\n\n"
            + trusted_task_prompt.strip()
            + "\n",
            encoding="utf-8",
        )
    role = compile_role_context(
        Path(str(context["canonical_role_path"])),
        launch_overlay_path,
        specialist=specialist,
        lane=lane,
        mode_profile=str(authority["mode_profile"]),
    )
    agent_system_context = role.prompt
    if trusted_context and execution_kind == "lane":
        agent_system_context = (
            "## Canonical specialist role\n\n"
            + role.canonical_role.rstrip()
            + "\n\n## Lane overlay\n\n"
            + authenticated_overlay.rstrip()
            + "\n"
        )
    now = int(time.time())
    def worker_scope_path(value):
        raw = Path(value)
        if raw.is_absolute():
            relative = raw.relative_to(repo_path)
        else:
            relative = raw
        candidate = Path(os.path.normpath(handle.worktree_root / relative))
        if os.path.commonpath((str(candidate), str(handle.worktree_root))) != str(handle.worktree_root):
            raise ValueError("authenticated worker scope escapes its worktree")
        return str(candidate)

    worker_write_scope = tuple(worker_scope_path(item) for item in authority["write_paths"])
    worker_read_scope = tuple(worker_scope_path(item) for item in authority["read_scope"])
    expected_result_path = worker_scope_path(authority["expected_result_path"])
    expected_outbox_path = worker_scope_path(authority["expected_outbox_path"])
    claims = RuntimeEnvelopeClaims(
        task_id=task_id,
        attempt_id=attempt_id,
        generation=int(generation),
        run_id=str(authority["run_id"]),
        lane=lane,
        author_family=str(authority["author_family"]),
        workload_class=str(context["workload_class"]),
        packet_sha256=str(authority["packet_sha256"]),
        role_context_sha256=role.sha256,
        overlay_sha256=role.lane_overlay_sha256,
        plan_sha256=str(authority["plan_sha256"]),
        authority_sha256=authority_sha256,
        verification_contract_sha256=str(authority["verification_contract_sha256"]),
        selected_model_sha256=str(authority["selected_model_sha256"]),
        read_scope=worker_read_scope,
        write_scope=worker_write_scope,
        network_scope=tuple(authority["network_scope"]),
        action_scope=tuple(authority["action_scope"]),
        budgets=dict(authority["budgets"]),
        expected_result_path=expected_result_path,
        expected_outbox_path=expected_outbox_path,
        required_phase_ids=tuple(authority["required_phase_ids"]),
        verification_kinds=tuple(authority["verification_kinds"]),
        operator_gates=tuple(authority["operator_gates"]),
        stage1_profile_sha256=prepared.canary.profile_sha256,
        stage1_request_sha256=prepared.canary.request_sha256,
        stage1_scope_sha256=prepared.canary.scope_sha256,
        reconciliation_nonce=str(authority["nonce"]),
        created_at=now,
        expires_at=min(int(authority["expires_at"]), now + 120),
    )
    signing_key = authority_signing_key
    envelope = seal_runtime_envelope(claims, signing_key)

    if sha256_file(Path(os.path.realpath(executable)), "cli_missing") != authority["executable_sha256"]:
        raise ValueError("lane executable changed after profile compilation")

    # Strict mode uses the retained PreparedLaunch for the final child.  The
    # trusted default still consumes its settled containment canary, then runs
    # the subscription CLI on the trusted host with its existing home/config
    # authentication and an explicit, non-secret environment allowlist.
    prepared.environment["PATH"] = DEFAULT_LANE_PATH
    # The strict worker gets neither the private root nor the controller's
    # aperture context.  Its chrono-vault child receives only the one-attempt
    # relay token from the rewritten native config; the broker-owned backend
    # holds context and root outside this Seatbelt domain.
    # Seed the legacy value, then scrub it in the same closed allowlist below;
    # this keeps the transition observable to the existing launch-contract
    # check while proving the final prepared environment cannot retain it.
    prepared.environment["CHRONO_VAULT_CONTEXT"] = trusted_environment[
        "CHRONO_VAULT_CONTEXT"
    ]
    for provider_key in (
        *VAULT_ROOT_ALIASES,
        VAULT_CONTEXT_ENV,
        VAULT_BROKER_TOKEN_ENV,
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        prepared.environment.pop(provider_key, None)
    def bounded_real_launcher(canary_runner, command, **kwargs):
        kwargs["limits"] = ResourceLimits(process_count=4096)
        if execution_kind == "lane" and lane == "gemini":
            kwargs["cwd"] = str(
                handle.worktree_root / GEMINI_LANE_CWD_RELATIVE
            )
        return launch_if_canary_passes(canary_runner, command, **kwargs)

    def trusted_real_launcher(canary_runner, command, **kwargs):
        retained = canary_runner()
        if retained is not prepared or not prepared.canary.passed:
            raise ValueError("trusted launch did not consume its retained passing canary")
        timeout = float(kwargs.get("timeout", 180))
        cwd = str(
            handle.worktree_root / GEMINI_LANE_CWD_RELATIVE
            if execution_kind == "lane" and lane == "gemini"
            else handle.worktree_root
        )
        # Stream the child's stdout to the board transcript fd as each line arrives so
        # the dashboard can tail the .log in real time (subprocess.run buffered until
        # exit -> 0 bytes visible mid-run). Drain both pipes on threads to avoid a
        # deadlock when either fills, and still return a CompletedProcess so every
        # downstream consumer (receipt hashes, memory-event parsing) is unchanged.
        mirror_fd = None
        raw_fd = os.environ.get("BOARD_TRANSCRIPT_FD_VALUE", "")
        if raw_fd:
            try:
                mirror_fd = int(raw_fd)
            except ValueError:
                mirror_fd = None
        proc = subprocess.Popen(
            tuple(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=trusted_environment,
            close_fds=True,
            start_new_session=True,
        )
        manager = ProcessGroupReaper()
        manager.register(proc.pid)
        out_chunks = []
        err_chunks = []

        def _drain(pipe, chunks, mirror):
            try:
                for line in iter(pipe.readline, ""):
                    chunks.append(line)
                    if mirror is not None:
                        try:
                            os.write(mirror, line.encode("utf-8", "replace"))
                        except OSError:
                            pass
            finally:
                pipe.close()

        threads = [
            threading.Thread(
                target=_drain, args=(proc.stdout, out_chunks, mirror_fd), daemon=True
            ),
            threading.Thread(
                target=_drain, args=(proc.stderr, err_chunks, None), daemon=True
            ),
        ]
        for thread in threads:
            thread.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            manager.terminate(proc.pid)
            proc.wait()
            for thread in threads:
                thread.join(timeout=2)
            if any(thread.is_alive() for thread in threads):
                raise ProcessTruthError("child pipes remained open after verified process cleanup")
            raise
        finally:
            manager.unregister(proc.pid)
        for thread in threads:
            thread.join()
        if mirror_fd is not None:
            _board_stdout_streamed[0] = True
        return subprocess.CompletedProcess(
            tuple(command), proc.returncode, "".join(out_chunks), "".join(err_chunks)
        )

    selected_launcher = (
        bounded_real_launcher if launch_mode == "strict" else trusted_real_launcher
    )

    def run_with_restored_prompt(prompt_path, suffix, callback):
        original = prompt_path.read_bytes()
        try:
            prompt_path.write_bytes(original.rstrip() + suffix.encode("utf-8"))
            return callback()
        finally:
            prompt_path.write_bytes(original)

    def gemini_ordered_launcher(canary_runner, command, **kwargs):
        if len(command) < 4 or command[0] != str(executable) or command[1] != "-p":
            raise ValueError("Gemini launch command has an unexpected shape")
        expected_tail = tuple(capability_lane_args) + tuple(authority["lane_args"])
        if tuple(command[3:]) != expected_tail:
            raise ValueError("Gemini launch arguments changed after authentication")
        directory_args = tuple(capability_lane_args[-2:])
        expected_directory_args = (
            "--include-directories",
            str(handle.worktree_root),
        )
        if directory_args != expected_directory_args:
            raise ValueError("Gemini workspace arguments changed after provisioning")
        role_capability_args = []
        for server_name in capability_plan.authorized_mcps:
            role_capability_args.extend(
                ("--allowed-mcp-server-names", server_name)
            )
        for tool_name in capability_plan.authorized_tools:
            role_capability_args.extend(("--allowed-tools", tool_name))
        projection_json = json.dumps(
            envelope.worker_projection(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        # This lane's cwd is its model-lanes directory, but every path in the
        # packet is worktree-root relative. State the offset and hand over the
        # resolved absolute paths so the worker never has to infer a "../../"
        # prefix; reclaim_lane_cwd_outputs() repairs it after the fact when the
        # worker uses the packet-relative form anyway.
        lane_cwd_path = handle.worktree_root / GEMINI_LANE_CWD_RELATIVE
        path_contract = (
            "\n\n## Working directory contract (read before writing anything)\n\n"
            f"- Your process working directory is `{lane_cwd_path}`.\n"
            f"- The worktree root is `{handle.worktree_root}`.\n"
            "- Every relative path in the task packet (`return_artifact`, "
            "`write_scope`, `read_context`) is relative to the WORKTREE ROOT, "
            "not to your working directory.\n"
            "- Write your return artifact to this exact absolute path:\n"
            f"  `{handle.worktree_root / authority['expected_result_path']}`\n"
            "- Write your outbox completion envelope to this exact absolute "
            "path:\n"
            f"  `{handle.worktree_root / authority['expected_outbox_path']}`\n"
            "- Use those absolute paths verbatim. Do NOT write the packet's "
            "relative path as-is; it would resolve under your working "
            "directory and land outside the declared write scope.\n"
        )
        concise_prompt = (
            trusted_task_prompt.strip()
            + path_contract
            + "\n## Read-only task runtime envelope\n\n"
            + "```json\n"
            + projection_json
            + "\n```\n"
        )
        gemini_command = (
            str(executable),
            *tuple(authority["lane_args"]),
            *directory_args,
            "--output-format",
            "stream-json",
            *role_capability_args,
            "-p",
            concise_prompt,
        )
        gemini_prompt_path = (
            handle.worktree_root / "model-lanes" / "gemini" / "GEMINI.md"
        )
        base_gemini_prompt = gemini_prompt_path.read_text(encoding="utf-8")
        gemini_prompt_path.write_text(
            base_gemini_prompt.rstrip()
            + "\n\n## Board-dispatched specialist context\n\n"
            + agent_system_context.rstrip()
            + "\n",
            encoding="utf-8",
        )
        try:
            return selected_launcher(canary_runner, gemini_command, **kwargs)
        finally:
            gemini_prompt_path.write_text(base_gemini_prompt, encoding="utf-8")

    def kimi_role_launcher(canary_runner, command, **kwargs):
        if len(command) < 4 or command[0] != str(executable) or command[1] != "-p":
            raise ValueError("Kimi launch command has an unexpected shape")
        projection_json = json.dumps(
            envelope.worker_projection(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        lead_allowlist_json = json.dumps(
            list(capability_plan.authorized_mcps),
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if len(lead_allowlist_json.encode("ascii")) > 2048:
            raise ValueError("Kimi lead MCP allowlist exceeds prompt bound")
        lead_contract = (
            "\n\n## Main-lead MCP contract\n\n"
            f"Exact allowed MCP server names: `{lead_allowlist_json}`.\n"
            "Only this main Kimi lead may call them. Native `Agent(...)` subagents remain MCP-free; "
            "do not ask a subagent to call or inherit MCP tools. Treat every other MCP as unavailable. "
            "Never reveal or pass MCP configuration, credentials, environment, or values.\n"
        )
        concise_prompt = (
            trusted_task_prompt.strip()
            + "\n\n## Read-only task runtime envelope\n\n"
            + "```json\n"
            + projection_json
            + "\n```\n"
            + lead_contract
        )
        role_path_args = tuple(capability_lane_args[-4:])
        role_capability_args = tuple(capability_lane_args[:-4])
        expected_role_path_args = (
            "--agent-file",
            str(handle.worktree_root / "model-lanes" / "kimi" / "main.yaml"),
            "--add-dir",
            str(handle.worktree_root),
        )
        if role_path_args != expected_role_path_args:
            raise ValueError("Kimi agent-file arguments changed after provisioning")
        proven_args = (
            tuple(authority["lane_args"])
            + role_path_args
            + role_capability_args
        )
        expected_tail = tuple(command[3:])
        if expected_tail != tuple(capability_lane_args) + tuple(authority["lane_args"]):
            raise ValueError("Kimi launch arguments changed after authentication")
        kimi_command = (
            str(executable),
            *proven_args,
            "--print",
            "--output-format",
            "stream-json",
            "-p",
            concise_prompt,
        )
        # main.yaml loads KIMI.md as its system prompt. Temporarily bind the
        # authenticated specialist role there for this child, then restore the
        # tracked worktree byte-for-byte before output integration.
        kimi_prompt_path = handle.worktree_root / "model-lanes" / "kimi" / "KIMI.md"
        specialist_suffix = (
            "\n\n## Board-dispatched specialist context\n\n"
            + agent_system_context.rstrip()
            + "\n"
        )
        return run_with_restored_prompt(
            kimi_prompt_path,
            specialist_suffix,
            lambda: selected_launcher(canary_runner, kimi_command, **kwargs),
        )

    lane_launcher = (
        kimi_role_launcher
        if execution_kind == "lane" and lane == "kimi"
        else gemini_ordered_launcher
        if execution_kind == "lane" and lane == "gemini"
        else selected_launcher
    )
    if vault_broker is not None:
        try:
            vault_broker.require_ready()
        except BrokerError as exc:
            block_after_provision(
                f"chrono-vault broker lost readiness before worker launch: {exc}"
            )
    try:
        completed = launch_task(
            envelope,
            signing_key,
            role,
            executable=executable,
            canary_runner=lambda: prepared,
            expected_task_id=task_id,
            expected_attempt_id=attempt_id,
            expected_generation=int(generation),
            now=now,
            lane_args=tuple(capability_lane_args) + tuple(authority["lane_args"]),
            timeout=launch_timeout,
            launcher=lane_launcher,
        )
    except ProcessTruthError as exc:
        hold_for_operator_stop(exc)
    except subprocess.TimeoutExpired as exc:
        block_after_provision(f"fresh lane CLI timed out: {exc}", failure_class="cli_timeout")
    except (FileNotFoundError, PermissionError) as exc:
        block_after_provision(f"fresh lane CLI is unavailable: {exc}", failure_class="cli_missing")
    if vault_broker is not None:
        try:
            vault_broker.close()
            vault_broker_closed = True
        except BrokerError as exc:
            block_after_provision(
                f"chrono-vault broker shutdown failed closed: {exc}"
            )
    if not isinstance(completed, subprocess.CompletedProcess):
        deny("fresh lane launcher returned the wrong receipt type")
    # If the launcher already streamed stdout live to the transcript fd, append only
    # stderr here so the log is not duplicated; otherwise write the full transcript.
    if _board_stdout_streamed[0]:
        write_board_transcript("", completed.stderr or "")
    else:
        write_board_transcript(completed.stdout or "", completed.stderr or "")
    if completed.returncode != 0:
        block_after_provision(
            "fresh lane CLI returned nonzero",
            failure_class="cli_nonzero",
            returncode=completed.returncode,
            cli_stdout=completed.stdout or "",
            cli_stderr=completed.stderr or "",
        )
    observed_memory_ids = set()

    def inspect_memory_event(value, *, in_record=False):
        if isinstance(value, dict):
            server = str(value.get("server") or value.get("server_name") or "")
            tool = str(value.get("tool") or value.get("name") or "")
            event_type = str(value.get("type") or "")
            record_event = in_record or (
                ("chrono-vault" in server or "chrono_vault" in server)
                and (tool == "record" or tool.endswith("__record"))
                and event_type in {"mcp_tool_call", "mcp_call", "tool_result", ""}
            )
            for child in value.values():
                inspect_memory_event(child, in_record=record_event)
        elif isinstance(value, list):
            for child in value:
                inspect_memory_event(child, in_record=in_record)
        elif isinstance(value, str):
            # Phase 4: extract mem-ids from ALL transcript strings, not only inside a
            # record CALL event. The recorded id comes back in the record RESULT event
            # (a separate stream event that does not carry the record tool name), so the
            # old in_record gate missed it -> false learning_status=degraded. Transcript
            # mem-ids only originate from vault tool results, and the "present in BOTH
            # transcript and artifact" check below still verifies it was not fabricated.
            observed_memory_ids.update(re.findall(r"\bmem-[0-9a-f]{8,64}\b", value))

    for output_line in (completed.stdout or "").splitlines():
        try:
            inspect_memory_event(json.loads(output_line))
        except json.JSONDecodeError:
            continue
    result_path = Path(expected_result_path)
    result_bytes = b""
    integration_receipt = None
    prepared_outputs = None
    if launch_mode == "trusted" and execution_kind == "lane":
        try:
            # Gemini runs with cwd=<worktree>/model-lanes/gemini (see
            # GEMINI_LANE_CWD_RELATIVE) while every packet path is worktree-root
            # relative, so a worker that resolves return_artifact against its own
            # cwd writes a real, complete artifact one directory tree too deep and
            # prevalidation blocks a finished run. Map those strays back onto the
            # declared paths before validating. Reclaim never overwrites an output
            # already at its declared path, so a worker that resolved the path
            # correctly is untouched.
            if execution_kind == "lane" and lane == "gemini":
                # Declared evidence is reclaimed with the result and envelope.
                # A declared evidence path that is absent blocks preparation, so
                # omitting these here would turn every Gemini packet that
                # declares a PoC into a stranded completion.
                reclaimed_outputs = reclaim_lane_cwd_outputs(
                    handle.worktree_root,
                    GEMINI_LANE_CWD_RELATIVE,
                    (
                        authority["expected_result_path"],
                        authority["expected_outbox_path"],
                        *(
                            str(declared.get("path", ""))
                            for declared in authority.get("evidence_outputs", [])
                            if isinstance(declared, dict) and declared.get("path")
                        ),
                    ),
                )
                if reclaimed_outputs:
                    write_board_note(
                        "reclaimed gemini lane-cwd outputs: "
                        + ", ".join(reclaimed_outputs)
                    )
            prepared_outputs = prepare_worktree_outputs(
                repo_path,
                handle.worktree_root,
                authority,
            )
            result_bytes = prepared_outputs.result_bytes
            artifact_text = result_bytes.decode("utf-8")
            matching_memory_ids = sorted(
                memory_id
                for memory_id in observed_memory_ids
                if memory_id in artifact_text
            )
            # Learning capture is best-effort, NOT a completion gate: a task that ran
            # and wrote its artifact is complete even if it recorded no vault memory id
            # (the outbox auto-capture handles learning). SOL/Fable Phase-2 fix — a
            # successful task must not be declared blocked for a missing memory note.
            completion_memory_id = matching_memory_ids[0] if matching_memory_ids else None
            learning_status = "captured" if completion_memory_id else "degraded"
        except DispatchContextError as exc:
            block_after_provision(
                f"fresh lane completion prevalidation failed: {exc}"
            )
        try:
            # A specialist CLI edits files; it does not commit them. Integration
            # only moves committed history, so without this the finalize step
            # blocked every code task ("worker left uncommitted in-scope code
            # changes") and stranded a finished response in the worktree. The
            # controller commits the residue itself, bounded by the dispatcher's
            # declared scope -- the out-of-scope and delete gates below still run.
            wti.commit_worker_residue(
                handle,
                authority["write_paths"],
                exclude_paths=(
                    authority["expected_result_path"],
                    authority["expected_outbox_path"],
                ),
            )
            integration_receipt = wti.integrate_worktree_commits(
                handle,
                authority["write_paths"],
                exclude_paths=(
                    authority["expected_result_path"],
                    authority["expected_outbox_path"],
                ),
                # Controller-side capability, resolved from the main-repo
                # canonical packet before launch. Empty for every packet that
                # does not carry an operator-approved deletion manifest, which
                # keeps the categorical refusal as the default.
                authorized_delete_paths=authorized_delete_paths,
                target_branch=os.environ.get("SQUAD_BASE_BRANCH", "v2"),
            )
        except wti.WorktreeIsolationError as exc:
            block_after_provision(
                f"fresh lane code integration failed: {exc}"
            )
        try:
            # The bridge is also the mode-close commit boundary: when the
            # authenticated evidence list contains the run manifest it promotes
            # evidence, runs the canonical verifier, and withholds this result
            # plus the watcher-visible envelope unless the report is PASS.
            bridge_receipt = publish_prepared_worktree_outputs(
                repo_path,
                prepared_outputs,
            )
        except ModeExitVerificationError as exc:
            block_after_provision(
                f"mode-exit verification failed: {exc}"
            )
        except DispatchContextError as exc:
            block_after_provision(
                f"fresh lane output bridge failed: {exc}"
            )

    receipt = {
        "status": "launched",
        "task_id": task_id,
        "attempt_id": attempt_id,
        "role_context_sha256": role.sha256,
        "worktree_root": str(handle.worktree_root),
        "worktree_branch": handle.branch,
        "lineage_sha256": delegation_lineage.lineage_sha256(lineage),
        "lineage_chain_depth": lineage.chain_depth,
        "envelope_sha256": envelope.envelope_sha256,
        "authority_sha256": authority_sha256,
        "scheduler_reservation_snapshot_sha256": scheduler_snapshot_sha256,
        "returncode": completed.returncode,
        "cli_exec_succeeded": True,
        "execution_mode": "real",
        "execution_kind": execution_kind,
        "authority_mode": (
            "strict-fd3-seatbelt" if launch_mode == "strict"
            else "trusted-host-unpinned"
        ),
        "final_worker_boundary": (
            "settled-seatbelt-profile" if launch_mode == "strict"
            else "trusted-host-normal-env"
        ),
        "capability_projection_sha256": capability_projection_sha256,
        "capability_enforcement": capability_enforcement,
        "authorized_mcps": authorized_mcps,
        "brokered_mcps": brokered_mcps,
        "vault_broker_required": vault_broker_required,
        "vault_broker_started": vault_broker_started,
        "configured_mcps": configured_mcps,
        "disabled_mcps": disabled_mcps,
        "authorized_tools": capability_projection["tools"],
        "available_tools": available_tools,
        "missing_tools": missing_tools,
        "capability_gaps": capability_gaps,
        # The audit record for a DEGRADED launch: which authorized servers were
        # unhealthy, verbatim what they said, and which managed credentials the
        # secret store did not supply. Absent these, a degraded attempt is
        # indistinguishable from a healthy one after the fact.
        "unhealthy_mcps": unhealthy_mcps,
        "unhealthy_mcp_status": unhealthy_mcp_status,
        "credential_missing": list(credential_missing),
        "capability_config_path": (
            str(capability_config_path)
            if capability_config_path is not None
            else None
        ),
        "memory_id": globals().get("completion_memory_id"),
        "learning_status": globals().get("learning_status", "unknown"),
        "cli_stdout_sha256": hashlib.sha256(
            (completed.stdout or "").encode("utf-8")
        ).hexdigest(),
        "cli_stderr_sha256": hashlib.sha256(
            (completed.stderr or "").encode("utf-8")
        ).hexdigest(),
    }
    if launch_mode == "trusted" and execution_kind == "lane":
        receipt.update({
            "expected_result_path": str(result_path),
            "expected_result_sha256": hashlib.sha256(result_bytes).hexdigest(),
            "main_artifact_path": bridge_receipt["artifact_path"],
            "main_artifact_sha256": bridge_receipt["artifact_sha256"],
            "artifact_promotions": bridge_receipt["artifact_promotions"],
            "main_envelope_path": bridge_receipt["envelope_path"],
            "main_envelope_sha256": bridge_receipt["envelope_sha256"],
            "response_status": bridge_receipt["status"],
            "worktree_integration": asdict(integration_receipt),
        })
        if bridge_receipt.get("mode_exit_verification") is not None:
            receipt["mode_exit_verification"] = bridge_receipt[
                "mode_exit_verification"
            ]
    # Worktree lifecycle. The pool provisions one worktree per attempt and
    # nothing ever released it, so release() sat with no production caller while
    # 44 worktrees (0.92 GB) accumulated across two days of dispatch.
    #
    # Release only a CLEAN tree. Integration has already committed the residue
    # inside write_scope, and `git worktree remove` deletes the directory but
    # never the branch, so for a clean tree everything the worker produced stays
    # reachable through `git show <branch>:<path>`. commit_worker_residue
    # deliberately leaves OUT-OF-SCOPE paths dirty -- that is exactly the content
    # removal would destroy and nothing else holds, so a dirty tree is retained
    # and named in the receipt instead of being silently cleaned. The leak
    # becomes bounded and visible rather than unbounded and silent.
    worktree_state = "retained"
    if execution_kind == "lane":
        try:
            residue = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(handle.worktree_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if residue.returncode != 0:
                worktree_state = "retained-status-unreadable"
            elif residue.stdout.strip():
                worktree_state = "retained-out-of-scope-residue"
            else:
                pool.release(handle)
                worktree_state = "released"
        except wti.WorktreeIsolationError:
            # Never fail a task that already succeeded over its own cleanup.
            worktree_state = "retained-release-failed"
        except OSError:
            worktree_state = "retained-status-unreadable"
    receipt["worktree_state"] = worktree_state
    print(json.dumps(receipt, sort_keys=True))
    # F3.2 (transport XOR): the pane-inbox packet was this supervisor's authenticated
    # launch file; the task is now terminally settled successfully, so remove it here —
    # the ONLY safe place (send-task must not, it races the detached supervisor that
    # reads the packet). Board tasks then leave no orphan in a pane inbox nothing
    # consumes, mirroring pane consumption. Best-effort; never fails a completed task.
    # Only lane dispatches have a validated pane-inbox packet (packet_path, set during
    # lane packet validation); offline-probe has none, so guard on execution_kind to
    # avoid a NameError that would escape as a spurious second (blocked) receipt.
    if (
        execution_kind == "lane"
        and not canary_cleanup_requested
    ):
        try:
            packet_path.unlink()
        except OSError:
            pass
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001
    block_after_provision(f"trusted launch failed: {exc}")
finally:
    if vault_broker is not None and not vault_broker_closed:
        try:
            vault_broker.close()
        except BrokerError as exc:
            write_board_note(f"chrono-vault broker cleanup failed: {exc}")
    if prepared is not None:
        prepared.close()
    close_writable_scopes(audited_scopes)
PYEOF
fi

usage >&2
exit 64
