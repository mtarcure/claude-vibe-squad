# Demo run — a real specialist panel, captured end to end

This directory is a **real, unedited panel run** from Vibe Squad — the same
kind of run the [swarm demo](../../README.md) shows. Nothing here is mocked:
these are the actual artifacts the system produced when a panel reviewed a
small code change. It exists so you can inspect *exactly* what "parallel
specialists + one synthesized answer" means, file by file.

## What happened

```
  request: "review this change with a panel"
        │
        ▼
  synthesizer  (coordinator, claude lane)
        │  spawns two specialists in parallel — one dispatch, same start epoch
        ├────────────────────────┬───────────────────────────┐
        ▼                        ▼                            │
  code-reviewer            security-analyst                   │  ⚡ SWARM ×2
  (correctness lens)       (security lens)                    │  running concurrently
        │                        │                            │
        └────────────┬───────────┘                            │
                     ▼                                         │
        coordinator collects both returns, preserves each     │
        finding + severity, reconciles the one overlap  ───────┘
                     ▼
        panel-result.md   ← exactly one canonical artifact
```

The two reviewers ran **independently** — the coordinator did not tell them
what to look for. They surfaced **different** defects (security-analyst: a SQL
injection; code-reviewer: an unvalidated discount that can drive a cart total
negative), and **converged** on the same top fix from opposite directions.

## The concurrency is real, not a figure of speech

From [`panel-activity.json`](panel-activity.json) — the actual activity ledger:

- Both members were marked `running` at the **same epoch** (`1784027216`).
- Both member records span that shared start through epoch `1784027350`, so
  the ledger shows a concurrent 134-second batch rather than distinct
  per-member finish times.
- The panel closed at epoch `1784027351`, 135 seconds after its recorded start.
  This activity ledger records panel lifecycle and batch closure; it does not
  provide a measured serial baseline or prove a wall-clock speedup.
- Collection was deadline-bounded and closed on `quorum_met` (2/2 returned,
  0 timed out); the record was archived in the coordinator's `finally` path —
  one parent task, one artifact.

## The files

| File | What it is |
|------|-----------|
| [`reviewed-change.py`](reviewed-change.py) | The 24-line change under review (a promo-code discount function). |
| [`members/code-reviewer.md`](members/code-reviewer.md) | The **raw, unedited** return from the code-reviewer specialist. |
| [`members/security-analyst.md`](members/security-analyst.md) | The **raw, unedited** return from the security-analyst specialist. |
| [`panel-activity.json`](panel-activity.json) | The real activity ledger (start/end epochs, member states, quorum closure). |
| [`panel-result.md`](panel-result.md) | The **one** synthesized review the coordinator wrote from both returns. |

Read the two `members/*.md` files, then `panel-result.md`, and you can see the
synthesis is faithful: every member finding is preserved and attributed, the
single overlapping issue is reconciled (not double-counted or majority-voted),
and the coordinator adds the cross-cutting insight that one fix — parameterizing
the query — closes both a *security* finding and a *correctness* finding.

## Reproduce the shape yourself

The mechanism is [`shared/modes/panel.md`](../../shared/modes/panel.md); a panel
is dispatched with:

```bash
bin/send-task.sh <task-file> \
  --panel code-reviewer,security-analyst \
  --panel-policy evidence-synthesis --panel-quorum all --panel-timeout 900
```

The panel activity ledger + status rendering are covered by the tests in
[`daemon/tests/`](../../daemon/tests/) (`test_panel_activity.py`,
`test_vs_lane_status.py`), which run in CI.
