# Capability Manifest: planner

Status: draft, current-system capability
Owner: Shared / all Leads
Canonical current specialist: `shared/specialists/planner.md`
Old plugin source: none direct in old `claude-chrono`; closest ancestry is architect/design planning methodology.

## Role Contract

`planner` owns decomposition of multi-week or multi-component goals into phases, dependencies, milestones, risks, rollback paths, and open questions. It recommends plans; it does not decide for the operator or implement.

## Preserved Current Behavior

- Uses Claude + Codex multi-model planning.
- Preserves alternative decompositions before synthesis.
- Keeps plans at phase/file/workstream level, not line-by-line implementation.
- Surfaces clarifying questions when goal is too vague.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve current cross-cutting planning behavior and architect-adjacent boundary discipline.

## Required Tools

- Current-state/context read path.
- Multi-model planning or explicit missing-provider fallback.
- Plan artifact path.
- Risk/dependency/rollback schema.

## Optional Tools

- Issue tracker/project board export.
- Timeline/milestone visualization.

## MCPs

- `chrono-kg`: prior plans and decisions.
- `chrono-catalog`: specialist/mode capability lookup.
- `chrono-vault` / `chrono-obsidian`: plan artifact references.
- `sequential-thinking`: required for big plans and dependency analysis.

## Skills

- `goal-decomposition`
- `dependency-mapping`
- `rollback-planning`
- `risk-register`
- `dispatch-vs-inline`

## Adaptive Operating Mode

Clarify goal and constraints, recall prior plans, produce at least two useful decompositions when multi-model is available, synthesize a practical phase plan, identify dependencies and rollback paths, and hand implementation to relevant Leads.

## Output Contract

- `plan_path`
- `phases`
- `dependencies`
- `milestones`
- `risks`
- `rollback`
- `open_questions`
- `confidence`

## KG And Memory Behavior

- Record accepted plans and major operator decisions.
- Do not overwrite active plan truth without operator approval.

## Safety Boundaries

- No implementation.
- No promised dates; estimates are ranges.
- No operator decision replacement.
- No over-detailed code plans that bypass architect/engineer roles.

## Live Dispatch Proof

1. Chrono dispatches a planning task.
2. Planner uses KG/catalog/sequential-thinking or reports missing-tool disposition.
3. Outbox includes phase plan, risks, dependencies, rollback, and open questions.
4. Active registry closes.

## Public/Private Disposition

Public repo may ship prompt, manifest, schemas, and sample plans. Client/product private roadmaps stay local/private.

## Cleanup Disposition

Keep as current-system cross-cutting capability. No cleanup removes planning prompts or schemas without explicit replacement.
