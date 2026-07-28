---
name: compact-now
description: Operator-triggered proactive compaction — Chrono externalizes load-bearing state (active decisions, open tasks, next action) to a snapshot + a durable Vault learning note before invoking Claude Code's native /compact, then resumes from the snapshot. Use when the operator says "/compact-now" / "compact now" or when a should_compact() advisory has surfaced.
type: skill
---

# /compact-now

Chrono-side proactive compaction. The operator triggers via slash phrase. Chrono:

1. Calls `chrono_state.compaction.should_compact()` to confirm safety (over threshold, no in-flight work).
2. If blockers exist (in-flight dispatches), surfaces them to the operator and asks whether to proceed anyway.
3. Externalizes load-bearing state to the Vault via the current `record("learning", {...})` writer — captures active decisions (authority), open tasks, pending approvals, and the next action.
4. Snapshots the same state to `_state/chrono/compaction/<session>.json` via `chrono_state.compaction.snapshot()`.
5. Invokes Claude Code's native `/compact`.
6. After compact, reads the snapshot via `chrono_state.compaction.recover()` and re-anchors on the next operator turn — **never bulk-re-reading conversation history.**

## When to invoke

- Operator types `/compact-now` (explicit)
- Operator types `compact now` / `please compact` / `let's compact` in prose (intent-recognition)
- After Chrono has surfaced a `should_compact()` advisory and the operator nudges affirmatively

## When NOT to invoke

- In-flight dispatches running — surface blockers first
- Mid-task (Chrono still processing) — wait for a task boundary
- Below the `should_compact()` threshold — no benefit, just cost

## Implementation

Chrono runs this skill inline (not a subagent dispatch), operator-triggered. It uses the
`chrono_state` helpers (in `scripts/python/chrono_state/`) and Chrono's existing chrono-vault
MCP access. A `PreCompact` hook is OPTIONAL and only fires if `.claude/settings.json` declares
one — do not depend on it; externalize eagerly here.

```python
# Chrono inline (not dispatched)
import json, sys
sys.path.insert(0, "scripts/python")
from chrono_state.compaction import should_compact, snapshot   # noqa: E402
from chrono_state.registry import load_active                  # noqa: E402
from chrono_state.decisions import active_decisions            # noqa: E402

advisory = should_compact(
    token_estimate=current_context_estimate,
    in_flight=[t["id"] for t in load_active() if t.get("state") in ("running", "admitted")],
)
if advisory["blockers"]:
    surface_to_operator(f"Blockers: {advisory['blockers']}. Proceed anyway?")
    if not operator_confirms:
        return

state = {
    "next_action": next_action,
    "active_decisions": active_decisions(),   # AUTHORITY — not Vault evidence
    "active_tasks": load_active(),
    "latest_turn": latest_operator_turn,
    "pending_approvals": pending_approvals,
}

# 1) Durable Vault note via the CURRENT API — record(note_type, fields), NOT the stale
#    record_finding(role=, canonical_name=, ...) signature. fields require title/body/
#    target/attack_class; unknown fields are rejected.
mcp__chrono_vault__record("learning", {
    "title": f"compact-now externalization ({session_id})",
    "body": json.dumps(state, indent=2),
    "target": "chrono-orchestrator",
    "attack_class": "session-continuity",
    "keywords": ["compaction", "resume", "chrono"],
    "source_task": current_task_id,
})

# 2) Atomic snapshot to _state/chrono/compaction/<session>.json
snapshot(session_id, state)

# 3) Invoke Claude Code's native /compact
trigger_native_compact()

# 4) After compact: recover ONLY from the snapshot, never bulk-re-read history.
#    from chrono_state.compaction import recover; recover(session_id)
```

## Cross-references

- Policy + snapshot helpers: `scripts/python/chrono_state/compaction.py` (`should_compact`, `snapshot`, `recover`)
- Decision authority (separate from Vault): `scripts/python/chrono_state/decisions.py`
- Bounded task registry: `scripts/python/chrono_state/registry.py`
- Resume capsule generator: `scripts/python/chrono_state/resume.py`
- Vault writer API: `record(note_type, fields)` — see `plugins/chrono-vault/README.md`
- Resume canary (acceptance proof): `scripts/python/tests/test_resume_canary.py`
- PreCompact hook: OPTIONAL; only if `.claude/settings.json` declares one
