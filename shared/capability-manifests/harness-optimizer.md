# Capability Manifest: harness-optimizer

Status: draft, preserve before cleanup
Owner: sysmgmt namespace
Canonical current specialist: `departments/sysmgmt/specialists/harness-optimizer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-harness-optimizer/0.1.0/`

## Role Contract

`harness-optimizer` owns the health of Vibe Squad's assistant harness: hooks, evals, model routing, context discipline, safety gates, prompt-cache discipline, and reversible harness improvements. It improves the system around specialist execution; it does not rewrite product code or specialist implementations.

## Preserved Current Behavior

- Audits hooks, evals, routing, context usage, and safety gates.
- Recommends minimal reversible changes as proposals.
- Coordinates with `memory-curator` when harness lessons should become durable instructions.
- Surfaces operator approval gates before high-blast-radius changes.

## Old Plugin Capabilities To Preserve

Old plugin method-role surface:

- Audit hook chains and config drift.
- Review eval baselines and stale eval coverage.
- Analyze model routing tables and lead/specialist tiering.
- Audit context discipline, token efficiency, cache warming, and progressive disclosure.
- Audit runaway, cost, and do-not-contact safety gates.
- Use observability before/after metrics for harness change validation.
- Use sequential thinking for multi-layer change-impact reasoning.

Old skills:

- `harness-baseline-audit`
- `leverage-area-identification`
- `reversible-change-protocol`

Shared skills from old plugin:

- `dispatch-vs-inline`
- `severity-vocabulary`
- `kg-integrity-gate`

## Required Tools

- File/config inspection path for launchers, hooks, prompts, specialist files, and model routing docs.
- Diff/proposal generation path.
- Validation path that can rerun a small representative task after a harness change.
- Observability/log review path for before/after metrics.

## Optional Tools

- Dedicated eval harness runner.
- MCP observability event emitter.
- Model usage/cache statistics parser.

## MCPs

- `chrono-kg`: recall prior harness audits and record findings.
- `chrono-catalog`: list currently available tools, skills, and model surfaces.
- `chrono-vault` / `chrono-obsidian`: durable proposal and audit artifact references.
- `sequential-thinking`: required for cross-layer harness changes.

## Skills

Current or old skills to keep represented:

- `harness-baseline-audit`
- `leverage-area-identification`
- `reversible-change-protocol`
- `dispatch-vs-inline`
- `severity-vocabulary`
- `kg-integrity-gate`
- `mcp-reachability-audit`
- `prompt-cache-hit-monitoring`

## Adaptive Operating Mode

Recall prior audits, baseline the target layer, identify no more than three leverage areas, draft minimal reversible changes, wait for operator approval when changes affect routing/prompts/hooks/safety, apply only approved changes, validate with a representative task, record measured deltas, and hand off any brain-trio changes to `memory-curator`.

## Output Contract

Expected return shape:

- `audit_layer`
- `baseline_scorecard`
- `leverage_areas`
- `proposed_changes`
- `applied_changes`
- `measured_deltas`
- `remaining_risks`
- `kg_finding_id`
- `awaiting_operator_approval`

## KG And Memory Behavior

- Recall recent audits before repeating work.
- Record audit attempts and final findings.
- Treat failed harness experiments as useful negative findings.
- Do not modify core instruction/memory files directly; route amendments through `memory-curator`.

## Safety Boundaries

- No product-code rewrites.
- No sweeping harness rewrites.
- No safety gate loosening without explicit operator re-authorization.
- No direct edits to `SOUL.md`, `CLAUDE.md`, goals files, or memory files.
- No high-blast-radius config change without approval and rollback notes.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a harness audit task to sysmgmt namespace.
2. sysmgmt namespace dispatches `harness-optimizer`.
3. Specialist uses catalog, KG recall, and sequential-thinking for a bounded layer.
4. Specialist drafts a reversible proposal and does not auto-apply it unless approved.
5. Outbox includes baseline, proposal, validation path, and operator gate status.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompt, manifest, skills, sanitized audit examples, and validator expectations. Private logs, operator corrections, usage traces, and local harness findings stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-harness-optimizer` assets until current SysMgmt docs, specialist prompt, catalog, and live proof preserve the audit/proposal/validation loop.
