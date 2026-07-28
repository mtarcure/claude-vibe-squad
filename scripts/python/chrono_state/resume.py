"""Bounded, source-tagged Chrono resume capsule.

Regenerated from the decision-authority record + the bounded task registry (never a
summary-of-a-summary). Every line carries a source ID ([DEC-...] / [TASK-...]) so the
capsule is a cache pointing at authority, never authority itself. This becomes the new
content of `current.md`: a thin derived cursor, not a narrative log.
"""

from __future__ import annotations

from chrono_state.registry import load_active
from chrono_state.decisions import active_decisions


def render_capsule(session_id, latest_operator_turn, max_tokens=3000):
    """Build a token-bounded capsule. Drops oldest tasks first under pressure;
    active decisions and the latest operator instruction are never dropped."""
    decs = active_decisions()
    tasks = load_active()

    def build(task_list):
        lines = ["# Chrono resume capsule", "", "## Active decisions"]
        lines += [f"- {d['statement']} [{d['decision_id']}]" for d in decs] or ["- (none)"]
        lines += ["", "## Active / blocked tasks"]
        lines += [
            f"- {t['state']}: {t.get('next_action', '?')} [{t['id']}]" for t in task_list
        ] or ["- (none)"]
        lines += ["", "## Latest operator instruction", f"- {latest_operator_turn}"]
        return "\n".join(lines)

    cap = build(tasks)
    # hard token bound (~4 chars/token): drop oldest tasks first, rebuild, re-check.
    while len(cap) // 4 > max_tokens and tasks:
        tasks = tasks[:-1]
        cap = build(tasks)
    return cap
