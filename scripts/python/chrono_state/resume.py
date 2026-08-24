"""Bounded, source-tagged Chrono resume capsule.

Regenerated from the decision-authority record + the live board registry (never a
summary-of-a-summary). Every projected item carries a source ID
([DEC-...] / [TASK-...] / [THREAD-...]) so the
capsule is a cache pointing at authority, never authority itself. This becomes the new
content of `current.md`: a thin derived cursor, not a narrative log.

A derived cache is only worth having if it is regenerated; `write_capsule` is the
single writer, and `bin/chrono-resume-capsule.sh` is the entry point that calls it.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from chrono_state.decisions import active_decisions
from chrono_state.registry import registry_view
from chrono_state.thread_charters import (
    load_archived_debt,
    CHARTERS_REL,
    ThreadCharter,
    clip,
    load_active_charters,
)

CAPSULE_PATH = (
    Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "chrono" / "resume.md"
)
QUEUE_PATH = Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "chrono-queue.md"
ARCHIVED_DEBT_ROOT = Path(os.environ.get("VAULT_ROOT", "."))
TASKS_HEADING = "## Live tasks (dispatched / in-flight / review-required)"
DEFERRED_HEADING = "## Deferred owed work (awaiting a Chrono/operator action)"
QUEUE_HEADING = "## Pending completions (specialist returns awaiting a decision)"
CONTRA_HEADING = "## Memory contradictions (unreconciled)"
TURN_HEADING = "## Latest operator instruction"
ARCHIVED_DEBT_HEADING = "## Archived with unfinished business"


def _archived_debt_rows(root=None) -> list[str]:
    """Bounded, warn-only rows naming charters archived while still owed.

    Every reader of charter state stops at ``active/``; archiving is a bare
    ``mv``. So debt is visible until the move and invisible after it -- which is
    how six queued items and three unticked boxes went unread. This says what is
    owed and nothing else: it renders no verdict, gates nothing, and no caller
    may branch on it.

    Probation: if this stays empty across roughly ten sessions, the written
    discipline is holding and this code should be deleted. A check that never
    fires is not a safety net, it is a cost.
    """
    try:
        owed = load_archived_debt(ARCHIVED_DEBT_ROOT if root is None else root)
    except Exception:
        return []
    rows = []
    for charter in owed[:8]:
        bits = []
        if not charter.done_when_met:
            bits.append("DONE-WHEN unticked")
        if charter.unresolved_queues:
            bits.append(f"{len(charter.unresolved_queues)} unresolved QUEUE")
        rows.append(f"- {charter.path.name}: {', '.join(bits)}")
    if len(owed) > 8:
        rows.append(f"- … and {len(owed) - 8} more")
    return rows


THREAD_HEADING = "## Active thread / Owed attention"
NO_TURN_PLACEHOLDER = "(none recorded since the last snapshot)"
MAX_PROJECTED_CHARTERS = 8
MAX_PROJECTED_QUEUES = 4
MAX_PROJECTED_DONE_WHEN = 6


def unreconciled_contradiction_count():
    """Count distinct notes left in an unreconciled contradiction, or None if unknown.

    A write that contradicts an active note and does not reconcile it is flagged
    in the chrono-vault audit trail and kept (never refused); the note stays
    disputed until someone acts. That owed work surfaces nowhere unless the
    capsule reports it, so P13.67 adds the count here.

    Single source: `recall._unreconciled_note_ids`, the one reader of the audit
    trail's flagged contradiction events — recall marks each disputed note with
    the same set. The plugin is imported lazily and every failure is swallowed:
    this is a must-not-crash session-resume path, so it must never depend on the
    vault plugin importing cleanly. Returns None — rendered as a loud "unknown",
    never a false 0 — when the trail cannot be read (no vault bound in this
    session, or the plugin is unimportable), the board-spawn-missing-root case
    that a silent 0 would hide.
    """
    try:
        plugin_dir = Path(__file__).resolve().parents[3] / "plugins" / "chrono-vault"
        # Append, never insert: the plugin's flat module names (audit, recall,
        # index, …) must not shadow anything already importable here.
        if str(plugin_dir) not in sys.path:
            sys.path.append(str(plugin_dir))
        import audit  # noqa: E402 — lazy, fail-soft plugin reach
        import recall  # noqa: E402

        if audit.resolve_audit_dir() is None:
            return None
        return len(recall._unreconciled_note_ids())
    except Exception:  # noqa: BLE001 — the capsule must render regardless
        return None


def _contradiction_line(unreconciled):
    """The one capsule line reporting unreconciled-contradiction debt."""
    if unreconciled is None:
        return (
            "- unreconciled contradiction count unavailable "
            "(chrono-vault audit trail unreadable)"
        )
    return (
        f"- {unreconciled} note(s) hold an unreconciled contradiction "
        "(chrono-vault audit trail; reconcile or supersede to clear)"
    )


def pending_completions(path=None):
    """Group `_state/chrono-queue.md` lines by `(namespace, status)`, counted.

    chrono/CLAUDE.md step 7 tells Chrono to read this file directly, but nothing
    ever did — 3,722 lines, zero handled (`shared/protocol.md:339`: "with no
    later reader it is durable storage, not a notification"). The capsule is the
    only path Chrono actually reads at session start, so this makes the queue
    reachable from there.

    Individual lines are never emitted here: the live queue can hold hundreds of
    open entries, which would blow the capsule's `max_tokens` budget outright.
    Grouped counts are the bounded projection; `_render` still subjects this
    section to the token-bound cascade, since even the grouped form can grow
    past budget on a long-uncleared queue.

    Each line is `timestamp | status | namespace/task-id | summary`; only the
    status and the namespace (text before the first `/`) are used. `#`-prefixed
    and blank lines are skipped. A malformed line (fewer than 3 `|`-fields) is
    skipped rather than raising — one bad line must not blank the whole section.
    Returns `[]`, never raises, when the file is absent, unreadable, or not
    valid UTF-8 (`read_text` raises `UnicodeDecodeError`, a `ValueError`
    subclass, on invalid bytes — caught alongside `OSError` here because a
    corrupt queue must never break capsule generation any more than a missing
    one does; fix round 2, controller ruling: the watcher that writes these
    summaries has separately produced verbatim error captures containing raw
    ANSI escapes, so invalid-UTF-8 input is a real risk, not a hypothetical
    one). Sorted by count descending, then by `(namespace, status)` for a
    stable order.
    """
    dest = Path(path) if path else QUEUE_PATH
    try:
        text = dest.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    counts = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = line.split("|", 3)
        if len(fields) < 3:
            continue
        status = fields[1].strip()
        namespace = fields[2].strip().split("/", 1)[0]
        key = (namespace, status)
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def active_thread_charters(path=None, now: datetime | None = None):
    """Load open charters from the active-path status rail, fail-soft.

    Deriving the default from ``CAPSULE_PATH`` keeps throwaway/test capsules
    isolated from the host's real charters when callers rebind that path.
    """
    source = (
        Path(path)
        if path
        else CAPSULE_PATH.parent / CHARTERS_REL.relative_to("_state/chrono")
    )
    try:
        return load_active_charters(source, now=now)
    except Exception as exc:  # noqa: BLE001 — resume must never blank the capsule
        # A read failure must be loud, not indistinguishable from "no active
        # threads". Represent it as one invalid projected charter so the
        # capsule still renders and points Chrono at the failed source.
        return [
            ThreadCharter(
                path=source / "unreadable-charter-rail.md",
                ask="",
                open_loops=(),
                done_when=(),
                done_when_met=False,
                unresolved_queues=(),
                stale_claims=(),
                issues=(f"active charter rail unreadable ({exc})",),
            )
        ]


def _thread_lines(
    charters: list[ThreadCharter],
    mode: int,
    needs_human: list[dict] | None = None,
) -> list[str]:
    """Render the bounded charter and urgent operator-attention projection.

    ``mode`` 2 is the useful projection, 1 is one line per thread, and 0 is a
    loud count-only fallback.  The global capsule bound can therefore compress
    charter detail without making active or queued work look absent. A
    ``needs_human`` task is stronger than ordinary deferred work, so its ID is
    pinned to this rail at every mode and cannot be crowded out by queue depth.
    """
    urgent = list(needs_human or ())
    queue_total = sum(len(charter.unresolved_queues) for charter in charters)
    lines = [
        f"- NEEDS HUMAN: {task.get('next_action', 'operator decision')} [{task['id']}]"
        for task in urgent
    ]
    if mode <= 0:
        if charters:
            lines.append(
                f"- active={len(charters)}; open_QUEUE={queue_total} "
                "[THREAD-RAIL:bound]"
            )
        return lines

    shown = charters[:MAX_PROJECTED_CHARTERS]
    if mode == 1:
        for charter in shown:
            checked = sum(line.lower().startswith("- [x]") for line in charter.done_when)
            flags = [f"DONE-WHEN {checked}/{len(charter.done_when)}"]
            if charter.unresolved_queues:
                flags.append(f"{len(charter.unresolved_queues)} unresolved QUEUE")
            if charter.stale_claims:
                flags.append(f"{len(charter.stale_claims)} stale current claim(s)")
            if charter.issues:
                flags.append("INVALID FORMAT")
            suffix = f"; {'; '.join(flags)}" if flags else ""
            lines.append(
                f"- THE ASK: {clip(charter.ask or '(unreadable)', 150)}{suffix} "
                f"[THREAD-{charter.thread_id}]"
            )
    else:
        for charter in shown:
            source = f"[THREAD-{charter.thread_id}]"
            lines.append(f"- THE ASK: {clip(charter.ask or '(unreadable)', 240)} {source}")
            if charter.done_when:
                for criterion in charter.done_when[:MAX_PROJECTED_DONE_WHEN]:
                    lines.append(f"  - DONE-WHEN: {clip(criterion, 240)} {source}")
                dropped_done = len(charter.done_when) - MAX_PROJECTED_DONE_WHEN
                if dropped_done > 0:
                    lines.append(
                        f"  - +{dropped_done} DONE-WHEN criterion/criteria omitted "
                        f"from this bounded block {source}"
                    )
            else:
                lines.append(f"  - DONE-WHEN: (missing) {source}")
            for loop in charter.unresolved_queues[:MAX_PROJECTED_QUEUES]:
                lines.append(f"  - {clip(loop.raw[2:], 500)} {source}")
            dropped_queues = len(charter.unresolved_queues) - MAX_PROJECTED_QUEUES
            if dropped_queues > 0:
                lines.append(
                    f"  - +{dropped_queues} unresolved QUEUE item(s) omitted from "
                    f"this bounded block {source}"
                )
            if charter.stale_claims:
                oldest = charter.stale_claims[0].observed_at
                lines.append(
                    f"  - WARNING: {len(charter.stale_claims)} current claim(s) are "
                    f"stale; oldest observed_at={oldest} (>24h) — refresh before "
                    f"presenting as current {source}"
                )
            if charter.issues:
                lines.append(
                    f"  - WARNING: invalid charter format — "
                    f"{clip('; '.join(charter.issues), 240)} {source}"
                )

    dropped_charters = len(charters) - len(shown)
    if dropped_charters:
        lines.append(
            f"- +{dropped_charters} active charter(s) omitted from this bounded "
            f"block — read {CHARTERS_REL}/"
        )
    return lines


def _render(latest_operator_turn, view, max_tokens=3000, unreconciled=None):
    """Build a token-bounded capsule from an already-classified registry view.

    Under pressure the contradiction count drops first, then live task lines
    are trimmed, then the pending-completions section collapses to a one-line
    declared omission, then deferred lines are trimmed, and only then does the
    active-thread block compress from full to summary to a loud count. The
    charter rail therefore outlives every other droppable section. Contradiction count
    is the least precious (re-derivable from the audit trail at any time) and
    live work is next (it re-surfaces through board sweeps), but
    pending-completions groups outrank both of those: nothing else in the
    capsule surfaces `_state/chrono-queue.md` at all, so a handful of
    live-task lines are traded away before the section collapses (controller
    ruling, fix round 1: measured on the real capsule, live tasks alone were
    ~75% of the 3000-token budget while the grouped pending section needed
    only ~116 tokens — dropping pending first made it permanently invisible in
    practice, which is worse than trimming a few recoverable live lines).
    Collapsing pending never goes silent (fix round 2): like live and
    deferred, it always declares what it dropped, because a missing heading
    is indistinguishable from "the queue is empty" — the exact ambiguity this
    section exists to kill. Deferred work still bites last: it surfaces
    nowhere but here. At the real budget nothing drops and every section shows.
    Active decisions, the omission/unclassified declarations, the active-thread
    heading/count, and the latest operator instruction are never dropped.
    """
    decs = active_decisions()
    tasks = view["live"]
    needs_human = [
        task for task in view["deferred"] if task.get("state") == "needs_human"
    ]
    deferred = [
        task for task in view["deferred"] if task.get("state") != "needs_human"
    ]
    pending = pending_completions()
    charters = active_thread_charters()
    debt_rows = _archived_debt_rows()

    def build(
        shown_live,
        shown_deferred,
        show_contra,
        show_pending,
        show_debt,
        thread_mode,
    ):
        lines = ["# Chrono resume capsule", "", "## Active decisions"]
        lines += [f"- {d['statement']} [{d['decision_id']}]" for d in decs] or ["- (none)"]
        if charters or needs_human:
            lines += ["", THREAD_HEADING]
            lines += _thread_lines(charters, thread_mode, needs_human)
        # Warn-only. Charters archived while still owed are invisible to every
        # other reader, because they all stop at active/ and archiving is a mv.
        # Collapses before live tasks are trimmed: this block is a POINTER, so
        # its one-line form keeps the whole signal (how many, where to look),
        # while a dropped live line loses that task's next action outright.
        # Never silent -- same rule as pending: an absent heading would read as
        # "nothing is owed", which is the ambiguity the block exists to kill.
        if debt_rows:
            lines += ["", ARCHIVED_DEBT_HEADING]
            if show_debt:
                lines += [
                    "Closed while still carrying unfinished business. Resolve "
                    "each into `_state/chrono/OPEN-WORK.md` or finish it.",
                ] + debt_rows
            else:
                lines += [
                    f"- ({len(debt_rows)} archived charter(s) still owed, "
                    "omitted for the token bound — regenerate at a higher "
                    "budget or read _state/chrono/thread-charters/complete)"
                ]
        lines += ["", TASKS_HEADING]
        lines += [
            f"- {t['state']}: {t.get('next_action', '?')} [{t['id']}]"
            for t in shown_live
        ] or ["- (none)"]
        # An omission the capsule does not declare is indistinguishable from a task
        # that closed — the exact ambiguity that let this file rot unnoticed.
        dropped = len(tasks) - len(shown_live)
        if dropped:
            lines += [f"- (+{dropped} more live, omitted for the token bound)"]
        if deferred:
            # A count line is not a task line (0230 review): a resuming Chrono
            # must be able to act from the capsule alone, so deferred work is
            # itemised with its ID and next action.
            lines += ["", DEFERRED_HEADING]
            lines += [
                f"- {t['state']}: {t.get('next_action', '?')} [{t['id']}]"
                for t in shown_deferred
            ]
            dropped_deferred = len(deferred) - len(shown_deferred)
            if dropped_deferred:
                lines += [
                    f"- (+{dropped_deferred} more deferred, omitted for the token "
                    "bound — query _state/active-tasks.json by status)"
                ]
        if pending:
            # Silent when dropped is the exact ambiguity this section exists to
            # kill (fix round 2): a missing heading must never be mistaken for
            # "the queue is empty" the way an omitted live/deferred task must
            # never read as "closed". Always declare, even when trimmed away.
            lines += ["", QUEUE_HEADING]
            if show_pending:
                lines += [
                    f"- {count} x {namespace} | {status}"
                    for (namespace, status), count in pending
                ]
            else:
                lines += [
                    f"- ({len(pending)} group(s) omitted for the token bound "
                    "— regenerate at a higher budget or read "
                    "_state/chrono-queue.md)"
                ]
        for status, n in sorted(view["unclassified"].items()):
            lines += [
                f"- UNCLASSIFIED STATUS {status!r}: {n} task(s) invisible to this "
                "capsule — add it to chrono_state/registry.py KNOWN_STATUSES"
            ]
        if show_contra:
            lines += ["", CONTRA_HEADING, _contradiction_line(unreconciled)]
        lines += ["", TURN_HEADING, f"- {latest_operator_turn}"]
        return "\n".join(lines)

    shown_live, shown_deferred = list(tasks), list(deferred)
    show_contra = True
    show_pending = True
    show_debt = True
    thread_mode = 2
    cap = build(
        shown_live,
        shown_deferred,
        show_contra,
        show_pending,
        show_debt,
        thread_mode,
    )
    # hard token bound (~4 chars/token): drop the contradiction line, then trim
    # live task lines, then collapse the pending-completions section to a
    # declared omission, then trim deferred, then compress active-thread detail;
    # rebuild and re-check. Live is
    # trimmed BEFORE pending collapses — see the priority note above — so
    # pending only collapses once trimming live has failed to free enough
    # room on its own.
    while len(cap) // 4 > max_tokens and (
        show_contra
        or show_debt
        or shown_live
        or show_pending
        or shown_deferred
        or (charters and thread_mode > 0)
    ):
        if show_contra:
            show_contra = False
        elif show_debt:
            show_debt = False
        elif shown_live:
            shown_live = shown_live[:-1]
        elif show_pending:
            show_pending = False
        elif shown_deferred:
            shown_deferred = shown_deferred[:-1]
        else:
            thread_mode -= 1
        cap = build(
            shown_live,
            shown_deferred,
            show_contra,
            show_pending,
            show_debt,
            thread_mode,
        )
    return cap


def render_capsule(session_id, latest_operator_turn, max_tokens=3000):
    """Render a fresh capsule from the live registry (see `_render`)."""
    return _render(
        latest_operator_turn,
        registry_view(),
        max_tokens=max_tokens,
        unreconciled=unreconciled_contradiction_count(),
    )


def previous_operator_turn(path=None):
    """Recover the operator instruction already recorded in the capsule on disk.

    Regeneration is driven by registry changes, which carry no operator turn. Without
    this, every automatic refresh would overwrite the one human line in the file.
    """
    dest = Path(path) if path else CAPSULE_PATH
    if not dest.exists():
        return None
    lines = dest.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.strip() != TURN_HEADING:
            continue
        for follow in lines[index + 1 :]:
            if follow.startswith("- "):
                return follow[2:].strip()
        break
    return None


def resolve_operator_turn(explicit_turn, snapshot_turn=None, path=None):
    """Pick the operator turn a refresh should record — the snapshot fills a vacuum.

    The precedence needs no timestamps: an explicit turn (the operator speaking
    now) always wins; otherwise a real line already in the capsule is kept; only
    when the capsule has no line (missing file, or the placeholder) does the
    compaction snapshot's turn fill it. mtime is not a causality signal — a
    copied or restored file carries a newer mtime with older content, and the
    0230 review reproduced exactly that overwriting a newer capsule line — so
    the snapshot never competes with an existing line at all. The cost: compact
    recovery only recovers a turn when the capsule has none, the honest trade
    for deleting an unprovable ordering.
    """
    if explicit_turn:
        return explicit_turn
    capsule_turn = previous_operator_turn(Path(path) if path else CAPSULE_PATH)
    if capsule_turn == NO_TURN_PLACEHOLDER:
        capsule_turn = None
    return capsule_turn or snapshot_turn


def write_capsule(session_id, latest_operator_turn=None, max_tokens=3000, path=None):
    """Atomically regenerate the capsule on disk (temp + fsync + rename). Returns path.

    `latest_operator_turn` falls back to whatever the previous capsule recorded, so a
    registry-triggered refresh never destroys the operator instruction. An
    unclassified board status is loud twice: named in the capsule itself (via
    `_render`) and warned on stderr here, so the write path can never silently
    drop owed state again.
    """
    dest = Path(path) if path else CAPSULE_PATH
    turn = (
        latest_operator_turn
        or previous_operator_turn(dest)
        or NO_TURN_PLACEHOLDER
    )
    view = registry_view()
    if view["unclassified"]:
        print(
            "WARNING: resume capsule: unclassified board statuses "
            f"{sorted(view['unclassified'])} — add them to "
            "chrono_state/registry.py KNOWN_STATUSES; affected tasks are counted "
            "in the capsule but cannot be listed",
            file=sys.stderr,
        )
    body = (
        _render(
            turn,
            view,
            max_tokens=max_tokens,
            unreconciled=unreconciled_contradiction_count(),
        )
        + "\n"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile("w", dir=dest.parent, delete=False)
    try:
        tmp.write(body)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, dest)
    except BaseException:
        # A failed rename must not leave the named temp beside the capsule — and
        # cleanup must never mask the failure that got us here: guard the close
        # (closing a buffered file can itself raise), always attempt the unlink,
        # and re-raise the ORIGINAL exception.
        try:
            tmp.close()
        except Exception:
            pass
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise
    return dest
