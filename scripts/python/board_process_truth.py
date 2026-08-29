#!/usr/bin/env python3
"""Verify board process identity and publish receipts without guessing."""

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone

# board_process_truth is run as a script (bin/board-supervisor.sh, bin/vs-cancel-spawn.sh
# invoke it by path, so scripts/python is sys.path[0]) AND imported as a package
# member (host_admission, launch_hygiene both carry a `from . import` fallback),
# where the sibling dir is NOT on sys.path. Same guard registry_reconciler uses.
_this_dir = str(Path(__file__).resolve().parent)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)
from plan_item_binding import PlanItemBindingError, canonical_plan_item_ids

DESCRIPTOR_V1 = "board-dispatch-process/v1"
DESCRIPTOR_V2 = "board-dispatch-process/v2"
RECEIPT_V2 = "board-dispatch-receipt/v2"
RECEIPT_V1 = "board-dispatch-receipt/v1"

TERMINAL_OUTCOMES = {
    "complete",
    "needs_review",
    "needs_human",
    "blocked",
    "cancelled",
    "failed",
    "denied",
}
LEGACY_OUTCOMES = {
    "launched": "complete",
    "completed": "complete",
    "canceled": "cancelled",
}
ATTEMPT_IDENTITY_FIELDS = ("task_id", "attempt_id", "generation")
PROCESS_IDENTITY_FIELDS = ("pid", "pgid", "process_start_token", "argv_sha256")
MAX_JSON_BYTES = 1024 * 1024


def exact_generation(value):
    return type(value) is int and value >= 1


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProcessTruthError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _unique_object(rows):
    value = {}
    for key, item in rows:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_non_finite(_value):
    raise ValueError("non-finite JSON number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def _read_fd(fd):
    try:
        raw = os.pread(fd, MAX_JSON_BYTES + 1, 0)
        if len(raw) > MAX_JSON_BYTES:
            return None
        value = json.loads(
            raw.decode(),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
            parse_float=_finite_float,
        )
    except (OSError, RecursionError, UnicodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def load_json(path):
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        return _read_fd(fd)
    finally:
        os.close(fd)


def atomic_write_json(path, value, *, exclusive=False):
    path = Path(path)
    data = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("ascii")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent = os.open(str(path.parent), flags)
    temporary = ".%s.%s.%s.tmp" % (path.name, os.getpid(), time.time_ns())
    created = False
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            try:
                os.link(
                    temporary,
                    path.name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileExistsError:
                return False
        else:
            os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            created = False
        os.fsync(parent)
        return True
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=parent)
                os.fsync(parent)
            except FileNotFoundError:
                pass
        os.close(parent)


def observe_process(pid):
    try:
        pid, pgid = int(pid), os.getpgid(int(pid))
    except (TypeError, ValueError, OSError):
        return None
    proc = Path("/proc/%d/stat" % pid)
    if proc.is_file():
        try:
            fields = proc.read_text(encoding="ascii").rsplit(")", 1)[1].split()
            argv = Path("/proc/%d/cmdline" % pid).read_bytes()
        except (OSError, IndexError):
            return None
        if len(fields) <= 19 or fields[0] == "Z" or not argv:
            return None
        token = "proc:" + fields[19]
    else:
        result = subprocess.run(
            [
                "/bin/ps",
                "-ww",
                "-p",
                str(pid),
                "-o",
                "state=",
                "-o",
                "lstart=",
                "-o",
                "command=",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
        )
        parts = result.stdout.strip().split(maxsplit=6)
        if result.returncode or len(parts) != 7 or parts[0].startswith(b"Z"):
            return None
        token, argv = "ps:" + b" ".join(parts[1:6]).decode("ascii"), parts[6]
    return {
        "pid": pid,
        "pgid": pgid,
        "process_start_token": token,
        "argv_sha256": hashlib.sha256(argv).hexdigest(),
    }


def process_run_state(pid):
    """Return 'running', 'stopped', or None -- liveness, NOT identity.

    Deliberately separate from observe_process(). Identity must survive a stop,
    because _freeze_tree() SIGSTOPs a tree and then re-observes it to confirm it
    froze the process it meant to; if a stopped process stopped being
    observable, every teardown would fail. So process state is not part of the
    identity token and never can be.

    The consequence was that "a PID with matching identity exists" was the only
    liveness concept available, and a SIGSTOPped supervisor therefore read as
    live. Measured 2026-08-22: one sat stopped for 9h30m while the health
    monitor stayed silent, because `ps state=` was parsed only far enough to
    reject 'Z'. The missing concept is *runnable*, and this is it.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    proc = Path("/proc/%d/stat" % pid)
    if proc.is_file():
        try:
            fields = proc.read_text(encoding="ascii").rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            return None
        if not fields:
            return None
        return "stopped" if fields[0] in ("T", "t") else "running"
    result = subprocess.run(
        ["/bin/ps", "-ww", "-p", str(pid), "-o", "state="],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
    )
    state = result.stdout.strip()
    if result.returncode or not state:
        return None
    # Darwin prefixes the run state, then appends flags (T, TN, T+, ...).
    return "stopped" if state[:1] in (b"T", b"t") else "running"


def timestamp_epoch(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
        return int(parsed.timestamp()) if parsed.tzinfo is not None else None
    except (OSError, OverflowError, ValueError):
        return None


def descriptor_error(path, value, *, require_v2=False):
    if not isinstance(value, dict):
        return "descriptor_schema"
    schema = value.get("schema")
    if not isinstance(schema, str) or schema not in {DESCRIPTOR_V1, DESCRIPTOR_V2}:
        return "descriptor_schema"
    if require_v2 and schema != DESCRIPTOR_V2:
        return "legacy_process_identity_unverifiable"
    task, attempt, generation = (value.get(key) for key in ATTEMPT_IDENTITY_FIELDS)
    if (
        not isinstance(task, str)
        or not IDENTIFIER.fullmatch(task)
        or not isinstance(attempt, str)
        or not IDENTIFIER.fullmatch(attempt)
        or not exact_generation(generation)
    ):
        return "descriptor_identity"
    path, suffix = Path(path), ".dispatch.json"
    base = str(path)[: -len(suffix)] if str(path).endswith(suffix) else ""
    if path.name != "%s.%s%s" % (task, attempt, suffix):
        return "descriptor_filename_identity"
    expected = {
        "context_path": base + ".context.json",
        "log_path": base + ".log",
        "receipt_path": base + ".receipt.json",
    }
    if any(
        not isinstance(value.get(key), str)
        or os.path.abspath(value[key]) != os.path.abspath(item)
        for key, item in expected.items()
    ):
        return "descriptor_paths"
    if schema == DESCRIPTOR_V2 and (
        timestamp_epoch(value.get("created_at")) is None
        or not exact_generation(value.get("pid"))
        or not exact_generation(value.get("pgid"))
        or value.get("pid") != value.get("pgid")
        or not isinstance(value.get("process_start_token"), str)
        or not value["process_start_token"]
        or not isinstance(value.get("argv_sha256"), str)
        or not SHA256.fullmatch(value["argv_sha256"])
    ):
        return "descriptor_process_identity"
    # Optional by design: a descriptor without a declaration is every packet that
    # does not opt in, and rejecting those would break every existing flow. A
    # PRESENT declaration must be well-formed, because finalize_receipt publishes
    # it as the dispatcher's word on what this task closes.
    if "plan_item_ids" in value:
        try:
            canonical_plan_item_ids(value["plan_item_ids"])
        except PlanItemBindingError:
            return "descriptor_plan_item_ids"
    return None


def context_matches(descriptor, context):
    authority = context.get("authority") if isinstance(context, dict) else None
    return (
        isinstance(authority, dict)
        and exact_generation(authority.get("generation"))
        and exact_generation(descriptor.get("generation"))
        and tuple(authority.get(key) for key in ATTEMPT_IDENTITY_FIELDS)
        == tuple(descriptor.get(key) for key in ATTEMPT_IDENTITY_FIELDS)
    )


def _terminal_evidence(context):
    """Best-effort evidence snapshot for a sealed attempt worktree, if one exists.

    Terminal receipt publication must never be suppressed by salvage failure.
    Conversely, an absent worktree before provisioning is ordinary and should
    not add noise to an early denial. Once an exact attempt directory exists,
    every outcome records either its preserved Git location or the bounded error
    plus retained worktree location that needs attention.
    """

    authority = context.get("authority") if isinstance(context, dict) else None
    if not isinstance(authority, dict):
        return None
    task_id = authority.get("task_id")
    attempt_id = authority.get("attempt_id")
    pool_root = authority.get("pool_root")
    if (
        not isinstance(task_id, str)
        or not isinstance(attempt_id, str)
        or not isinstance(pool_root, str)
        or not Path(pool_root).is_absolute()
    ):
        return None
    worktree = Path(pool_root) / attempt_id
    if not worktree.is_dir():
        return None
    try:
        import worktree_isolation as wti

        return asdict(wti.preserve_terminal_evidence(authority))
    except Exception as exc:  # noqa: BLE001 - receipt publication must survive salvage
        reason = " ".join(str(exc).split())[:600]
        # Say it on the terminal, not only inside the receipt. cancel/reap both
        # exit 0 after terminalising the attempt, so an unpreservable worktree
        # otherwise reads as an ordinary clean cancel until somebody re-reads the
        # receipt or the reconciler's PRESERVED WORK line scrolls past. This is
        # the one route where committed work is left sitting only in a worktree
        # that later reclamation is entitled to remove.
        print(
            f"WARNING: could not preserve {task_id}/{attempt_id} onto a branch; "
            f"its work is RETAINED ONLY IN {worktree} -- {reason}",
            file=sys.stderr,
        )
        return {
            "status": "error",
            "task_id": task_id,
            "attempt_id": attempt_id,
            "selection_policy": (
                "declared-write-scope+explicit-outputs+git-ignore+bounded-untracked/v1"
            ),
            "evidence_location": "",
            "worktree_location": str(worktree),
            "worktree_retained_required": True,
            "reason": reason or type(exc).__name__,
        }


def _process_identity(descriptor):
    return {key: descriptor[key] for key in PROCESS_IDENTITY_FIELDS}


def process_truth(path, descriptor):
    error = descriptor_error(path, descriptor, require_v2=True)
    if error:
        return {"state": "invalid", "reason": error, "observed": None}
    observed = observe_process(descriptor["pid"])
    expected = _process_identity(descriptor)
    if observed is None:
        return {"state": "dead", "reason": "process_not_live", "observed": None}
    try:
        session_matches = os.getsid(descriptor["pid"]) == descriptor["pid"]
    except OSError:
        session_matches = False
    if observed != expected or not session_matches:
        return {
            "state": "mismatch",
            "reason": "process_identity_mismatch",
            "observed": observed,
        }
    # `runnable` is ADDITIVE on purpose. The "live" string stays exactly as it
    # was because cancel_attempt() and reap refuse to act unless state == "live"
    # -- demoting a stopped attempt out of "live" would make the one recovery
    # you most need (cancelling a stuck lane) impossible. Callers that care
    # about schedulability opt in by reading this field; everything else is
    # unaffected by construction.
    run_state = process_run_state(descriptor["pid"])
    return {
        "state": "live",
        "reason": "exact_live_process",
        "observed": observed,
        "runnable": run_state != "stopped",
        "run_state": run_state or "unknown",
    }


def descriptor_hash(descriptor):
    canonical = json.dumps(
        descriptor, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def terminal_outcome(receipt, descriptor):
    if (
        not isinstance(receipt, dict)
        or not isinstance(descriptor, dict)
        or any(
            receipt.get(key) != descriptor.get(key) for key in ("task_id", "attempt_id")
        )
    ):
        return None
    if not exact_generation(descriptor.get("generation")):
        return None
    if receipt.get("schema") == RECEIPT_V2:
        outcome = receipt.get("terminal_outcome")
        return (
            outcome
            if descriptor.get("schema") == DESCRIPTOR_V2
            and exact_generation(receipt.get("generation"))
            and receipt.get("generation") == descriptor.get("generation")
            and receipt.get("descriptor_sha256") == descriptor_hash(descriptor)
            and isinstance(outcome, str)
            and outcome in TERMINAL_OUTCOMES
            and timestamp_epoch(receipt.get("completed_at")) is not None
            else None
        )
    receipt_schema = receipt.get("schema")
    if (
        descriptor.get("schema") != DESCRIPTOR_V1
        or descriptor.get("generation") != 1
        or receipt_schema not in (None, RECEIPT_V1)
        or (
            receipt.get("generation") is not None
            and (
                not exact_generation(receipt.get("generation"))
                or receipt.get("generation") != 1
            )
        )
    ):
        return None
    status = receipt.get("response_status") or receipt.get("status")
    if not isinstance(status, str):
        return None
    if status in TERMINAL_OUTCOMES:
        return status
    return LEGACY_OUTCOMES.get(status)


def _bound(path, identity):
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (current.st_dev, current.st_ino) == identity


def _locked(path):
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        observed = os.fstat(fd)
        identity = (observed.st_dev, observed.st_ino)
        if not stat.S_ISREG(observed.st_mode) or not _bound(path, identity):
            raise ProcessTruthError("descriptor pathname changed")
        return fd, _read_fd(fd), identity
    except BaseException:
        os.close(fd)
        raise


CAPTURE_EXCERPT_BYTES = 320
INVALID_RECEIPT_REASON_LIMIT = 600


def _bounded_reason(text):
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= INVALID_RECEIPT_REASON_LIMIT:
        return collapsed
    return collapsed[: INVALID_RECEIPT_REASON_LIMIT - 3] + "..."


def _capture_excerpt(raw_path):
    """Bounded, printable-only prefix of a capture that would not parse.

    Untrusted bytes: control characters are folded to spaces and the whole thing
    is length-capped, because this string is embedded in a published receipt and
    read by an operator. O_NOFOLLOW matches load_json's discipline -- the capture
    is re-opened here, and a path swapped for a symlink between the two reads
    must not redirect the excerpt.
    """
    try:
        fd = os.open(str(raw_path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            head = os.pread(fd, CAPTURE_EXCERPT_BYTES + 1, 0)
        finally:
            os.close(fd)
    except OSError as exc:
        return "<unreadable: %s>" % exc
    truncated = len(head) > CAPTURE_EXCERPT_BYTES
    text = head[:CAPTURE_EXCERPT_BYTES].decode("utf-8", "replace")
    text = " ".join(
        "".join(item if item.isprintable() else " " for item in text).split()
    )
    return (text + " ...") if truncated else text


def invalid_receipt_reason(raw_path, raw, descriptor):
    """Say WHY a capture is not a usable receipt -- never merely that it is not.

    The finalizer is fail-closed on purpose: anything it cannot bind to this
    exact attempt terminalises as blocked, and that stays true. What it must not
    do is terminalise ANONYMOUSLY. Until 2026-08-10 every one of these
    conditions -- an empty capture, an oversized capture, diagnostics
    interleaved with an otherwise valid receipt, a receipt belonging to a
    different attempt -- published the single string "invalid launch receipt".
    That string is what an operator reads when a lane dies, and it distinguishes
    none of them, so the board's observability was weakest at the exact moment
    it was needed. Each branch below names the observed condition instead.
    """
    if not isinstance(raw, dict):
        try:
            size = os.stat(raw_path).st_size
        except OSError as exc:
            return _bounded_reason("launch receipt capture could not be read: %s" % exc)
        if size == 0:
            return (
                "launch receipt capture was empty: the launch process exited "
                "without writing a receipt to stdout"
            )
        if size > MAX_JSON_BYTES:
            return _bounded_reason(
                "launch receipt capture is %d bytes, over the %d-byte receipt "
                "bound; stdout begins: %s"
                % (size, MAX_JSON_BYTES, _capture_excerpt(raw_path))
            )
        return _bounded_reason(
            "launch receipt capture is not one JSON object (%d bytes); stdout "
            "begins: %s" % (size, _capture_excerpt(raw_path))
        )
    mismatched = [
        key
        for key in ATTEMPT_IDENTITY_FIELDS
        if key in raw and raw[key] != descriptor.get(key)
    ]
    if mismatched:
        return _bounded_reason(
            "launch receipt belongs to a different attempt: "
            + ", ".join(
                "%s=%r expected %r" % (key, raw[key], descriptor.get(key))
                for key in mismatched
            )
        )
    if "generation" in raw and not exact_generation(raw["generation"]):
        return _bounded_reason(
            "launch receipt generation is not an exact positive integer: %r"
            % (raw["generation"],)
        )
    non_string = [
        key
        for key in ("response_status", "status")
        if key in raw and not isinstance(raw[key], str)
    ]
    if non_string:
        return _bounded_reason(
            "launch receipt "
            + " and ".join(
                "%s is not a string: %r" % (key, raw[key]) for key in non_string
            )
        )
    # Unreachable while this mirrors the `exact` predicate; kept total so a
    # future exactness rule cannot silently reintroduce an anonymous block.
    return "launch receipt failed an exactness check with no distinguishing condition"


def finalize_receipt(raw_path, dispatch_path, receipt_path):
    fd, descriptor, inode = _locked(dispatch_path)
    try:
        error = descriptor_error(dispatch_path, descriptor, require_v2=True)
        if error or not _bound(dispatch_path, inode):
            raise ProcessTruthError(error or "descriptor pathname changed")
        existing = load_json(receipt_path)
        if os.path.lexists(str(receipt_path)):
            if terminal_outcome(existing, descriptor):
                return existing
            raise ProcessTruthError("mismatched receipt occupies exact path")
        if process_truth(dispatch_path, descriptor)["state"] != "live":
            raise ProcessTruthError("finalizer lost exact live process identity")
        raw = load_json(raw_path)
        exact = (
            isinstance(raw, dict)
            and all(
                key not in raw or raw[key] == descriptor[key]
                for key in ATTEMPT_IDENTITY_FIELDS
            )
            and ("generation" not in raw or exact_generation(raw["generation"]))
            and all(
                key not in raw or isinstance(raw[key], str)
                for key in ("response_status", "status")
            )
        )
        payload = (
            dict(raw)
            if exact
            else {
                "status": "blocked",
                "reason": invalid_receipt_reason(raw_path, raw, descriptor),
            }
        )
        response, status = payload.get("response_status"), payload.get("status")
        if isinstance(response, str) and response in TERMINAL_OUTCOMES:
            outcome = response
        elif isinstance(status, str) and status in TERMINAL_OUTCOMES:
            outcome = status
        elif status == "launched":
            outcome = "complete"
        else:
            outcome = "blocked"
        # ``status == launched`` is the supervisor's promotion proof: code was
        # integrated and both canonical outputs were atomically published before
        # that receipt could be emitted. Every other terminal route may contain
        # unpromoted work, irrespective of whether its outcome is blocked,
        # denied, failed, or a malformed-capture fallback. Snapshot it before the
        # receipt commit point, and let the receipt make the location discoverable.
        if status != "launched":
            evidence = _terminal_evidence(load_json(descriptor["context_path"]))
            if evidence is not None:
                payload["evidence_preservation"] = evidence
        # These fields are the DISPATCHER's, and this update overwrites whatever
        # the capture claimed rather than merging with it. `plan_item_ids` belongs
        # here for exactly that reason: a worker that could name its own
        # completions could mark any plan item done. The declaration travels
        # packet -> descriptor -> receipt and is never read back from the worker.
        payload.update(
            {
                "schema": RECEIPT_V2,
                "task_id": descriptor["task_id"],
                "attempt_id": descriptor["attempt_id"],
                "generation": descriptor["generation"],
                "completed_at": utc_now(),
                "terminal_outcome": outcome,
                "descriptor_sha256": descriptor_hash(descriptor),
                "plan_item_ids": canonical_plan_item_ids(
                    descriptor.get("plan_item_ids")
                ),
            }
        )
        if not atomic_write_json(receipt_path, payload, exclusive=True):
            raise ProcessTruthError("receipt publication lost its fence")
        return payload
    finally:
        os.close(fd)


def _process_rows():
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,pgid=,state="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ProcessTruthError("process tree observation failed")
    return [
        tuple(map(int, parts[:3]))
        for line in result.stdout.splitlines()
        if len(parts := line.split()) == 4
        and all(item.isdigit() for item in parts[:3])
        and not parts[3].startswith("Z")
    ]


def _signal_identity(identity, signum, *, target, operation):
    # Darwin has no pidfd: re-observe immediately before every PID signal, then
    # freeze the exact session leader before any numeric process-group signal.
    observed = observe_process(identity["pid"])
    if observed is None:
        return False
    if observed != identity:
        mismatches = []
        for field in PROCESS_IDENTITY_FIELDS:
            if observed[field] == identity[field]:
                continue
            if field == "argv_sha256":
                mismatches.append(
                    "%s expected_prefix=%s observed_prefix=%s"
                    % (field, identity[field][:12], observed[field][:12])
                )
            else:
                mismatches.append(
                    "%s expected=%r observed=%r"
                    % (field, identity[field], observed[field])
                )
        raise ProcessTruthError(
            "process identity changed before signal: pid=%s pgid=%s signal=%s "
            "target=%s operation=%s; mismatches: %s"
            % (
                identity["pid"],
                identity["pgid"],
                int(signum),
                target,
                operation,
                "; ".join(mismatches),
            )
        )
    os.kill(identity["pid"], signum)
    return True


def _freeze_tree(expected):
    root, pgid = expected["pid"], expected["pgid"]
    stopped = {}
    if (
        not _signal_identity(
            expected, signal.SIGSTOP, target="tree_root", operation="freeze"
        )
        or observe_process(root) != expected
    ):
        raise ProcessTruthError("session leader could not be identity-frozen")
    os.killpg(pgid, signal.SIGSTOP)
    try:
        for _ in range(8):
            rows, descendants = _process_rows(), {root}
            while True:
                found = descendants | {
                    pid for pid, parent, _group in rows if parent in descendants
                }
                if found == descendants:
                    break
                descendants = found
            scoped = [
                (pid, group) for pid, _parent, group in rows if pid in descendants
            ]
            pending = [
                (pid, group)
                for pid, group in scoped
                if group != pgid and pid not in stopped
            ]
            for pid, _group in pending:
                identity = observe_process(pid)
                if identity is not None and _signal_identity(
                    identity,
                    signal.SIGSTOP,
                    target="descendant",
                    operation="freeze",
                ):
                    stopped[pid] = identity
            if pending:
                continue
            identities = [observe_process(pid) for pid, _group in scoped]
            if None not in identities and expected in identities:
                return identities, [item for item in identities if item["pgid"] != pgid]
        raise ProcessTruthError("process tree did not stabilize while frozen")
    except BaseException:
        for identity in stopped.values():
            try:
                _signal_identity(
                    identity,
                    signal.SIGCONT,
                    target="descendant",
                    operation="continue",
                )
            except (OSError, ProcessTruthError):
                # Swallowed deliberately: raising during rollback would mask the
                # original exception. So the operation="continue" mismatch detail
                # is built and discarded here and can never reach a transcript --
                # do not expect that string in an operator note.
                pass
        if observe_process(root) == expected:
            os.killpg(pgid, signal.SIGCONT)
        raise


def terminate_attributable_tree(expected, grace):
    if (
        not isinstance(expected, dict)
        or set(expected) != set(PROCESS_IDENTITY_FIELDS)
        or expected.get("pid") != expected.get("pgid")
    ):
        raise ProcessTruthError("process-tree root is not an exact group leader")
    try:
        if os.getsid(expected["pid"]) != expected["pid"]:
            raise ProcessTruthError("process-tree root is not a session leader")
    except OSError as exc:
        raise ProcessTruthError("process-tree root session is unavailable") from exc
    members, escaped = _freeze_tree(expected)
    for identity in escaped:
        _signal_identity(
            identity,
            signal.SIGTERM,
            target="descendant",
            operation="terminate",
        )
    if observe_process(expected["pid"]) != expected:
        raise ProcessTruthError("session leader identity changed before group signal")
    os.killpg(expected["pgid"], signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(
        observe_process(item["pid"]) == item for item in members
    ):
        time.sleep(0.05)
    live = [item for item in members if observe_process(item["pid"]) == item]
    for identity in live:
        if identity["pgid"] != expected["pgid"]:
            _signal_identity(
                identity,
                signal.SIGKILL,
                target="descendant",
                operation="terminate",
            )
    if any(item["pgid"] == expected["pgid"] for item in live):
        os.killpg(expected["pgid"], signal.SIGKILL)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and any(
        observe_process(item["pid"]) == item for item in members
    ):
        time.sleep(0.02)
    if any(observe_process(item["pid"]) == item for item in members):
        raise ProcessTruthError("verified process tree survived cancellation")


def cancel_attempt(dispatch_path, grace):
    fd, descriptor, inode = _locked(dispatch_path)
    try:
        error = descriptor_error(dispatch_path, descriptor, require_v2=True)
        context = load_json(descriptor["context_path"])
        if error or not context_matches(descriptor, context):
            raise ProcessTruthError(error or "exact identity fence mismatch")
        if os.path.lexists(descriptor["receipt_path"]):
            raise ProcessTruthError("attempt already has a receipt")
        if process_truth(dispatch_path, descriptor)["state"] != "live" or not _bound(
            dispatch_path, inode
        ):
            raise ProcessTruthError("refusing stale process identity")
        expected = _process_identity(descriptor)
        terminate_attributable_tree(expected, grace)
        receipt = {
            "schema": RECEIPT_V2,
            "task_id": descriptor["task_id"],
            "attempt_id": descriptor["attempt_id"],
            "generation": descriptor["generation"],
            "status": "cancelled",
            "terminal_outcome": "cancelled",
            "failure_class": "cancelled",
            "reason": "cancelled by operator",
            "completed_at": utc_now(),
            "descriptor_sha256": descriptor_hash(descriptor),
        }
        evidence = _terminal_evidence(context)
        if evidence is not None:
            receipt["evidence_preservation"] = evidence
        if not atomic_write_json(descriptor["receipt_path"], receipt, exclusive=True):
            raise ProcessTruthError("cancel receipt lost its fence")
        return descriptor
    finally:
        os.close(fd)


def reap_dead_attempt(dispatch_path):
    """Resolve an attempt whose process is gone and which published no receipt.

    Deliberately narrower than cancel_attempt(): this signals nothing and admits
    only `process_not_live`. A `mismatch` means the PID was recycled, so the
    original process's fate is unknown and reaping could mask a live worker --
    that stays an operator decision.

    Without this path the board deadlocks. discover_live_attempts() fails closed
    on a dead descriptor holding no fenced receipt, while cancel_attempt() and
    finalize_receipt() both require an exact live process, so nothing shipped can
    clear it and every later dispatch is refused. hold_for_operator_stop() parks
    a supervisor under SIGSTOP without a receipt; killing that held supervisor is
    what strands the descriptor. SIGKILL is untrappable, so "always receipt on
    exit" cannot close this on its own.
    """
    fd, descriptor, inode = _locked(dispatch_path)
    try:
        error = descriptor_error(dispatch_path, descriptor, require_v2=True)
        if error or not _bound(dispatch_path, inode):
            raise ProcessTruthError(error or "descriptor pathname changed")
        context = load_json(descriptor["context_path"])
        if not context_matches(descriptor, context):
            raise ProcessTruthError("exact identity fence mismatch")
        if os.path.lexists(descriptor["receipt_path"]):
            raise ProcessTruthError("attempt already has a receipt")
        truth = process_truth(dispatch_path, descriptor)
        if truth["state"] != "dead":
            raise ProcessTruthError(
                f"refusing to reap a {truth['state']} attempt: {truth['reason']}"
            )
        receipt = {
            "schema": RECEIPT_V2,
            "task_id": descriptor["task_id"],
            "attempt_id": descriptor["attempt_id"],
            "generation": descriptor["generation"],
            "status": "failed",
            "terminal_outcome": "failed",
            "failure_class": "process_died_without_receipt",
            "reason": "reaped: process is not live and published no receipt",
            "completed_at": utc_now(),
            "descriptor_sha256": descriptor_hash(descriptor),
        }
        evidence = _terminal_evidence(context)
        if evidence is not None:
            receipt["evidence_preservation"] = evidence
        if not atomic_write_json(descriptor["receipt_path"], receipt, exclusive=True):
            raise ProcessTruthError("reap receipt lost its fence")
        return receipt
    finally:
        os.close(fd)


def main():
    args = sys.argv[1:]
    try:
        if args[:1] == ["finalize-receipt"] and len(args) == 4:
            print(json.dumps(finalize_receipt(*args[1:]), sort_keys=True))
            return 0
        if args[:1] == ["reap"] and len(args) == 3 and args[2].endswith(".log"):
            vault, log = Path(args[1]), Path(args[2])
            if log.resolve().parent != (vault / "_state" / "board-dispatch").resolve():
                raise ProcessTruthError("log is outside board-dispatch")
            receipt = reap_dead_attempt(Path(str(log)[:-4] + ".dispatch.json"))
            reconciler = vault / "bin" / "registry-reconciler.sh"
            if os.access(reconciler, os.X_OK):
                subprocess.run(
                    [str(reconciler), "--task-id", receipt["task_id"]],
                    env={**os.environ, "VAULT_ROOT": str(vault),
                         "RESPONSE_MIN_AGE_SECONDS": "0"},
                    check=False,
                )
            print(
                "reaped %s/%s generation %s"
                % tuple(receipt[key] for key in ("task_id", "attempt_id", "generation"))
            )
            return 0
        if args[:1] != ["cancel"] or len(args) != 3 or not args[2].endswith(".log"):
            return 2
        vault, log = Path(args[1]), Path(args[2])
        board = vault / "_state" / "board-dispatch"
        if log.resolve().parent != board.resolve():
            raise ProcessTruthError("log is outside board-dispatch")
        dispatch = Path(str(log)[:-4] + ".dispatch.json")
        grace = max(0, min(float(os.environ.get("VS_CANCEL_GRACE_SECONDS", "5")), 60))
        reconciler = vault / "bin" / "registry-reconciler.sh"
        observed = os.stat(reconciler, follow_symlinks=False)
        if not stat.S_ISREG(observed.st_mode) or not os.access(reconciler, os.X_OK):
            raise ProcessTruthError("exact registry reconciler is unavailable")
        descriptor = cancel_attempt(dispatch, grace)
        environment = {
            **os.environ,
            "VAULT_ROOT": str(vault),
            "RESPONSE_MIN_AGE_SECONDS": "0",
        }
        if subprocess.run(
            [str(reconciler), "--task-id", descriptor["task_id"]],
            env=environment,
            check=False,
        ).returncode:
            raise ProcessTruthError("exact registry reconciliation failed")
        print(
            "cancelled %s/%s generation %s"
            % tuple(descriptor[key] for key in ("task_id", "attempt_id", "generation"))
        )
        return 0
    except (OSError, ValueError, ProcessTruthError) as exc:
        print("process truth refused: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
