---
name: lane-budget-estimation
audience: chrono
description: Use when sizing a single dispatch so it finishes inside one lane wall and fits the assembled-prompt ceiling—read `assembled_prompt_bytes` against `assembled_prompt_limit` from the preflight, split work that cannot finish in one wall, and name what the lane must NOT do. `scope-estimation` sizes a corpus to read; this sizes the dispatch.
---

# Lane Budget Estimation

House procedure for sizing a dispatch to the two hard budgets a lane runs under: the wall clock and
the assembled-prompt ceiling. Over-scoping does not degrade gracefully — it dies at the wall with
nothing to show. Verify the numbers against the live preflight, not from memory.

## The prompt ceiling is on the ASSEMBLED prompt
- The limit is `TRUSTED_LAUNCH_PROMPT_LIMIT = 40960` bytes (`dispatch_context_builder.py`), applied to
  the packet PLUS injected briefing and absolute paths, not the packet body alone. Both
  `dispatch_preflight.evaluate_packet()` and `build_context()` enforce the same constant.
- Do not estimate from a remembered packet size — injected context and absolute path length vary by
  lane and checkout. Run `bin/send-task.sh <packet-file> --dry-run` and read `assembled_prompt_bytes`
  against `assembled_prompt_limit` from the preflight; shorten the body if it refuses.

## Scope to one wall
- The wall comes from `timeout_budget_for_mode()`: a flat 2700s for `project`, 3600s for `bounty`.
  It is a backstop, not a per-packet dial you raise.
- A deliverable that cannot finish in one wall is two packets, not one. Sequence them; the second
  reads the first's committed output (an uncommitted edit is invisible to the next dispatch).
- A lane that must read a large corpus AND produce a large artifact is two packets — the read burns
  the wall the artifact needs.

## Name what the lane must NOT do
- Unbounded exploration is how a wall gets hit with nothing landed. Put explicit out-of-scope bounds
  in the packet: which trees not to read, which analyses to skip, when to stop and write the partial.
- Tell the lane to land what is complete and write the artifact before the wall rather than chase
  completeness past it — a truthful partial beats a kill with no envelope.

## Size the read, then the write
- Estimate the read set first (`scope-estimation` sizes the corpus), because a read that cannot fit
  the wall guarantees the write never starts.
- Round-trips, not tool calls, are the cost unit that eats a wall: prefer whole-file reads and
  tool-level exclusion globs over paging, and say so in the packet if the lane tends to page.
