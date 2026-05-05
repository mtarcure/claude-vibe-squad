# Capability Manifest: architect

Status: draft, preserve before cleanup
Owner: coding namespace
Canonical current specialist: `departments/coding/specialists/architect.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-architect/0.1.0/`

## Role Contract

`architect` owns bounded design artifacts, service boundaries, C4 diagrams, interface contracts, data model contracts, and design-risk tradeoffs. It does not implement, test, deploy, submit PRs, or make final major design decisions without review.

## Preserved Current Behavior

- Produces design artifacts, not production code.
- Keeps architecture outputs bounded and actionable.
- Uses structured boundary/interface skills.
- Requires adversarial or challenger review for major boundary decisions.
- Hands implementation to engineering specialists.

## Old Plugin Capabilities To Preserve

Old plugin was a method-role without a role-specific MCP server. Preserve:

- `c4-model-authoring`
- `boundary-design`
- `data-model-contract`
- `interface-ambiguity-check`
- Structurizr CLI usage when available.
- Mermaid fallback when Structurizr is absent.
- Shared `spec-to-code-compliance` and `adversarial-review`.
- Dispatch/review with challenger or research when needed.

## Required Tools

- Markdown artifact writing path.
- Diagram path: Structurizr CLI or Mermaid fallback.
- Source/spec inspection path.
- Review path through challenger/skeptic or equivalent adversarial specialist.

## Optional Tools

- Structurizr CLI validation.
- GitHub API inspection of existing API contracts.

## MCPs

- `chrono-kg`: recall prior ADRs/designs and record design findings.
- `chrono-catalog`: verify tool/skill availability.
- `chrono-vault` / `chrono-obsidian`: persist design artifacts and references.
- `sequential-thinking`: explicit design tradeoff reasoning.
- Dispatch surface for `research` and `challenger` where available.

## Skills

Current or old skills to keep represented:

- `boundary-design`
- `data-model-contract`
- `c4-model-authoring`
- `interface-ambiguity-check`
- `dependency-cycle-audit`
- `spec-to-code-compliance`
- `adversarial-review`

## Adaptive Operating Mode

Read requirements, recall prior decisions, resolve interface ambiguity first, compare at least two options for non-trivial boundaries, author a bounded artifact with a diagram, run challenger/adversarial review, then record risks and next-stage recommendation.

## Output Contract

Expected return shape:

- `artifact`: `architecture.md`, `design.md`, `boundary_decisions.md`, or `compliance_delta.md`
- `artifact_path`
- `diagram_path` when applicable
- `challenger_reviewed`
- `open_risks`
- `kg_finding_id`
- `suggested_next_stage`

## KG And Memory Behavior

- Recall prior design decisions before proposing new boundaries.
- Record design attempts and finalized design findings.
- Include artifact path, design target, accepted risks, and challenger status.

## Safety Boundaries

- No production code, tests, deployment scripts, PR submission, or scanner execution.
- No unbounded architecture documents; split design if scope grows.
- No silent downgrade when diagram tooling is absent; record Mermaid fallback.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a design task to coding namespace.
2. coding namespace dispatches `architect`.
3. Specialist uses catalog, KG recall, and sequential-thinking for a bounded decision.
4. Specialist creates a small design artifact with Mermaid or Structurizr path.
5. Specialist records challenger/review status or structured missing-review blocker.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompts, skills, examples, and validator rules. Private customer specs, internal product design docs, and local KG memories stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-architect` assets until the current role preserves method skills, diagram fallback, challenger gate, and output contract.
