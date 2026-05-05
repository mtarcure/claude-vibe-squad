# Capability Manifest: loop-operator

Status: draft, preserve before cleanup
Owner: sysmgmt namespace
Canonical current specialist: `departments/sysmgmt/specialists/loop-operator.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-loop-operator/0.1.0/`

## Role Contract

`loop-operator` owns safe autonomous loop operation: explicit stop conditions, checkpointing, stall detection, retry-storm prevention, progress telemetry, and intervention decisions. It supervises loops; it does not own the underlying specialist work.

## Preserved Current Behavior

- Refuses open-ended loops without success, max-iteration, wall-clock, and intervention rules.
- Checkpoints progress and creates resumable state.
- Stops on repeated no-progress or repeated identical errors.
- Surfaces operator decision points before budget/pathology risks escalate.

## Old Plugin Capabilities To Preserve

Old plugin method-role surface:

- Dispatch one loop iteration to an underlying specialist role.
- Record every loop iteration with stop-condition status and progress signal.
- Emit loop checkpoint events.
- Detect retry storms through KG recall and repeated signatures.
- Abort MCP retry-loop pathology.
- Pause at budget/wall-clock thresholds.

Old skills:

- `loop-checkpoint-protocol`
- `stall-detection`
- `safe-intervention`

Shared skills from old plugin:

- `chain-atomicity-verify`
- `dispatch-vs-inline`
- `severity-vocabulary`

## Required Tools

- Active task and dispatch log inspection.
- Checkpoint artifact path.
- Outbox/status writing path.
- Registry closure path through watcher, sweep, or manual close.
- Log diffing across loop iterations.

## Optional Tools

- Observability event emitter.
- Dedicated budget/token usage parser.
- Automated loop fixture test harness.

## MCPs

- `chrono-kg`: recall prior loops and record attempts/findings.
- `chrono-catalog`: discover available tools/skills and underlying specialist capability.
- `chrono-vault` / `chrono-obsidian`: checkpoint/report references.
- `sequential-thinking`: required for ambiguous stall-vs-progress judgment.

## Skills

Current or old skills to keep represented:

- `loop-checkpoint-protocol`
- `stall-detection`
- `safe-intervention`
- `chain-atomicity-verify`
- `dispatch-vs-inline`
- `severity-vocabulary`

## Adaptive Operating Mode

Recall similar loop signatures, validate stop conditions before starting, run one iteration at a time, checkpoint after each iteration, compare progress signals, continue only when progress is real and budgets allow it, pause or abort on stall/retry-storm/pathology, then record the terminal loop outcome.

## Output Contract

Expected return shape:

- `loop_outcome`: `success`, `stall-escalation`, `operator-pause`, `budget-exhaust`, or `retry-storm-abort`
- `iterations_completed`
- `terminal_stop_condition`
- `progress_signals`
- `escalation_rationale`
- `retry_storm_detected`
- `kg_finding_id`
- `awaiting_operator_decision`

## KG And Memory Behavior

- Recall prior loops before iteration one.
- Record every iteration attempt.
- Record terminal finding with iteration count, stop reason, and evidence.
- Route recurring stall patterns to `memory-curator` or `harness-optimizer` as proposals.

## Safety Boundaries

- No infinite loops.
- No loop without budget and stop conditions.
- No bypassing runaway guards.
- No direct product work in place of the looped specialist.
- No ambiguous continue decision when progress is unclear; pause and surface.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a bounded loop task to sysmgmt namespace.
2. sysmgmt namespace dispatches `loop-operator`.
3. Specialist validates stop conditions and uses KG recall.
4. Specialist runs or simulates one safe iteration with checkpoint output.
5. Outbox includes terminal status, progress evidence, and next decision.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompt, manifest, skills, loop schemas, and sanitized loop examples. Private loop artifacts, customer/client data, and live task transcripts stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-loop-operator` assets until the current role preserves stop-condition discipline, checkpointing, stall detection, and terminal reporting.
