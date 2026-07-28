#!/usr/bin/env python3
"""V2 board router — the parallel-safety scheduler.

Pure logic. Given a set of ready task descriptors, decide which may run
concurrently without colliding on files, dependency order, or shared runtime
resources. The conservative default is to serialize: anything that cannot be
*proven* safe to parallelize waits.

Three independent conflict axes (all must be clear to co-run):

1. Files — canonical realpath disjointness. String inequality is NOT
   disjointness: we resolve ``..``/``.``, symlinks, case (on case-insensitive
   volumes), hardlink aliases (``st_dev``/``st_ino``), and parent/child
   containment, and we distinguish read vs write access (read/read is safe).
2. Dependencies — a direct or transitive ``depends_on`` edge in either
   direction serializes; and at schedule time a task is admissible only when
   every predecessor has SETTLED at the exact ``(generation, artifact_sha256)``
   the packet declared. Resource locks do NOT substitute for these edges.
3. Shared resources — a typed inventory (registry, vault internals, git
   refs/config/hooks/remotes/integration branches, outbox/reconciler, board and
   queue/claim/attempt/generation ledgers, MCP state, browser profiles,
   ports/daemons, caches, credential brokers, provider quotas/budgets,
   tmux/status/temp) guarded by a lock table. Pairwise checks miss cumulative
   (three-way) capacity conflicts, so ``schedule`` acquires the whole active
   set's locks in a canonical order with all-or-nothing rollback.

Missing or ambiguous metadata always serializes.

The LOGICAL concurrency bound is enforced here; the PHYSICAL host admission
(RSS/swap/pressure) is Task 1.2's ``host_admission.under_admission`` and is
delegated through the ``admission_gate`` seam — it is not reimplemented.
Production calls fail closed when that gate is absent, errors, or returns a
non-boolean result; pure-logic use requires an explicit ``logical_only`` opt-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from typing import Callable, Iterable, Mapping, Sequence

try:  # interface reference only; the supervisor supplies the real gate.
    from host_admission import under_admission as _under_admission  # noqa: F401

    _HOST_ADMISSION_AVAILABLE = True
except Exception:  # pragma: no cover - board_router never requires it at import
    _HOST_ADMISSION_AVAILABLE = False


__all__ = [
    "DepEdge",
    "ResourceClaim",
    "BoardTask",
    "TaskReservation",
    "ReservationRelease",
    "ScheduleResult",
    "DependencyIndex",
    "build_dependency_index",
    "is_ambiguous",
    "files_conflict",
    "can_parallelize",
    "schedule",
    "KNOWN_RESOURCE_CLASSES",
]


# The full typed shared-resource inventory (rev-2 review §3). Anything a task
# declares that is NOT in this set is ambiguous and forces serialization.
KNOWN_RESOURCE_CLASSES = frozenset(
    {
        "task_registry",
        "vault_db",
        "vault_index",
        "vault_compaction",
        "git_refs",
        "git_config",
        "git_hooks",
        "git_remotes",
        "integration_branch",
        "outbox",
        "reconciler",
        "board_state",
        "queue_ledger",
        "claim_ledger",
        "attempt_ledger",
        "generation_ledger",
        "mcp_server",
        "browser_profile",
        "port",
        "daemon",
        "cache",
        "credential_broker",
        "provider_quota",
        "tmux",
        "status_line",
        "temp",
    }
)

_VALID_MODES = frozenset({"read", "write", "count"})


@dataclass(frozen=True)
class DepEdge:
    """A prerequisite bound to the exact settled generation and artifact hash."""

    task_id: str
    generation: int
    artifact_sha256: str


@dataclass(frozen=True)
class ResourceClaim:
    """A typed claim on one shared runtime resource."""

    resource_class: str
    target: str = ""
    mode: str = "write"  # read | write | count
    units: int = 1  # only meaningful for count mode


@dataclass(frozen=True)
class BoardTask:
    task_id: str
    write_paths: tuple[str, ...] = ()
    read_paths: tuple[str, ...] = ()
    depends_on: tuple[DepEdge, ...] = ()
    resources: tuple[ResourceClaim, ...] = ()
    worktree_root: str = ""
    metadata_complete: bool = False
    priority: int = 0


@dataclass(frozen=True)
class TaskReservation:
    """Deterministic active-task reservation for atomic board persistence."""

    task_id: str
    token: str
    task: BoardTask = field(repr=False)


@dataclass(frozen=True)
class ReservationRelease:
    """An authoritative board transition that releases one reservation."""

    token: str
    outcome: str  # settled | cancelled


@dataclass(frozen=True)
class ScheduleResult:
    run_now: tuple[str, ...]
    must_wait: tuple[str, ...]
    reasons: dict[str, str] = field(default_factory=dict)
    reservations: tuple[TaskReservation, ...] = ()
    reservation_snapshot_sha256: str = ""


# --------------------------------------------------------------------------- #
# Canonical path handling
# --------------------------------------------------------------------------- #
def _canonical_path(path: str, worktree_root: str = "") -> tuple[str, tuple[int, int] | None]:
    """Return a comparison key (realpath, case-folded) and inode identity."""

    rooted = path if os.path.isabs(path) else os.path.join(worktree_root, path)
    real = os.path.realpath(rooted)  # resolves symlinks, .. and .
    key = os.path.normcase(real).casefold()  # conservative on case-folding volumes
    try:
        stat_result = os.stat(real)
        identity: tuple[int, int] | None = (stat_result.st_dev, stat_result.st_ino)
    except OSError:
        identity = None  # not-yet-created scope paths compare by canonical string
    return key, identity


def _is_ancestor(ancestor_key: str, descendant_key: str) -> bool:
    if ancestor_key == descendant_key:
        return False
    prefix = ancestor_key.rstrip("/")
    return descendant_key.startswith(prefix + "/")


def _paths_alias(task_a: BoardTask, path_a: str, task_b: BoardTask, path_b: str) -> bool:
    key_a, ident_a = _canonical_path(path_a, task_a.worktree_root)
    key_b, ident_b = _canonical_path(path_b, task_b.worktree_root)
    if ident_a is not None and ident_a == ident_b:
        return True  # hardlink / same inode under different names
    if key_a == key_b:
        return True
    return _is_ancestor(key_a, key_b) or _is_ancestor(key_b, key_a)


def _claims(task: BoardTask) -> tuple[tuple[str, str], ...]:
    return tuple((p, "write") for p in task.write_paths) + tuple(
        (p, "read") for p in task.read_paths
    )


def files_conflict(task_a: BoardTask, task_b: BoardTask) -> bool:
    """True if the two tasks' file scopes alias with at least one writer."""

    for path_a, mode_a in _claims(task_a):
        for path_b, mode_b in _claims(task_b):
            if mode_a == "read" and mode_b == "read":
                continue  # concurrent reads of the same object are safe
            if _paths_alias(task_a, path_a, task_b, path_b):
                return True
    return False


# --------------------------------------------------------------------------- #
# Metadata completeness
# --------------------------------------------------------------------------- #
def is_ambiguous(task: BoardTask) -> bool:
    """Conservative: any incomplete/unrecognized metadata forces serialization."""

    if not isinstance(task.task_id, str) or not task.task_id:
        return True
    if not isinstance(task.metadata_complete, bool) or not task.metadata_complete:
        return True
    if isinstance(task.priority, bool) or not isinstance(task.priority, int):
        return True
    if not isinstance(task.worktree_root, str) or "\x00" in task.worktree_root:
        return True
    if task.worktree_root and not os.path.isabs(task.worktree_root):
        return True
    for path in (*task.write_paths, *task.read_paths):
        if not isinstance(path, str) or not path or "\x00" in path:
            return True
        if not os.path.isabs(path) and not task.worktree_root:
            return True
    for claim in task.resources:
        if not isinstance(claim, ResourceClaim):
            return True
        if not isinstance(claim.resource_class, str):
            return True
        if claim.resource_class not in KNOWN_RESOURCE_CLASSES:
            return True
        if not isinstance(claim.target, str) or claim.target != claim.target.strip():
            return True
        if not isinstance(claim.mode, str):
            return True
        if claim.mode not in _VALID_MODES:
            return True
        if isinstance(claim.units, bool) or not isinstance(claim.units, int) or claim.units <= 0:
            return True
    return False


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
def _direct_dep(task_a: BoardTask, task_b: BoardTask) -> bool:
    if any(edge.task_id == task_b.task_id for edge in task_a.depends_on):
        return True
    return any(edge.task_id == task_a.task_id for edge in task_b.depends_on)


class DependencyIndex:
    """Transitive reachability over ``depends_on`` edges."""

    def __init__(self, adjacency: Mapping[str, frozenset[str]]) -> None:
        self._adjacency = {node: frozenset(edges) for node, edges in adjacency.items()}

    def reachable(self, source: str, target: str) -> bool:
        """True if ``source`` transitively depends on ``target``."""

        seen: set[str] = set()
        stack = list(self._adjacency.get(source, ()))
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self._adjacency.get(node, ()))
        return False

    def depends_either(self, task_a: str, task_b: str) -> bool:
        return self.reachable(task_a, task_b) or self.reachable(task_b, task_a)


def build_dependency_index(tasks: Iterable[BoardTask]) -> DependencyIndex:
    adjacency: dict[str, frozenset[str]] = {}
    for task in tasks:
        adjacency[task.task_id] = frozenset(edge.task_id for edge in task.depends_on)
    return DependencyIndex(adjacency)


# --------------------------------------------------------------------------- #
# Shared-resource pairwise + cumulative locking
# --------------------------------------------------------------------------- #
def _capacities_valid(capacities: Mapping[object, int]) -> bool:
    for key, capacity in capacities.items():
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            return False
        if isinstance(key, str):
            if key not in KNOWN_RESOURCE_CLASSES:
                return False
            continue
        if not (
            isinstance(key, tuple)
            and len(key) == 2
            and isinstance(key[0], str)
            and key[0] in KNOWN_RESOURCE_CLASSES
            and isinstance(key[1], str)
            and key[1] == key[1].strip()
        ):
            return False
    return True


def _capacity(capacities: Mapping[object, int], resource_class: str, target: str) -> int:
    if (resource_class, target) in capacities:
        return capacities[(resource_class, target)]
    if resource_class in capacities:
        return capacities[resource_class]
    return 1  # conservative default: exclusive


def _resource_conflict_pairwise(
    task_a: BoardTask, task_b: BoardTask, capacities: Mapping[object, int]
) -> bool:
    for claim_a in task_a.resources:
        for claim_b in task_b.resources:
            if (claim_a.resource_class, claim_a.target) != (
                claim_b.resource_class,
                claim_b.target,
            ):
                continue
            if claim_a.mode == "read" and claim_b.mode == "read":
                continue
            if claim_a.mode == "count" and claim_b.mode == "count":
                capacity = _capacity(capacities, claim_a.resource_class, claim_a.target)
                if claim_a.units + claim_b.units > capacity:
                    return True
                continue
            return True  # any writer, or mixed modes on the same resource
    return False


class _LockTable:
    """All-or-nothing, canonically ordered acquisition with rollback."""

    def __init__(self, capacities: Mapping[object, int]) -> None:
        self._capacities = capacities
        self._state: dict[tuple[str, str], dict[str, object]] = {}

    def try_acquire(self, task: BoardTask) -> bool:
        ordered = sorted(
            task.resources, key=lambda claim: (claim.resource_class, claim.target, claim.mode)
        )
        held: list[ResourceClaim] = []
        for claim in ordered:
            if self._grant(claim):
                held.append(claim)
            else:
                for previous in reversed(held):
                    self._release(previous)
                return False  # rolled back: no half-held locks
        return True

    def _grant(self, claim: ResourceClaim) -> bool:
        key = (claim.resource_class, claim.target)
        state = self._state.get(key)
        if claim.mode == "write":
            if state is not None and int(state["count"]) > 0:
                return False
            self._state[key] = {"mode": "write", "count": 1, "units": 1}
            return True
        if claim.mode == "read":
            if state is None:
                self._state[key] = {"mode": "read", "count": 1, "units": 0}
                return True
            if state["mode"] != "read":
                return False
            state["count"] = int(state["count"]) + 1
            return True
        # count
        capacity = _capacity(self._capacities, claim.resource_class, claim.target)
        if state is None:
            if claim.units > capacity:
                return False
            self._state[key] = {"mode": "count", "count": 1, "units": claim.units}
            return True
        if state["mode"] != "count":
            return False
        if int(state["units"]) + claim.units > capacity:
            return False
        state["units"] = int(state["units"]) + claim.units
        state["count"] = int(state["count"]) + 1
        return True

    def _release(self, claim: ResourceClaim) -> None:
        key = (claim.resource_class, claim.target)
        state = self._state.get(key)
        if state is None:
            return
        if claim.mode == "count":
            state["units"] = int(state["units"]) - claim.units
        state["count"] = int(state["count"]) - 1
        if int(state["count"]) <= 0:
            self._state.pop(key, None)


# --------------------------------------------------------------------------- #
# Pairwise predicate + whole-set scheduler
# --------------------------------------------------------------------------- #
def _conflict_reason(
    task_a: BoardTask,
    task_b: BoardTask,
    dependency_index: DependencyIndex | None,
    capacities: Mapping[object, int],
) -> str | None:
    if task_a.task_id == task_b.task_id:
        return f"duplicate task identity: {task_a.task_id}"
    if is_ambiguous(task_a) or is_ambiguous(task_b):
        return "ambiguous or missing metadata (serialized)"
    if _direct_dep(task_a, task_b) or (
        dependency_index is not None
        and dependency_index.depends_either(task_a.task_id, task_b.task_id)
    ):
        return f"dependency edge with {task_b.task_id}"
    if files_conflict(task_a, task_b):
        return f"write-scope collision with {task_b.task_id}"
    if _resource_conflict_pairwise(task_a, task_b, capacities):
        return f"shared-resource conflict with {task_b.task_id}"
    return None


def can_parallelize(
    task_a: BoardTask,
    task_b: BoardTask,
    *,
    dependency_index: DependencyIndex | None = None,
    capacities: Mapping[object, int] | None = None,
) -> bool:
    """Pairwise parallel-safety. Note: cumulative (>2-way) resource capacity is
    only decided by ``schedule``; this returns whether *these two* may co-run."""

    capacities = capacities or {}
    if not _capacities_valid(capacities):
        return False
    return _conflict_reason(task_a, task_b, dependency_index, capacities) is None


def _reservation_for(task: BoardTask) -> TaskReservation:
    material = {
        "depends_on": [
            [edge.task_id, edge.generation, edge.artifact_sha256] for edge in task.depends_on
        ],
        "metadata_complete": task.metadata_complete,
        "priority": task.priority,
        "read_paths": list(task.read_paths),
        "resources": [
            [claim.resource_class, claim.target, claim.mode, claim.units]
            for claim in task.resources
        ],
        "task_id": task.task_id,
        "worktree_root": task.worktree_root,
        "write_paths": list(task.write_paths),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return TaskReservation(
        task_id=task.task_id,
        token=f"resv-{hashlib.sha256(encoded).hexdigest()}",
        task=task,
    )


def _reservation_snapshot_sha256(reservations: Sequence[TaskReservation]) -> str:
    encoded = json.dumps(
        [[reservation.task_id, reservation.token] for reservation in reservations],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def schedule(
    ready_tasks: Sequence[BoardTask],
    *,
    concurrency: int,
    active_reservations: Sequence[TaskReservation] = (),
    active_snapshot_sha256: str | None = None,
    release_events: Sequence[ReservationRelease] = (),
    settled: Mapping[str, tuple[int, str]] | None = None,
    capacities: Mapping[object, int] | None = None,
    admission_gate: Callable[[tuple[BoardTask, ...]], bool] | None = None,
    logical_only: bool = False,
) -> ScheduleResult:
    """Return one atomic scheduling round plus the resulting reservation snapshot.

    ``settled`` maps a task id to its settled ``(generation, artifact_sha256)``.
    ``active_reservations`` plus ``active_snapshot_sha256`` must be the complete
    persisted snapshot returned by the prior round. Reservations remain active
    unless a matching ``ReservationRelease`` records a ``settled`` or ``cancelled``
    transition. ``admission_gate`` is the Task 1.2 seam and receives active plus
    newly admitted work. Production scheduling fails closed without an exact
    boolean result; pure-logic callers must explicitly use ``logical_only=True``.
    """

    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency <= 0:
        raise ValueError("concurrency must be a positive integer")
    if not isinstance(logical_only, bool):
        raise ValueError("logical_only must be a boolean")
    if logical_only and admission_gate is not None:
        raise ValueError("logical_only cannot bypass a supplied admission gate")
    ready_tasks = tuple(ready_tasks)
    supplied_reservations = tuple(active_reservations)
    for reservation in supplied_reservations:
        if not isinstance(reservation, TaskReservation):
            raise ValueError("active snapshot entries must be TaskReservation values")
        if reservation != _reservation_for(reservation.task):
            raise ValueError("active reservation token or task snapshot is invalid")
    supplied_reservations = tuple(
        sorted(supplied_reservations, key=lambda reservation: reservation.task_id)
    )
    expected_snapshot_sha256 = _reservation_snapshot_sha256(supplied_reservations)
    if supplied_reservations and active_snapshot_sha256 is None:
        raise ValueError("active reservation snapshot hash is required")
    if active_snapshot_sha256 is not None and active_snapshot_sha256 != expected_snapshot_sha256:
        raise ValueError("active reservation snapshot hash mismatch")

    releases: dict[str, str] = {}
    for event in release_events:
        if not isinstance(event, ReservationRelease):
            raise ValueError("release events must be ReservationRelease values")
        if not isinstance(event.token, str) or event.outcome not in {"settled", "cancelled"}:
            raise ValueError("reservation release must be settled or cancelled")
        if event.token in releases:
            raise ValueError("duplicate reservation release token")
        releases[event.token] = event.outcome
    known_tokens = {reservation.token for reservation in supplied_reservations}
    if not set(releases).issubset(known_tokens):
        raise ValueError("reservation release token is not active")

    active_tasks = tuple(
        reservation.task
        for reservation in supplied_reservations
        if reservation.token not in releases
    )
    for task in (*active_tasks, *ready_tasks):
        if not isinstance(task, BoardTask):
            raise ValueError("schedule entries must be BoardTask values")
        if not isinstance(task.task_id, str) or not task.task_id:
            raise ValueError("task id must be a non-empty string")
    settled = dict(settled or {})
    capacities = dict(capacities or {})
    if not _capacities_valid(capacities):
        raise ValueError("capacities must use validated resource keys and positive integers")
    reasons: dict[str, str] = {}
    for task in active_tasks:
        if is_ambiguous(task):
            raise ValueError(f"active task metadata is ambiguous: {task.task_id}")
    active = tuple(sorted(active_tasks, key=lambda task: (task.priority, task.task_id)))
    if len({task.task_id for task in active}) != len(active):
        raise ValueError("active reservation snapshot contains duplicate task ids")
    duplicate_ready_ids: set[str] = set()
    seen_ids = {task.task_id for task in active}
    for task in ready_tasks:
        if task.task_id in seen_ids:
            duplicate_ready_ids.add(task.task_id)
        seen_ids.add(task.task_id)
    dependency_index = build_dependency_index((*active, *ready_tasks))

    # Validate the persisted active snapshot before it can authorize new work.
    lock = _LockTable(capacities)
    validated_active: list[BoardTask] = []
    for task in active:
        for other in validated_active:
            conflict = _conflict_reason(task, other, dependency_index, capacities)
            if conflict is not None:
                raise ValueError(f"active reservation snapshot conflicts: {conflict}")
        if not lock.try_acquire(task):
            raise ValueError("active reservation snapshot exceeds resource capacity")
        validated_active.append(task)

    # 1. Runnability: every declared predecessor must be settled at the exact
    #    generation and artifact hash. An unsettled predecessor (including another
    #    ready task) or a generation/hash mismatch defers the task. This cascade
    #    is what serializes transitive dependency chains.
    runnable: list[BoardTask] = []
    for task in ready_tasks:
        if task.task_id in duplicate_ready_ids:
            reasons[task.task_id] = "duplicate task identity (deferred)"
            continue
        if is_ambiguous(task):
            reasons[task.task_id] = "ambiguous or missing metadata (deferred)"
            continue
        unmet: DepEdge | None = None
        for edge in task.depends_on:
            if settled.get(edge.task_id) != (edge.generation, edge.artifact_sha256):
                unmet = edge
                break
        if unmet is not None:
            reasons[task.task_id] = (
                f"unmet dependency: {unmet.task_id}@gen{unmet.generation}"
            )
        else:
            runnable.append(task)

    # 2. Deterministic order, independent of input order.
    runnable.sort(key=lambda task: (task.priority, task.task_id))

    # 3. Whole-active-set admission with atomic, canonically ordered locking.
    admitted: list[BoardTask] = []
    for task in runnable:
        if len(active) + len(admitted) >= concurrency:
            reasons.setdefault(task.task_id, "concurrency bound reached")
            continue
        conflict: str | None = None
        for other in (*active, *admitted):
            conflict = _conflict_reason(task, other, dependency_index, capacities)
            if conflict is not None:
                break
        if conflict is None and not lock.try_acquire(task):
            conflict = "shared-resource lock unavailable"
        if conflict is None:
            admitted.append(task)
        else:
            reasons.setdefault(task.task_id, conflict)

    # 4. Task 1.2 gates active plus proposed work. Missing, failing, or non-bool
    #    gates fail closed; logical-only operation requires an explicit opt-in.
    if admitted and not logical_only:
        gate_ok = False
        if callable(admission_gate):
            try:
                gate_result = admission_gate(tuple((*active, *admitted)))
            except Exception:
                gate_result = False
            gate_ok = isinstance(gate_result, bool) and gate_result
        if not gate_ok:
            for task in admitted:
                reasons[task.task_id] = "host admission unavailable or deferred (Task 1.2)"
            admitted = []

    run_ids = tuple(task.task_id for task in admitted)
    run_set = set(run_ids)
    must_wait = tuple(task.task_id for task in ready_tasks if task.task_id not in run_set)
    reserved_tasks = sorted((*active, *admitted), key=lambda task: task.task_id)
    reservations = tuple(_reservation_for(task) for task in reserved_tasks)
    return ScheduleResult(
        run_now=run_ids,
        must_wait=must_wait,
        reasons=reasons,
        reservations=reservations,
        reservation_snapshot_sha256=_reservation_snapshot_sha256(reservations),
    )
