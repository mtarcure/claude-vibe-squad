---
name: compact-now
description: Operator-triggered proactive compaction — brain externalizes load-bearing state to KG before invoking Claude Code's native /compact. Use when operator says "/compact-now" or when proactive_compaction advisory has surfaced.
type: skill
---

# /compact-now

Brain-side proactive compaction. Operator triggers via slash phrase. Brain:
1. Calls the coordinator's proactive-compaction policy helper to confirm safety.
2. If blockers exist (in-flight dispatches, mid-stage), surfaces blockers to operator and asks confirmation to proceed anyway.
3. Externalizes load-bearing state to KG via `mcp__chrono_vault__record_finding` — captures: active dossier slug, current spec ID, unresolved risks, pending approvals, in-flight subagent results, last operator decision.
4. Snapshots the same state via the coordinator's compaction snapshot helper to `~/Obsidian-Chrono/chrono/_state/compaction/<session>.json`.
5. Invokes Claude Code's native `/compact` to trigger compaction.
6. After compact, brain reads the snapshot via the coordinator's compaction recovery helper and re-injects as recall on next operator turn.

## When to invoke

- Operator types `/compact-now` (explicit)
- Operator types `compact now` / `please compact` / `let's compact` in prose (intent-recognition)
- After brain has surfaced a `should_compact()` advisory and operator nudges affirmatively

## When NOT to invoke

- In-flight dispatches running — surface blockers first
- Mid-stage (brain still processing) — wait for stage boundary
- Below 120k token threshold — no benefit, just cost

## Implementation

Brain runs this skill inline (not a subagent dispatch). The KG-write step uses brain's existing MCP access; the `/compact` invocation is a Claude Code native primitive that fires `PreCompact` (chrono's existing snapshot hook).

```python
# Brain pseudocode (inline, not dispatched)
from coordinator_compaction_policy import should_compact
from coordinator_compaction_snapshot import snapshot

advisory = should_compact(
    token_estimate=current_context_estimate,
    stage_state=current_stage,
    in_flight=current_in_flight_dispatches,
)

if advisory["blockers"]:
    surface_to_operator(f"Blockers: {advisory['blockers']}. Proceed anyway?")
    if not operator_confirms:
        return

state = {
    "dispatched": last_dispatched,
    "last_decision": last_decision,
    "active_dossier": active_dossier,
    "pending_approvals": pending_approvals,
    "active_stage": current_stage,
    "current_spec_id": current_spec_id,
    "unresolved_risks": unresolved_risks,
    "next_action": next_action,
}

# Externalize to KG (brain-side MCP call)
mcp__chrono_vault__record_finding(
    role="brain",
    canonical_name=f"compact-now-{session_id}",
    summary=f"Pre-compact externalization: {state['next_action']}",
    body=json.dumps(state, indent=2),
    severity="info",
)

# Snapshot to JSON (hook also persists this on /compact, but eager-write is safer)
snapshot(session_id, state)

# Invoke Claude Code native compact (fires PreCompact hook → snapshot again → compact)
trigger_native_compact()
```

## Cross-references

- Policy module: coordinator-side proactive compaction helper
- Snapshot module: coordinator-side compaction snapshot helper
- PreCompact hook: `.claude/settings.json:24`
- Research synthesis: `docs/phase8-proactive-compaction-research.md`
