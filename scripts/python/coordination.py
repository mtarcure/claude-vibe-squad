#!/usr/bin/env python3
"""Library-only delegation checkpoint/continuation records (V2 Task 2.4, F5).

This module does not dispatch work and has no live production caller. The
currently supported continuation route is manual and controller-owned:

    requester emits bounded delegation request
      -> Chrono records any checkpoint it chooses to preserve
      -> Chrono authors and dispatches an ordinary board child packet
      -> child RESULT settles
      -> Chrono authors the next ordinary packet with a bounded Markdown capsule

The checkpoint helpers retain TTL, cancellation, crash-recovery, and
duplicate/stale-return fencing for compatibility tests. Their existence does
not imply automatic child dispatch, return injection, or a running sweeper.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from delegation_lineage import (
    DelegationAuthority,
    DelegationDenied,
    DelegationLineage,
    LineageBudget,
    advance,
    authority_sha256,
    lineage_from_dict,
    lineage_sha256,
    lineage_to_dict,
)


CHECKPOINT_SCHEMA = "delegation-checkpoint/v1"
NON_TERMINAL_STATES = {"checkpointed", "dispatched"}
TERMINAL_STATES = {"settled", "cancelled", "stale"}
DEFAULT_TTL_SECONDS = 300.0
MAX_TTL_SECONDS = 2_592_000.0  # 30 days: generous but explicit and finite.
DELEGATION_ID_RE = re.compile(r"^deleg-[0-9a-f]{32}$")


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_ttl(ttl_seconds: float | None) -> float:
    """Reject non-finite/negative/zero/absurdly-large TTLs before any file
    is written. NaN in particular makes every ordinary >=/>= expiry
    comparison silently False forever -- the exact defect a NaN-TTL
    checkpoint exploited to never expire, even after the clock advanced to
    1e100."""

    if ttl_seconds is None:
        return DEFAULT_TTL_SECONDS
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
        raise DelegationDenied(f"ttl_seconds must be a finite number, got {ttl_seconds!r}")
    value = float(ttl_seconds)
    if not math.isfinite(value) or value <= 0 or value > MAX_TTL_SECONDS:
        raise DelegationDenied(
            "ttl_seconds must be finite, positive, and at most "
            f"{MAX_TTL_SECONDS}, got {ttl_seconds!r}"
        )
    return value


def _teardown_lock_dir(lock_dir: Path, state_dir: Path) -> None:
    """Atomically remove ``lock_dir`` from its shared, contended path
    before deleting its contents, so it never exists in an
    empty-but-not-yet-removed state that a concurrent acquirer's rename
    could land on (``os.rename()`` onto an existing EMPTY directory
    succeeds on this filesystem -- confirmed directly, not assumed)."""

    graveyard = state_dir / f".delegation-lock-releasing.{os.getpid()}.{os.urandom(8).hex()}"
    os.rename(str(lock_dir), str(graveyard))
    try:
        (graveyard / "owner.pid").unlink(missing_ok=True)
    finally:
        graveyard.rmdir()


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def _store_lock(state_dir: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Mkdir-based mutual exclusion scoped to this store's own state
    directory (not the shared chrono-notify.lockdir, which guards a
    different resource). Like registry_reconciler.lockdir, the claim and its owner
    marker are written in a private staging directory FIRST, then published
    with a single ``os.rename()`` -- the same prepare-then-atomically-
    publish idiom ``_atomic_write_json`` already uses for files, applied to
    a directory. This closes the exact crash window the original two-step
    ``mkdir()`` then a separate ``owner.pid`` write left open: no observer
    can ever see the lock directory exist without its owner marker already
    inside it, so a transient/partial owner.pid can no longer be misread as
    stale (stealing an actively-held lock), and a genuine crash between the
    old two steps can no longer leave a permanently unreclaimable ownerless
    lock.

    Release is made atomic the same way, for a reason discovered only by
    stress-testing: ``os.rename()`` onto an EXISTING, EMPTY target
    directory also succeeds (verified directly against this filesystem),
    so a naive two-step release (``owner_path.unlink()`` then a separate
    ``lock_dir.rmdir()``) still leaves a real -- not merely theoretical --
    window where a concurrent acquirer's rename lands on the momentarily-
    empty ``lock_dir`` and "steals" it during an otherwise-ordinary
    release, not only after a crash. The owning thread now renames the
    whole lock directory away to a private, contention-free path in one
    atomic step before tearing it down, so ``lock_dir`` never exists in an
    empty-but-not-yet-removed state at all.

    A missing ``owner.pid`` while ``lock_dir`` itself still exists is
    deliberately NOT treated as an instant-reclaim signal, even though
    atomicity makes it a rare state. A `stale = True` shortcut here was
    tried and stress-tested to a real, reproducible failure: the read of
    ``owner_path`` and the later reclaim of ``lock_dir`` are two separate
    steps, and in the gap between them a DIFFERENT thread can legitimately
    acquire a brand-new ``lock_dir`` (once the old one finished a clean
    release) -- the "stale" diagnosis, made against the OLD state, would
    then blindly tear down that new thread's live lock, letting a third
    thread acquire concurrently with it. A genuine crash (kill -9 mid
    critical section) leaves a FULLY POPULATED ``owner.pid`` naming a now-
    dead PID, which the ordinary liveness branch below reclaims safely
    without this race, since acting on a confirmed-dead PID can never
    "un-die" out from under the check. The missing-owner-path case is left
    to the existing timeout -- fail-safe (a bounded, visible denial) rather
    than a fast reclaim that stress-testing proved can steal a live lock."""

    state_dir.mkdir(parents=True, exist_ok=True)
    lock_dir = state_dir / "delegation-lock.lockdir"
    owner_path = lock_dir / "owner.pid"
    deadline = time.monotonic() + timeout_seconds
    acquired = False

    while not acquired:
        staging = state_dir / f".delegation-lock-staging.{os.getpid()}.{os.urandom(8).hex()}"
        staging.mkdir()
        (staging / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        try:
            os.rename(str(staging), str(lock_dir))
            acquired = True
        except OSError:
            # Someone else holds the lock or won a concurrent race for it.
            # Never leave our own unclaimed staging directory behind.
            try:
                (staging / "owner.pid").unlink(missing_ok=True)
                staging.rmdir()
            except OSError:
                pass
            stale = False
            try:
                owner_text = owner_path.read_text(encoding="utf-8").strip()
                stale = not owner_text.isdigit() or not _pid_is_alive(int(owner_text))
            except OSError:
                # See the docstring above: this is deliberately NOT an
                # instant-reclaim signal, since diagnosing staleness and
                # acting on it are two separate steps a concurrent thread's
                # fresh, legitimate acquisition can race between.
                stale = False
            if stale:
                try:
                    _teardown_lock_dir(lock_dir, state_dir)
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for delegation store lock: {lock_dir}")
            time.sleep(0.02)

    try:
        yield
    finally:
        try:
            if owner_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                _teardown_lock_dir(lock_dir, state_dir)
        except OSError:
            pass


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Temp + fsync + rename + directory fsync."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _delegation_id(
    parent_task_id: str,
    parent_attempt_id: str,
    parent_generation: int,
    target_specialist: str,
    question: str,
    authority_hash: str,
) -> str:
    """Excludes timestamps; includes the authority hash, so a narrowed or
    widened authority for an otherwise-identical question cannot replay or
    collide with a prior sealed answer (the 1425 spec's idempotency-key
    rule, carried forward unchanged).

    Also includes ``parent_attempt_id`` and ``parent_generation``: without
    them, a checkpoint from a stale prior generation collides with an
    otherwise-identical request from a new generation, and the idempotency
    short-circuit in ``checkpoint()`` would silently return the OLD
    (possibly already-settled) record instead of treating the new
    generation's request as what it is — a genuinely new delegation. A
    real retry WITHIN the same attempt/generation still correctly hits the
    idempotent-return path; only a generation or attempt change now mints a
    distinct identity."""

    material = _canonical_json(
        {
            "parent_task_id": parent_task_id,
            "parent_attempt_id": parent_attempt_id,
            "parent_generation": parent_generation,
            "target_specialist": target_specialist,
            "question": question,
            "authority_sha256": authority_hash,
        }
    )
    return f"deleg-{_sha256_text(material)[:32]}"


class CoordinationStore:
    """SQLite-free, file-backed checkpoint store for one board/state root."""

    def __init__(
        self,
        state_dir: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.checkpoint_dir = self.state_dir / "delegation-checkpoints"
        self.clock = clock

    def _path(self, delegation_id: str) -> Path:
        """The single chokepoint every public method routes through for a
        caller-supplied ``delegation_id`` -- ``get``, ``dispatched``,
        ``inject_result``, ``cancel``, and ``_require`` all resolve their
        path here. Only the canonical ``deleg-[0-9a-f]{32}`` grammar this
        store itself generates (see ``_delegation_id``) is accepted; a
        caller-supplied ID containing ``/`` or ``..`` was previously an
        out-of-store path-traversal write primitive (``cancel('../../victim',
        ...)`` rewrote a file two levels outside ``delegation-checkpoints/``).
        Resolved-path containment is checked too, as defense in depth,
        though the grammar alone already excludes every character that
        could enable traversal or an absolute path."""

        if not isinstance(delegation_id, str) or not DELEGATION_ID_RE.fullmatch(delegation_id):
            raise DelegationDenied(f"invalid delegation id: {delegation_id!r}")
        candidate = self.checkpoint_dir / f"{delegation_id}.json"
        normalized_candidate = os.path.normpath(str(candidate))
        normalized_checkpoint_dir = os.path.normpath(str(self.checkpoint_dir))
        if os.path.commonpath((normalized_candidate, normalized_checkpoint_dir)) != normalized_checkpoint_dir:
            raise DelegationDenied(f"delegation id escapes the checkpoint store: {delegation_id!r}")
        return candidate

    def _root_ledger_path(self, originating_parent: str) -> Path:
        digest = _sha256_text(originating_parent)[:32]
        return self.state_dir / "delegation-root-ledgers" / f"root-{digest}.json"

    def _read_root_ledger(self, originating_parent: str) -> int:
        """The trusted, supervisor-owned counter for one lineage root, read
        under the store lock. Unlike ``DelegationLineage.total_delegations``
        (a pure function of one caller's own branch, unable to see sibling
        branches by construction), this file is written ONLY by this store,
        under the same lock that serializes every checkpoint() call, so it
        is the one place a GLOBAL, cross-sibling, cross-lane count can
        actually live."""

        try:
            text = self._root_ledger_path(originating_parent).read_text(encoding="utf-8")
        except FileNotFoundError:
            return 0
        payload = json.loads(text)
        value = payload["total_delegations_admitted"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DelegationDenied(
                f"corrupt trusted root delegation ledger for {originating_parent!r}: {value!r}"
            )
        return value

    def _write_root_ledger(self, originating_parent: str, total_delegations_admitted: int) -> None:
        _atomic_write_json(
            self._root_ledger_path(originating_parent),
            {
                "originating_parent": originating_parent,
                "total_delegations_admitted": total_delegations_admitted,
            },
        )

    def _trusted_root_identity(self, lineage: DelegationLineage, parent_task_id: str) -> str:
        """The global ledger key must never be taken verbatim from
        ``lineage.originating_parent`` -- untrusted, caller-suppliable data
        that round-trips through JSON across a checkpoint -> Chrono -> child
        task -> continuation envelope boundary. Rotating it while holding
        ``parent_task_id`` fixed was the round-2 REJECT probe: three sibling
        checkpoints from "the same parent task", each carrying a different
        forged ``originating_parent``, each selected a fresh ledger file.

        At the true root of a chain (``chain_depth == 0``), nothing has
        advanced yet, so the acting ``parent_task_id`` for THIS call is by
        definition the root -- the caller's claimed ``originating_parent``
        must equal it exactly, rather than being trusted as given.

        For a genuine continuation (``chain_depth > 0``), ``parent_task_id``
        is only the immediate hop's acting parent, not the tree root, so it
        cannot be substituted directly without reintroducing the original
        per-hop reset bug. Instead this exact (pre-advance) lineage must
        already have been produced and persisted by THIS store at an
        earlier hop -- proven via an exact ``lineage_sha256`` match against
        an existing checkpoint record -- which transitively proves its
        ``originating_parent`` was already validated against a real
        ``parent_task_id`` back when that earlier record was admitted.

        This does not authenticate ``parent_task_id`` itself (a caller
        claiming to *be* a particular acting task is a trust boundary this
        module has always deferred to its caller, e.g. the existing
        concurrency cap already trusts ``parent_task_id`` as given) -- it
        only closes the specific, demonstrated bypass of rotating the
        lineage root identity independently of the acting parent.
        """

        if lineage.chain_depth == 0:
            if lineage.originating_parent != parent_task_id:
                raise DelegationDenied(
                    "lineage forgery: a root-level lineage's originating_parent "
                    f"({lineage.originating_parent!r}) must equal the acting "
                    f"parent_task_id ({parent_task_id!r})"
                )
            return parent_task_id

        if not self._lineage_previously_admitted(lineage):
            raise DelegationDenied(
                "lineage forgery: a non-root lineage was presented that this "
                "store never advanced and persisted itself -- its "
                "originating_parent cannot be trusted"
            )
        return lineage.originating_parent

    def _lineage_previously_admitted(self, lineage: DelegationLineage) -> bool:
        target_hash = lineage_sha256(lineage)
        if not self.checkpoint_dir.is_dir():
            return False
        for path in self.checkpoint_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("lineage_sha256") == target_hash:
                return True
        return False

    def get(self, delegation_id: str) -> dict[str, Any] | None:
        try:
            return json.loads(self._path(delegation_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def checkpoint(
        self,
        *,
        parent_task_id: str,
        parent_attempt_id: str,
        parent_generation: int,
        requester_specialist: str,
        target_specialist: str,
        question: str,
        lineage: DelegationLineage,
        budget: LineageBudget,
        authority: DelegationAuthority,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Validate the delegation against the GLOBAL lineage cap, the
        concurrent-delegations-per-ACTING-PARENT cap, and the intersected
        authority BEFORE any file is written. A denied request leaves no
        trace on disk, so validation remains fail closed without persisting a
        partial checkpoint.

        The concurrency cap is scoped to ``parent_task_id`` (the immediate
        acting task making THIS delegation call), not
        ``lineage.originating_parent`` (the fixed root of the whole chain,
        used only for audit). Scoping it to the root would mean a child
        delegating further consumes its own ancestor's concurrency budget —
        wrong: "concurrent delegations: 1" means one acting task doesn't
        fan out to multiple simultaneous children, not that the whole tree
        may only ever have one outstanding delegation anywhere.

        The whole read-check-write sequence is lock-held so two concurrent
        calls that would both individually pass every check cannot jointly
        exceed a cap they'd each individually satisfy (a classic
        check-then-act race) — the same reason board_router.schedule()
        validates its whole active set inside one lock-held pass rather
        than checking each task independently."""

        if not isinstance(parent_generation, int) or isinstance(parent_generation, bool) or parent_generation <= 0:
            raise ValueError("parent_generation must be a positive integer")
        validated_ttl_seconds = _validate_ttl(ttl_seconds)
        authority.validate()
        authority_hash = authority_sha256(authority)
        delegation_id = _delegation_id(
            parent_task_id, parent_attempt_id, parent_generation, target_specialist, question, authority_hash
        )

        with _store_lock(self.state_dir):
            existing = self.get(delegation_id)
            if existing is not None:
                return existing

            in_flight = self._count_in_flight(parent_task_id)
            if in_flight >= budget.max_children_per_delegation:
                raise DelegationDenied(
                    "concurrency exceeded: "
                    f"{in_flight} delegation(s) already in flight for acting parent "
                    f"{parent_task_id!r} >= max_children_per_delegation="
                    f"{budget.max_children_per_delegation}"
                )

            # Resolve the GLOBAL ledger key to a value the caller cannot
            # rotate -- never lineage.originating_parent verbatim. See
            # _trusted_root_identity's docstring for the full argument.
            trusted_root = self._trusted_root_identity(lineage, parent_task_id)

            # Per-branch depth/cycle bound (unchanged) -- legitimately a
            # property of THIS branch's own path, not a global count.
            advanced = advance(lineage, target_specialist, budget)

            # The GLOBAL cap, enforced from trusted, supervisor-owned state:
            # never from lineage.total_delegations, which is a pure function
            # of the caller's own branch and structurally cannot see sibling
            # branches (the exact gap that let 3 siblings each independently
            # compute total_delegations=1 against a configured max of 2).
            # Reserve BEFORE persisting the checkpoint record: if the process
            # crashes between the two atomic writes below, the failure mode
            # is an under-counted (over-strict) budget, never a bypass.
            current_root_total = self._read_root_ledger(trusted_root)
            new_root_total = current_root_total + 1
            if new_root_total > budget.max_total_delegations:
                raise DelegationDenied(
                    "global budget exhausted (trusted ledger): "
                    f"root={trusted_root!r} admitted={current_root_total} "
                    f"would-become={new_root_total} > max_total_delegations={budget.max_total_delegations}"
                )

            now = self.clock()
            record: dict[str, Any] = {
                "schema": CHECKPOINT_SCHEMA,
                "delegation_id": delegation_id,
                "parent_task_id": parent_task_id,
                "parent_attempt_id": parent_attempt_id,
                "parent_generation": parent_generation,
                "requester_specialist": requester_specialist,
                "target_specialist": target_specialist,
                "question": question,
                "lineage": lineage_to_dict(advanced),
                "lineage_sha256": lineage_sha256(advanced),
                "authority": {
                    "read_paths": sorted(authority.read_paths),
                    "write_paths": sorted(authority.write_paths),
                    "external_targets": sorted(authority.external_targets),
                    "data_class": authority.data_class,
                    "resources": sorted(list(pair) for pair in authority.resources),
                },
                "authority_sha256": authority_hash,
                "state": "checkpointed",
                "result": None,
                "result_sha256": None,
                "created_at_epoch": now,
                "ttl_seconds": validated_ttl_seconds,
                "expires_at_epoch": now + validated_ttl_seconds,
                "cancel_reason": None,
                "root_admitted_total": new_root_total,
            }
            # Reservation before record, so a crash between the two writes
            # can only under-count remaining budget, never bypass it.
            self._write_root_ledger(trusted_root, new_root_total)
            _atomic_write_json(self._path(delegation_id), record)
            return record

    def _count_in_flight(self, parent_task_id: str) -> int:
        if not self.checkpoint_dir.is_dir():
            return 0
        count = 0
        for path in self.checkpoint_dir.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["state"] in NON_TERMINAL_STATES and record["parent_task_id"] == parent_task_id:
                count += 1
        return count

    def dispatched(self, delegation_id: str) -> dict[str, Any]:
        """Mark that Chrono has actually created the ordinary child task
        for this checkpoint. Idempotent past this point."""

        with _store_lock(self.state_dir):
            record = self._require(delegation_id)
            if record["state"] != "checkpointed":
                return record
            record = dict(record, state="dispatched")
            _atomic_write_json(self._path(delegation_id), record)
            return record

    def inject_result(
        self,
        delegation_id: str,
        *,
        parent_generation: int,
        result: dict[str, Any],
        result_sha256: str,
    ) -> dict[str, Any]:
        """The idempotent-injection + stale/duplicate-return fencing method.

        Re-injecting the identical settled result is a no-op. Injecting a
        DIFFERENT result for an already-settled identity, injecting after
        cancellation, injecting after TTL expiry, injecting before dispatch,
        a parent-generation mismatch, or a claimed hash that does not match
        the real canonical hash of ``result`` are all fenced (raised), never
        silently accepted — "Continuation binding: original lead accepts
        only a child result matching delegation ID, request hash, and
        parent generation."
        """

        with _store_lock(self.state_dir):
            record = self._require(delegation_id)
            if record["parent_generation"] != parent_generation:
                raise DelegationDenied(
                    f"parent generation mismatch: checkpoint={record['parent_generation']} "
                    f"result={parent_generation} (stale return)"
                )
            if record["state"] == "settled":
                if record["result_sha256"] == result_sha256:
                    return record
                raise DelegationDenied(
                    f"duplicate/stale return: {delegation_id} is already settled with a different result"
                )
            if record["state"] in ("cancelled", "stale"):
                raise DelegationDenied(f"cannot inject result into a {record['state']} checkpoint")
            if record["state"] != "dispatched":
                raise DelegationDenied(
                    f"cannot settle before dispatch: {delegation_id} is in state "
                    f"{record['state']!r}, expected 'dispatched'"
                )

            now = self.clock()
            if now >= record["expires_at_epoch"]:
                expired = dict(record, state="stale")
                _atomic_write_json(self._path(delegation_id), expired)
                raise DelegationDenied(f"checkpoint expired at {record['expires_at_epoch']} (late return fenced)")

            # Independently verify the claimed hash against the real
            # canonical hash of the result payload -- never trust a
            # caller-supplied digest verbatim (the exact gap that let a
            # checkpoint settle with the literal string "false" as its
            # "hash").
            actual_sha256 = _sha256_text(_canonical_json(result))
            if not hmac.compare_digest(actual_sha256, str(result_sha256)):
                raise DelegationDenied(
                    f"result hash mismatch for {delegation_id}: "
                    f"claimed={result_sha256!r} actual={actual_sha256!r}"
                )

            record = dict(record, state="settled", result=result, result_sha256=result_sha256)
            _atomic_write_json(self._path(delegation_id), record)
            return record

    def cancel(self, delegation_id: str, reason: str) -> dict[str, Any]:
        with _store_lock(self.state_dir):
            record = self._require(delegation_id)
            if record["state"] in TERMINAL_STATES:
                return record
            record = dict(record, state="cancelled", cancel_reason=reason)
            _atomic_write_json(self._path(delegation_id), record)
            return record

    def sweep_expired(self, now: float | None = None) -> list[dict[str, Any]]:
        """Library-only TTL sweep; no production loop invokes it automatically."""

        moment = now if now is not None else self.clock()
        expired: list[dict[str, Any]] = []
        if not self.checkpoint_dir.is_dir():
            return expired
        with _store_lock(self.state_dir):
            for path in sorted(self.checkpoint_dir.glob("*.json")):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record["state"] not in NON_TERMINAL_STATES:
                    continue
                if moment >= record["expires_at_epoch"]:
                    record = dict(record, state="stale")
                    _atomic_write_json(path, record)
                    expired.append(record)
        return expired

    def _require(self, delegation_id: str) -> dict[str, Any]:
        record = self.get(delegation_id)
        if record is None:
            raise DelegationDenied(f"unknown delegation: {delegation_id}")
        return record


def delegation_board_task(checkpoint: dict[str, Any]):
    """Build a validation-only BoardTask for a manually authored child.

    This helper has test callers only. Chrono still authors and sends the
    ordinary child packet; this function neither schedules nor dispatches it.
    """

    import board_router as br

    authority = checkpoint["authority"]
    resources = tuple(
        br.ResourceClaim(resource_class=pair[0], target=pair[1], mode="read")
        for pair in authority["resources"]
    )
    return br.BoardTask(
        task_id=checkpoint["delegation_id"],
        write_paths=(),  # V1 delegation is always read-only.
        read_paths=tuple(authority["read_paths"]),
        resources=resources,
        metadata_complete=True,
    )
