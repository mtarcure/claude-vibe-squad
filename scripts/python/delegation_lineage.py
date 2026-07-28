#!/usr/bin/env python3
"""Global delegation-lineage cap and authority intersection (V2 Task 2.4, F5).

This closes the exact gap found in the cross-family review of the
specialist-delegation/v1 spec (held TASK-2026-07-21-1425, settled
APPROVE-WITH-CHANGES by TASK-2026-07-21-1445): the spec's per-parent
``<=3 delegations`` cap resets on every cross-lane hop, because each hop is
dispatched as an ordinary fresh task with its own budget and cycle-ledger.
A chain P -> T1 -> T2 -> ... can fan out unboundedly even though every
individual hop stays inside its own local cap.

The fix is a ``DelegationLineage`` value that is carried, unmodified except
by ``advance()``, across every hop of a delegation chain (same-lane and
cross-lane alike, per the drop-subagents advisory's uniform board-routing
replacement). ``chain_depth`` and ``visited_specialists`` bound recursion and
cycles; ``total_delegations`` is the GLOBAL replacement for the old
per-parent counter, so it keeps accumulating no matter how many acting
parents the chain passes through. The lineage is plain, hashable data with
no side effects, so it round-trips through JSON exactly as it will round
-trip through a checkpoint -> Chrono -> child task -> continuation envelope.

Authority intersection lives here too, not in ``coordination.py``, because
it is the same class of "a delegate can never exceed its parent" safety
math as the lineage cap, and both must be pure and independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Mapping


class DelegationDenied(RuntimeError):
    """A delegation admission or authority check failed closed."""


@dataclass(frozen=True)
class LineageBudget:
    """Caller-suppliable caps. Sol's conservative V1 defaults."""

    max_depth: int = 1
    max_children_per_delegation: int = 1
    max_total_delegations: int = 3

    def validate(self) -> None:
        for name in ("max_depth", "max_children_per_delegation", "max_total_delegations"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class DelegationLineage:
    """Carried, unmodified except by advance(), across every hop of a chain."""

    originating_parent: str
    chain_depth: int
    visited_specialists: tuple[str, ...]
    total_delegations: int


def root_lineage(originating_parent: str, requester_specialist: str) -> DelegationLineage:
    """Seed a lineage at the root of a delegation chain.

    The requester is included in ``visited_specialists`` from the start,
    which closes the "chain loops back to its own originator" cycle case
    for free — the very first ``advance()`` already treats the root
    specialist as visited.
    """

    if not isinstance(originating_parent, str) or not originating_parent:
        raise ValueError("originating_parent must be a non-empty string")
    if not isinstance(requester_specialist, str) or not requester_specialist:
        raise ValueError("requester_specialist must be a non-empty string")
    return DelegationLineage(
        originating_parent=originating_parent,
        chain_depth=0,
        visited_specialists=(requester_specialist,),
        total_delegations=0,
    )


def advance(
    lineage: DelegationLineage,
    target_specialist: str,
    budget: LineageBudget,
) -> DelegationLineage:
    """Admit one more hop, or fail closed with a typed reason.

    This is the global cap: ``total_delegations`` and ``visited_specialists``
    are read from the SAME lineage object the caller carried in from the
    prior hop (however many process/lane boundaries it crossed), never from
    a fresh local counter. A caller that constructs a brand-new
    ``root_lineage`` to dodge this is not "advancing" a chain at all — it is
    starting an unrelated one, which is a caller-discipline concern outside
    this module's pure-function boundary.
    """

    budget.validate()
    if not isinstance(target_specialist, str) or not target_specialist:
        raise ValueError("target_specialist must be a non-empty string")
    if lineage.chain_depth >= budget.max_depth:
        raise DelegationDenied(
            f"depth exceeded: chain_depth={lineage.chain_depth} >= max_depth={budget.max_depth}"
        )
    if target_specialist in lineage.visited_specialists:
        raise DelegationDenied(f"cycle: {target_specialist!r} already visited in this lineage")
    if lineage.total_delegations >= budget.max_total_delegations:
        raise DelegationDenied(
            "budget exhausted: total_delegations="
            f"{lineage.total_delegations} >= max_total_delegations={budget.max_total_delegations}"
        )
    return DelegationLineage(
        originating_parent=lineage.originating_parent,
        chain_depth=lineage.chain_depth + 1,
        visited_specialists=(*lineage.visited_specialists, target_specialist),
        total_delegations=lineage.total_delegations + 1,
    )


def lineage_to_dict(lineage: DelegationLineage) -> dict[str, object]:
    return {
        "originating_parent": lineage.originating_parent,
        "chain_depth": lineage.chain_depth,
        "visited_specialists": list(lineage.visited_specialists),
        "total_delegations": lineage.total_delegations,
    }


def lineage_from_dict(value: Mapping[str, object]) -> DelegationLineage:
    """Strict validation, not mere coercion: this is the boundary a carried
    lineage crosses back into the process (a JSON round-trip through a
    checkpoint -> Chrono -> child task -> continuation envelope), so it must
    reject a forged/malformed value rather than silently coerce it into
    something ``advance()`` would then trust. Every check here enforces an
    invariant that anything actually produced by ``root_lineage()`` and
    ``advance()`` always satisfies by construction: non-negative counters,
    non-empty string fields, no duplicate visited specialists, and
    ``chain_depth == len(visited_specialists) - 1 == total_delegations``
    (root seeds one visited entry at depth/total 0; every ``advance()``
    appends exactly one visited entry and increments both counters by
    exactly one, in lockstep, every single hop)."""

    try:
        originating_parent = value["originating_parent"]
        if not isinstance(originating_parent, str) or not originating_parent:
            raise ValueError("originating_parent must be a non-empty string")

        chain_depth = value["chain_depth"]
        if isinstance(chain_depth, bool) or not isinstance(chain_depth, int):
            raise ValueError("chain_depth must be an integer")
        if chain_depth < 0:
            raise ValueError("chain_depth must be non-negative")

        total_delegations = value["total_delegations"]
        if isinstance(total_delegations, bool) or not isinstance(total_delegations, int):
            raise ValueError("total_delegations must be an integer")
        if total_delegations < 0:
            raise ValueError("total_delegations must be non-negative")

        visited_raw = value["visited_specialists"]
        if not isinstance(visited_raw, (list, tuple)):
            raise ValueError("visited_specialists must be a list")
        if not all(isinstance(item, str) and item for item in visited_raw):
            raise ValueError("visited_specialists entries must be non-empty strings")
        visited_specialists = tuple(str(item) for item in visited_raw)
        if len(set(visited_specialists)) != len(visited_specialists):
            raise ValueError("visited_specialists must not contain duplicates")

        if chain_depth != len(visited_specialists) - 1:
            raise ValueError("chain_depth is inconsistent with visited_specialists length")
        if total_delegations != chain_depth:
            raise ValueError("total_delegations is inconsistent with chain_depth")

        return DelegationLineage(
            originating_parent=originating_parent,
            chain_depth=chain_depth,
            visited_specialists=visited_specialists,
            total_delegations=total_delegations,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DelegationDenied(f"malformed lineage: {exc}") from exc


def lineage_sha256(lineage: DelegationLineage) -> str:
    """Corruption/tamper detection, not an authentication primitive — the
    same disclosed trust boundary as board_router.py's reservation tokens:
    this proves the lineage a caller hands back is self-consistent with
    what was last persisted, not that the caller is who it claims to be."""

    encoded = json.dumps(lineage_to_dict(lineage), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_DATA_CLASS_RANK = {"public": 0, "internal": 1, "restricted": 2}


@dataclass(frozen=True)
class DelegationAuthority:
    """The 1425 spec's ``scope`` object, made a first-class intersectable
    value. ``resources`` mirrors board_router.ResourceClaim's
    ``(resource_class, target)`` shape deliberately, for vocabulary
    consistency with the settled Task 2.1 scheduler this module feeds."""

    read_paths: frozenset[str] = field(default_factory=frozenset)
    write_paths: frozenset[str] = field(default_factory=frozenset)
    external_targets: frozenset[str] = field(default_factory=frozenset)
    data_class: str = "internal"
    resources: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def validate(self) -> None:
        if self.data_class not in _DATA_CLASS_RANK:
            raise ValueError(f"unknown data_class: {self.data_class!r}")


def intersect_authority(
    parent: DelegationAuthority,
    requester: DelegationAuthority,
    requested_scope: DelegationAuthority,
    target_safety_policy: DelegationAuthority,
) -> DelegationAuthority:
    """``effective_resource_authority = parent ∩ requester ∩ scope ∩ target_policy``.

    An intersection can only shrink: there is no operator here that adds a
    resource, so escalation beyond any single input is structurally
    impossible by construction, matching the 1425 spec's authority model
    exactly. ``write_paths`` is unconditionally forced empty regardless of
    what any input claims — V1 delegation is read-only, full stop, not
    merely "read-only if every input happens to agree."
    """

    for authority in (parent, requester, requested_scope, target_safety_policy):
        authority.validate()
    return DelegationAuthority(
        read_paths=parent.read_paths & requester.read_paths & requested_scope.read_paths & target_safety_policy.read_paths,
        write_paths=frozenset(),
        external_targets=parent.external_targets & requester.external_targets & requested_scope.external_targets & target_safety_policy.external_targets,
        data_class=min(
            (parent.data_class, requester.data_class, requested_scope.data_class, target_safety_policy.data_class),
            key=lambda value: _DATA_CLASS_RANK[value],
        ),
        resources=parent.resources & requester.resources & requested_scope.resources & target_safety_policy.resources,
    )


def authority_to_dict(authority: DelegationAuthority) -> dict[str, object]:
    return {
        "read_paths": sorted(authority.read_paths),
        "write_paths": sorted(authority.write_paths),
        "external_targets": sorted(authority.external_targets),
        "data_class": authority.data_class,
        "resources": sorted(list(pair) for pair in authority.resources),
    }


def authority_sha256(authority: DelegationAuthority) -> str:
    encoded = json.dumps(authority_to_dict(authority), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
