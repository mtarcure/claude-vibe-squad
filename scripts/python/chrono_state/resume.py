"""Bounded, source-tagged Chrono resume capsule.

Regenerated from the decision-authority record + the live board registry (never a
summary-of-a-summary). Every line carries a source ID ([DEC-...] / [TASK-...]) so the
capsule is a cache pointing at authority, never authority itself. This becomes the new
content of `current.md`: a thin derived cursor, not a narrative log.

A derived cache is only worth having if it is regenerated; `write_capsule` is the
single writer, and `bin/chrono-resume-capsule.sh` is the entry point that calls it.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from chrono_state.registry import registry_view
from chrono_state.decisions import active_decisions

CAPSULE_PATH = (
    Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "chrono" / "resume.md"
)
TASKS_HEADING = "## Live tasks (dispatched / in-flight / review-required)"
DEFERRED_HEADING = "## Deferred owed work (awaiting a Chrono/operator action)"
CONTRA_HEADING = "## Memory contradictions (unreconciled)"
TURN_HEADING = "## Latest operator instruction"
NO_TURN_PLACEHOLDER = "(none recorded since the last snapshot)"


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


def _render(latest_operator_turn, view, max_tokens=3000, unreconciled=None):
    """Build a token-bounded capsule from an already-classified registry view.

    Under pressure the contradiction count drops first, then live task lines,
    then deferred lines — the count is re-derivable from the audit trail at any
    time and is the least precious to the resume moment, while live work
    re-surfaces through board sweeps and deferred work surfaces nowhere but here
    (so it bites last). At the real budget nothing drops and all three show.
    Active decisions, the omission/unclassified declarations, and the latest
    operator instruction are never dropped.
    """
    decs = active_decisions()
    tasks = view["live"]
    deferred = view["deferred"]

    def build(shown_live, shown_deferred, show_contra):
        lines = ["# Chrono resume capsule", "", "## Active decisions"]
        lines += [f"- {d['statement']} [{d['decision_id']}]" for d in decs] or ["- (none)"]
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
    cap = build(shown_live, shown_deferred, show_contra)
    # hard token bound (~4 chars/token): drop the contradiction line first, then
    # live, then deferred; rebuild and re-check.
    while len(cap) // 4 > max_tokens and (show_contra or shown_live or shown_deferred):
        if show_contra:
            show_contra = False
        elif shown_live:
            shown_live = shown_live[:-1]
        else:
            shown_deferred = shown_deferred[:-1]
        cap = build(shown_live, shown_deferred, show_contra)
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
