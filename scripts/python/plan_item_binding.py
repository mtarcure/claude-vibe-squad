#!/usr/bin/env python3
"""Bind a closed board task to the plan items it closes.

Three ledger items shipped on 2026-08-11 and the plan sat unchanged all day,
because nothing connected a closed task to a plan item. This module is the
consumption half of that link. The declaration half is an explicit optional
``plan_item_ids`` field, or a canonical detailed ``phase`` fallback when that field
is absent. ``bin/send-task.sh`` writes the result into the board dispatch descriptor;
``board_process_truth.finalize_receipt`` echoes it into the terminal receipt,
overwriting whatever the worker's capture claimed.

What lives here:

* ``canonical_plan_item_ids`` -- the single validator for a declared set. Both the
  declaration site and the descriptor validator call it, so there is one shape rule.
* ``resolve_packet_plan_item_ids`` -- explicit declaration wins; otherwise a detailed
  canonical packet phase reaches that same validator.
* ``require_single_active_plan_authority`` -- the repository-wide cardinality check
  over structural plan-header status claims.
* ``decide`` -- the marking rule. An item is done only on a terminal receipt that
  carries the ID, a reachable commit that changed the task's own declared write
  scope, and a settled cross-family APPROVE review. Any missing or unreadable
  piece leaves the item open and says which piece.
* ``move_item`` -- the atomic move: append the unchanged item block plus evidence
  pointers to history first, then remove it from the active plan.

Deliberately absent: any automatic firing. Nothing in the reconcile loop calls this.
Completion mutation stays an explicit controller action, so a defect here cannot
rewrite the ledger on a timer.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys

# ``P12``, ``P4.4``, ``P3.7b``, ``P10A.1``, ``P10B.7``. Derived from the 110 IDs
# actually in the two ledger files, not from a guess: an earlier draft omitted the
# uppercase phase suffix and would have made all 14 P10A/P10B items undeclarable.
# ``test_id_shape_covers_every_real_ledger_item`` pins it to the data.
# Bounded on purpose -- the ID becomes a Git grep argument and a Markdown match.
PLAN_ITEM_RE = re.compile(r"^P[0-9]{1,3}[A-Z]?(\.[0-9]{1,3}[a-z]?)?$")
MAX_DECLARED_ITEMS = 32
CHECKBOX_RE = re.compile(r"^- \[[ xX]\] (\S+)")
# A plan claims live remaining-work authority only through a structural status
# line, never because its prose mentions an "active plan". This covers the
# repository's Markdown spelling (``**Status:** active``) and plain YAML-style
# ``status: active`` while anchoring the claim to its own line.
PLAN_HEADER_STATUS_RE = re.compile(
    r"^[ \t]*(?:>[ \t]*)?(?:\*\*|__)?status[ \t]*:"
    r"(?:\*\*|__)?[ \t]*(?P<status>[A-Za-z][A-Za-z0-9_-]*)\b",
    re.IGNORECASE | re.MULTILINE,
)

# A receipt proves work was delivered. ``needs_review`` is the ordinary terminal
# outcome for a task under mandatory review, and the review leg is checked
# separately below, so accepting it here does not weaken the gate.
RECEIPT_SUCCESS_OUTCOMES = frozenset({"complete", "needs_review"})
SETTLED_TASK_STATUSES = frozenset({"complete", "closed"})
RECEIPT_SCHEMA_V2 = "board-dispatch-receipt/v2"

# Registry lane spelling -> author family. Mirrors registry_reconciler's map, but
# this module is imported by board_process_truth, which must not depend on the
# reconciler. Entries also pass through unchanged when already a family name,
# because a registry entry may record either spelling.
LANE_AUTHOR_FAMILY = {
    "gpt-codex": "openai",
    "codex": "openai",
    "claude": "anthropic",
    "gemini": "google",
    "kimi": "moonshot",
}

EVIDENCE_PREFIX = "      Evidence:"
HISTORY_SECTION = "## Evidence-bound completions"

# Every candidate costs two Git invocations, and the candidate list is whatever
# named the task in a commit message -- a quantity nothing else bounds.
MAX_ANCESTRY_CANDIDATES = 64
COMMIT_ID_RE = re.compile(r"^[0-9a-f]{40}$")


class PlanItemBindingError(ValueError):
    """A declaration, an evidence set, or a ledger move failed closed."""


def canonical_plan_item_ids(values) -> list[str]:
    """Validate a declared item set, preserving declaration order.

    ``None`` and ``[]`` both mean "this packet declares nothing" and return an
    empty list. That is the default for every existing packet, and making it an
    error would break every flow that does not opt in -- the exact mistake that
    took swarm registration down when a fail-closed reader landed without its
    writer.
    """

    if values is None:
        return []
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise PlanItemBindingError("plan_item_ids must be a list of item IDs")
    if len(values) > MAX_DECLARED_ITEMS:
        raise PlanItemBindingError(
            f"plan_item_ids declares {len(values)} items, over the "
            f"{MAX_DECLARED_ITEMS}-item bound"
        )
    seen: list[str] = []
    for value in values:
        if not isinstance(value, str) or not PLAN_ITEM_RE.fullmatch(value):
            raise PlanItemBindingError(f"invalid plan item id: {value!r}")
        if value in seen:
            raise PlanItemBindingError(f"duplicate plan item id: {value}")
        seen.append(value)
    return seen


def resolve_packet_plan_item_ids(
    values, *, phase, declaration_present: bool
) -> list[str]:
    """Resolve the packet's one plan-binding fact at admission.

    An explicit ``plan_item_ids`` field wins by *presence*, including an empty
    list. Without one, a detailed canonical phase such as ``P13.52`` becomes the
    declaration and therefore reaches the existing validator/receipt rail.

    Bare canonical phases (``P13``, ``P10A``) remain unbound. They are legitimate
    grouping labels, but do not name the detailed item one task closes; deriving
    them would let any task in a phase claim completion of the whole phase. A
    non-empty free-form phase fails closed instead of silently bypassing the ID
    validator that explicit declarations already face.
    """

    if declaration_present:
        return canonical_plan_item_ids(values)
    if phase in (None, "", "none"):
        return []
    if not isinstance(phase, str) or not PLAN_ITEM_RE.fullmatch(phase):
        raise PlanItemBindingError(f"invalid phase plan item id: {phase!r}")
    if "." not in phase:
        return []
    return canonical_plan_item_ids([phase])


def _plan_header_status(text: str, *, path: Path) -> str | None:
    """Read one plan-level status, excluding task statuses in the body."""

    preamble = text.split("\n## ", 1)[0]
    matches = list(PLAN_HEADER_STATUS_RE.finditer(preamble))
    if len(matches) > 1:
        raise PlanItemBindingError(
            f"plan file declares more than one header status: {path.name}"
        )
    return matches[0].group("status").casefold() if matches else None


def active_plan_authorities(plans_dir: Path) -> list[Path]:
    """Return direct plan files whose header status is exactly ``active``.

    The plans directory is an optional input. Its absence means the repository
    currently has no active plan authorities; a path that exists but is not a
    directory is still malformed and fails closed.
    """

    plans_dir = Path(plans_dir)
    try:
        mode = plans_dir.stat().st_mode
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise PlanItemBindingError(
            f"cannot inspect plans path {plans_dir}: {exc}"
        ) from exc
    if not stat.S_ISDIR(mode):
        raise PlanItemBindingError(f"plans path is not a directory: {plans_dir}")
    active: list[Path] = []
    for path in sorted(plans_dir.glob("*.md")):
        if path.name == "README.md" or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise PlanItemBindingError(f"cannot read plan file {path}: {exc}") from exc
        if _plan_header_status(text, path=path) == "active":
            active.append(path)
    return active


def require_single_active_plan_authority(plans_dir: Path) -> Path:
    """Require exactly one plan file to claim active remaining-work authority."""

    active = active_plan_authorities(plans_dir)
    if len(active) != 1:
        names = ", ".join(path.name for path in active) or "none"
        raise PlanItemBindingError(
            f"expected exactly one active plan authority; found {len(active)}: {names}"
        )
    return active[0]


def _family(value) -> str:
    lane = str(value or "").strip().lower()
    return LANE_AUTHOR_FAMILY.get(lane, lane)


def _entry_author_family(entry: dict) -> str:
    explicit = str(entry.get("author_family") or "").strip().lower()
    if explicit:
        return _family(explicit)
    contract = entry.get("verification_contract")
    if isinstance(contract, dict):
        contracted = str(contract.get("author_family") or "").strip().lower()
        if contracted:
            return _family(contracted)
    return _family(entry.get("to_model"))


def _resolve(repo_root: Path, value) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else repo_root / path


def _load_receipt(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _git(repo_root: Path, arguments: list[str]) -> str | None:
    """Run one Git command, returning stdout, or ``None`` when it did not run."""

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _relative_text(value: str) -> str:
    """Trim one path to repo-relative form, or return ``""`` to refuse it.

    The ORDER here is load-bearing. An earlier draft wrote ``value.strip("/")``
    to drop the trailing slash a directory scope carries -- but ``strip`` is
    symmetric, so it also ate the LEADING slash, silently promoting the absolute
    ``/bin`` into the repo-relative ``bin``. Measured against the real history,
    that made a scope of ``["/bin"]`` witness two commits it must have refused.
    Absolute paths are rejected BEFORE anything is trimmed.
    """

    text = value.strip()
    if not text or text.startswith("/"):
        return ""
    return text.rstrip("/")


def declared_scope_paths(values) -> tuple[PurePosixPath, ...]:
    """Normalise a task's declared ``write_scope`` into containment roots.

    Uninterpretable entries are dropped rather than raised on. This is a
    *witness filter*: a scope we cannot read must only ever narrow what counts
    as landed, never widen it. A scope that normalises to nothing therefore
    leaves the ancestry leg unsatisfiable, which is the fail-closed answer and
    also the structurally correct one -- ``integrate_worktree_commits`` refuses
    an empty integration scope outright, so a task with no write scope cannot
    have landed anything to witness.
    """

    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        return ()
    roots: list[PurePosixPath] = []
    for value in values:
        if not isinstance(value, str):
            continue
        text = _relative_text(value)
        if not text:
            continue
        path = PurePosixPath(text)
        # The integration rail rejects the repository root as a write scope.
        # Keep the witness at least as strict: PurePosixPath('.') has no parts
        # and is a parent of every repository path, so accepting it would turn
        # one corrupted legacy entry back into an all-repository witness.
        if not path.parts:
            continue
        # `..` would let a declared scope reach outside the repo; PurePosixPath
        # already drops `.` segments, so only the escape needs refusing.
        if ".." in path.parts:
            continue
        if path not in roots:
            roots.append(path)
    return tuple(roots)


def _within_scope(path: str, scopes: Sequence[PurePosixPath]) -> bool:
    """Is this changed path the scope root itself, or underneath one?"""

    # Git's `-z` path output is already repo-relative and unquoted. Preserve it
    # byte-for-character: stripping here would alias a real path such as
    # ``"src "`` to the declared scope ``"src"``.
    if not isinstance(path, str) or not path or path.startswith("/"):
        return False
    candidate = PurePosixPath(path)
    if ".." in candidate.parts:
        return False
    parents = frozenset(candidate.parents)
    return any(scope == candidate or scope in parents for scope in scopes)


def commit_changed_paths(commit: str, *, repo_root: Path) -> tuple[str, ...] | None:
    """Paths this commit changed against its FIRST parent. ``None`` if unknown.

    The first parent is resolved EXPLICITLY, and that is the whole subtlety of
    this function. ``git diff-tree -m --first-parent`` does not restrict the
    diff to the first parent -- it emits one diff per parent and
    ``--no-commit-id`` strips the headers that would have separated them, so a
    merge comes back as the *union* across its parents. Measured on the board's
    own integrate merge ``47e71dff``, that union added ``bin/doctor.sh``, a file
    the concurrent mainline advance contributed and the worker never touched.
    Crediting a merge for paths it did not introduce is precisely the
    over-permissiveness this leg exists to remove.

    Against the first parent, every shape the board produces answers correctly:
    a worker/residue commit reports what it authored, an integrate merge reports
    what it brought onto the mainline, a root commit reports its whole tree, and
    a commit that changed nothing reports nothing.
    """

    if not COMMIT_ID_RE.fullmatch(str(commit or "")):
        return None
    described = _git(repo_root, ["rev-list", "--parents", "-n", "1", commit])
    if described is None:
        return None
    fields = described.split()
    if not fields or fields[0] != commit:
        return None
    arguments = ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z"]
    # `-z` because the paths are matched against a declared scope: Git would
    # otherwise quote and escape unusual filenames, and a quoted path does not
    # compare equal to the scope it actually sits under.
    arguments += [fields[1], commit] if len(fields) > 1 else ["--root", commit]
    changed = _git(repo_root, arguments)
    if changed is None:
        return None
    return tuple(entry for entry in changed.split("\0") if entry)


def landed_commits(
    task_id: str,
    *,
    repo_root: Path,
    git_ref: str = "HEAD",
    write_scope=None,
) -> list[str]:
    """Commits reachable from ``git_ref`` that actually landed this task's work.

    Two independent legs, because naming a task is not doing it:

    1. **Reachability.** ``git log <ref>`` walks only ancestors of the ref, so a
       commit found here has landed on that branch.
    2. **Territory.** The commit must have changed at least one path inside the
       task's dispatcher-declared ``write_scope``, measured against its first
       parent. Message text is worker-influenceable prose; the scope is a
       controller-owned field that ``bin/send-task.sh`` writes from the
       Chrono-authored packet, and ``integrate_worktree_commits`` refuses to
       land anything outside it. So "changed an in-scope path" is exactly the
       signature of a board-landed commit for this task.

    Leg 2 is the fix for a check that could not fail. Without it, ANY reachable
    commit whose message merely mentioned the ID satisfied the landed-ancestry
    leg of the completion gate -- a bookkeeping commit, a one-line docs commit,
    or a genuinely empty one. Excluding only empty commits would have closed the
    instance and left the class, so the rule is stated positively: the commit
    must have touched the task's own territory.

    ``write_scope`` defaults to ``None`` and yields ``[]``. That default is
    fail-closed on purpose: a caller that cannot say what the task was
    authorised to change cannot be told that it landed.
    """

    if not task_id:
        return []
    scopes = declared_scope_paths(write_scope)
    if not scopes:
        return []
    named = _git(
        repo_root,
        [
            "log",
            "-z",
            "--format=%H%x00%B",
            "--fixed-strings",
            f"--grep={task_id}",
            git_ref,
            "--",
        ],
    )
    if named is None:
        raise PlanItemBindingError(
            "could not determine commit ancestry: git log failed"
        )
    fields = named.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        raise PlanItemBindingError(
            "could not determine commit ancestry: malformed git log output"
        )
    # `git log --fixed-strings --grep` is substring matching. Without this
    # token boundary, TASK-...-1170-extra can witness TASK-...-1170 when both
    # happen to touch the same scope. Commit messages cannot contain NUL, so
    # the paired NUL format above preserves arbitrary multi-line bodies while
    # keeping the hash/message association unambiguous.
    task_token = re.compile(
        rf"(?<![A-Za-z0-9_-]){re.escape(task_id)}(?![A-Za-z0-9_-])"
    )
    candidates = [
        commit.strip()
        for commit, message in zip(fields[0::2], fields[1::2])
        if COMMIT_ID_RE.fullmatch(commit.strip()) and task_token.search(message)
    ]
    landed = []
    for commit in candidates[:MAX_ANCESTRY_CANDIDATES]:
        changed = commit_changed_paths(commit, repo_root=repo_root)
        if changed is None:
            raise PlanItemBindingError(
                f"could not determine changed paths for commit {commit}"
            )
        if changed and any(_within_scope(path, scopes) for path in changed):
            landed.append(commit)
    return landed


@dataclass(frozen=True)
class Decision:
    """Whether one item may be marked done, and what is missing if not."""

    item_id: str
    task_id: str
    done: bool
    missing: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def decide(
    item_id: str,
    task_id: str,
    entry: dict,
    *,
    repo_root: Path,
    git_ref: str = "HEAD",
) -> Decision:
    """Apply the marking rule to one (item, task) pair.

    Every leg is independent and every failure is named. A caller that wants to
    know *why* an item stayed open reads ``missing``; a caller that only wants the
    answer reads ``done``. There is no partial credit: one missing leg leaves the
    item open, because completion must be as hard to fake as a failure.
    """

    if not PLAN_ITEM_RE.fullmatch(str(item_id or "")):
        raise PlanItemBindingError(f"invalid plan item id: {item_id!r}")
    missing: list[str] = []
    evidence: dict = {"item_id": item_id, "task_id": task_id}

    if not isinstance(entry, dict):
        return Decision(item_id, task_id, False, ["task_not_registered"], evidence)
    if str(entry.get("status") or "").strip().lower() not in SETTLED_TASK_STATUSES:
        missing.append("task_not_settled")

    # --- terminal receipt carrying the ID ------------------------------------
    receipt = _load_receipt(_resolve(repo_root, entry.get("terminal_receipt_path")))
    if receipt is None:
        missing.append("receipt_missing")
    else:
        if receipt.get("schema") != RECEIPT_SCHEMA_V2:
            missing.append("receipt_schema_unsupported")
        elif (
            receipt.get("task_id") != task_id
            or receipt.get("attempt_id") != entry.get("delivery_attempt_id")
            or receipt.get("generation") != entry.get("delivery_generation")
        ):
            missing.append("receipt_identity_mismatch")
        else:
            outcome = str(receipt.get("terminal_outcome") or "")
            if outcome not in RECEIPT_SUCCESS_OUTCOMES:
                missing.append("receipt_outcome_not_terminal_success")
            try:
                declared = canonical_plan_item_ids(receipt.get("plan_item_ids"))
            except PlanItemBindingError:
                declared = []
                missing.append("receipt_declaration_malformed")
            if item_id not in declared:
                missing.append("receipt_does_not_declare_item")
            evidence["receipt_path"] = str(entry.get("terminal_receipt_path") or "")
            evidence["receipt_outcome"] = outcome

    # --- landed commit ancestry ----------------------------------------------
    # The scope is read from the REGISTRY ENTRY, never from the receipt or the
    # worktree. `bin/send-task.sh` writes it there from the Chrono-authored
    # packet and it is part of the dispatch identity, so it is the same class of
    # controller-owned evidence as the review fields below. A worker cannot
    # widen the territory it will later be judged against.
    scope = entry.get("write_scope")
    if not declared_scope_paths(scope):
        # Distinct from `commit_ancestry_missing`: nothing was even measurable.
        missing.append("commit_ancestry_unscoped")
    else:
        try:
            commits = landed_commits(
                task_id, repo_root=repo_root, git_ref=git_ref, write_scope=scope
            )
        except PlanItemBindingError as exc:
            missing.append("commit_ancestry_unknown")
            evidence["commit_ancestry_error"] = str(exc)
        else:
            if not commits:
                missing.append("commit_ancestry_missing")
            else:
                evidence["commit"] = commits[0]

    # --- required anti-affinity review ---------------------------------------
    # Checked for every declared item, not only when `mandatory_review` is set. A
    # packet that declared items and waived review would otherwise be an easier
    # route to "done" than to "failed".
    review_ref = str(entry.get("cross_family_review_ref") or "").strip()
    verdict = str(entry.get("verdict") or "").strip().upper()
    settled_by = str(entry.get("review_settled_by") or "").strip()
    if settled_by != "chrono-explicit" or not review_ref:
        missing.append("review_not_settled")
    elif verdict != "APPROVE":
        missing.append("review_not_approved")
    elif entry.get("review_force_override"):
        missing.append("review_force_overridden")
    else:
        reviewer = _family(entry.get("review_model"))
        author = _entry_author_family(entry)
        if not reviewer or not author or reviewer == author:
            missing.append("review_not_cross_family")
        else:
            evidence["review_ref"] = review_ref
            evidence["verdict"] = verdict
            evidence["reviewer_family"] = reviewer
            evidence["author_family"] = author

    return Decision(item_id, task_id, not missing, missing, evidence)


# ── ledger surgery ────────────────────────────────────────────────────────────


def atomic_write(path, text: str) -> None:
    """Temp + fsync + rename, per Hard Rule 7. Module-level so callers can wrap it."""

    path = Path(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def checkbox_item_ids(text: str) -> list[str]:
    """Every plan item ID carrying a checkbox in this file, in order."""

    found = []
    for line in text.splitlines():
        match = CHECKBOX_RE.match(line)
        if match and PLAN_ITEM_RE.fullmatch(match.group(1)):
            found.append(match.group(1))
    return found


def _block_bounds(text: str, item_id: str) -> tuple[int, int] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = CHECKBOX_RE.match(line)
        if not match or match.group(1) != item_id:
            continue
        end = index + 1
        while end < len(lines) and lines[end][:1].isspace() and lines[end].strip():
            end += 1
        return index, end
    return None


def find_item_block(text: str, item_id: str) -> str:
    """The exact item text: its checkbox line plus indented continuation lines."""

    bounds = _block_bounds(text, item_id)
    if bounds is None:
        raise PlanItemBindingError(f"item is not present as a checkbox: {item_id}")
    start, end = bounds
    return "\n".join(text.splitlines()[start:end])


def _evidence_line(item_id: str, evidence: dict) -> str:
    return (
        f"{EVIDENCE_PREFIX} item={item_id} task={evidence.get('task_id', '')} "
        f"commit={evidence.get('commit', '')} "
        f"receipt={evidence.get('receipt_path', '')} "
        f"outcome={evidence.get('receipt_outcome', '')} "
        f"review={evidence.get('review_ref', '')} "
        f"verdict={evidence.get('verdict', '')}"
    )


def _recorded_evidence(history_text: str, item_id: str) -> str | None:
    marker = f"{EVIDENCE_PREFIX} item={item_id} "
    for line in history_text.splitlines():
        if line.startswith(marker):
            return line
    return None


def move_item(item_id: str, evidence: dict, *, plan: Path, history: Path) -> bool:
    """Move one item from the active plan to completion history.

    Returns ``False`` for an idempotent no-op -- the item is already recorded
    complete with this exact evidence. Raises when the item is open in neither
    file, or when history already records a *different* evidence tuple for it:
    a conflicting record is a real disagreement about what happened, and guessing
    which one is right is how a ledger silently becomes wrong.
    """

    plan, history = Path(plan), Path(history)
    plan_text = plan.read_text(encoding="utf-8")
    history_text = history.read_text(encoding="utf-8")

    in_plan = checkbox_item_ids(plan_text).count(item_id)
    in_history = checkbox_item_ids(history_text).count(item_id)
    if in_plan > 1:
        raise PlanItemBindingError(f"item is open more than once in the plan: {item_id}")
    if not in_plan and not in_history:
        raise PlanItemBindingError(f"item is in neither the plan nor history: {item_id}")

    line = _evidence_line(item_id, evidence)
    if in_history:
        recorded = _recorded_evidence(history_text, item_id)
        if recorded is not None and recorded != line:
            raise PlanItemBindingError(
                f"history records conflicting evidence for {item_id}"
            )
        if not in_plan:
            return False
        # A crash between the two writes left a duplicate. The same evidence
        # tuple makes the restart remove it idempotently.
        start, end = _block_bounds(plan_text, item_id)
        remaining = plan_text.splitlines()[:start] + plan_text.splitlines()[end:]
        atomic_write(plan, "\n".join(remaining) + "\n")
        return True

    block = find_item_block(plan_text, item_id)
    completed = block.replace(f"- [ ] {item_id}", f"- [x] {item_id}", 1)

    appended = history_text if history_text.endswith("\n") else history_text + "\n"
    if HISTORY_SECTION not in appended:
        appended += f"\n{HISTORY_SECTION}\n"
    appended += f"\n{completed}\n{line}\n"
    # History first: a crash here leaves a duplicate, never a lost item.
    atomic_write(history, appended)

    start, end = _block_bounds(plan_text, item_id)
    remaining = plan_text.splitlines()[:start] + plan_text.splitlines()[end:]
    atomic_write(plan, "\n".join(remaining) + "\n")
    return True


# ── controller entry points ───────────────────────────────────────────────────


def _registry(repo_root: Path) -> dict:
    path = repo_root / "_state" / "active-tasks.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PlanItemBindingError(f"cannot read the active registry: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _declared_for(entry: dict, repo_root: Path) -> list[str]:
    receipt = _load_receipt(_resolve(repo_root, entry.get("terminal_receipt_path")))
    if receipt is None:
        return []
    try:
        return canonical_plan_item_ids(receipt.get("plan_item_ids"))
    except PlanItemBindingError:
        return []


def _evaluate(args) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = _registry(repo_root)
    task_ids = [args.task_id] if args.task_id else sorted(registry)
    report = []
    for task_id in task_ids:
        entry = registry.get(task_id)
        if not isinstance(entry, dict):
            continue
        for item_id in _declared_for(entry, repo_root):
            decision = decide(
                item_id, task_id, entry, repo_root=repo_root, git_ref=args.git_ref
            )
            report.append(
                {
                    "item_id": decision.item_id,
                    "task_id": decision.task_id,
                    "done": decision.done,
                    "missing": decision.missing,
                    "evidence": decision.evidence,
                }
            )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _mark(args) -> int:
    repo_root = Path(args.repo_root).resolve()
    plan, history = Path(args.plan), Path(args.history)
    registry = _registry(repo_root)
    task_ids = [args.task_id] if args.task_id else sorted(registry)

    sys.path.insert(0, str(repo_root / "scripts" / "python"))
    import registry_reconciler as rr

    moved, held = [], []
    # One lock for the whole pass. Re-read both files inside it: the structural
    # contract is "open in exactly one partition", and a concurrent writer would
    # make that check describe a state that no longer exists.
    with rr.locked_registry():
        for task_id in task_ids:
            entry = registry.get(task_id)
            if not isinstance(entry, dict):
                continue
            for item_id in _declared_for(entry, repo_root):
                decision = decide(
                    item_id, task_id, entry, repo_root=repo_root, git_ref=args.git_ref
                )
                if not decision.done:
                    held.append({"item_id": item_id, "missing": decision.missing})
                    continue
                if args.dry_run:
                    moved.append({"item_id": item_id, "dry_run": True})
                    continue
                changed = move_item(item_id, decision.evidence, plan=plan, history=history)
                moved.append({"item_id": item_id, "changed": changed})
    print(json.dumps({"marked": moved, "held": held}, indent=2, sort_keys=True))
    return 0


def _declare(args) -> int:
    try:
        values = json.loads(args.json)
    except ValueError as exc:
        raise SystemExit(f"plan_item_ids is not valid JSON: {exc}") from exc
    try:
        print(
            json.dumps(
                resolve_packet_plan_item_ids(
                    values,
                    phase=args.phase or "",
                    declaration_present=args.phase is None,
                ),
                separators=(",", ":"),
            )
        )
    except PlanItemBindingError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".")
    subparsers = parser.add_subparsers(dest="command", required=True)

    declare = subparsers.add_parser("declare", help="validate a declared item set")
    declare.add_argument("--json", required=True)
    declare.add_argument(
        "--phase",
        help="derive from this phase because plan_item_ids was absent",
    )
    declare.set_defaults(handler=_declare)

    for name, handler in (("evaluate", _evaluate), ("mark", _mark)):
        sub = subparsers.add_parser(name)
        sub.add_argument("--task-id")
        sub.add_argument("--git-ref", default="HEAD")
        if name == "mark":
            sub.add_argument("--plan", required=True)
            sub.add_argument("--history", required=True)
            sub.add_argument("--dry-run", action="store_true")
        sub.set_defaults(handler=handler)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except PlanItemBindingError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
