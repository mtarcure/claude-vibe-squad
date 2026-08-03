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
TURN_HEADING = "## Latest operator instruction"
NO_TURN_PLACEHOLDER = "(none recorded since the last snapshot)"


def _render(latest_operator_turn, view, max_tokens=3000):
    """Build a token-bounded capsule from an already-classified registry view.

    Under pressure, live task lines drop first, then deferred lines — each with a
    declared count. Live work re-surfaces through board sweeps and notifications;
    deferred work surfaces nowhere but here, so the bound bites it last. Active
    decisions, the omission/unclassified declarations, and the latest operator
    instruction are never dropped.
    """
    decs = active_decisions()
    tasks = view["live"]
    deferred = view["deferred"]

    def build(shown_live, shown_deferred):
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
        lines += ["", TURN_HEADING, f"- {latest_operator_turn}"]
        return "\n".join(lines)

    shown_live, shown_deferred = list(tasks), list(deferred)
    cap = build(shown_live, shown_deferred)
    # hard token bound (~4 chars/token): drop lines, rebuild, re-check.
    while len(cap) // 4 > max_tokens and (shown_live or shown_deferred):
        if shown_live:
            shown_live = shown_live[:-1]
        else:
            shown_deferred = shown_deferred[:-1]
        cap = build(shown_live, shown_deferred)
    return cap


def render_capsule(session_id, latest_operator_turn, max_tokens=3000):
    """Render a fresh capsule from the live registry (see `_render`)."""
    return _render(latest_operator_turn, registry_view(), max_tokens=max_tokens)


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
    body = _render(turn, view, max_tokens=max_tokens) + "\n"
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
