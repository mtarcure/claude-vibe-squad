# Capability Manifest: shared-common-skills

Status: draft, required prompt/markdown foundation
Owner: sysmgmt namespace with all Leads
Canonical current surface: `shared/skills/*.md`, specialist skill lists
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-shared-common-skills/0.1.0/`

## Role Contract

`shared-common-skills` is the markdown-first reusable skill library that keeps behavior in prompts/instructions rather than Python systems.

## Preserved Current Behavior

- Specialists cite skills by name.
- Skills are markdown instructions and lightweight checklists.
- Catalog/validators should ensure cited skills exist.

## Old Plugin Capabilities To Preserve

Old shared plugin included `RESOLVER.md`, used to resolve shared skill references. Preserve shared-skill resolution, no duplicate role-local forks, and canonical skill reuse.

## Required Tools

- Skill file lookup.
- Cited-skill existence validator.
- Shared-vs-role-specific classification.

## Optional Tools

- Skill generation/install tooling.
- Skill trigger validation.

## MCPs

- `chrono-catalog`
- `chrono-kg` for recurring skill lessons

## Skills

This surface owns all shared skills under `shared/skills/` plus old shared common skill concepts such as `severity-vocabulary`, `adversarial-review`, and `dispatch-vs-inline` when present.

## Adaptive Operating Mode

Keep skills small, composable, markdown-first, cited by specialists, and validated for existence. Add scripts only as rails, not as the behavior source.

## Output Contract

- `skill_inventory`
- `missing_skills`
- `duplicate_skills`
- `deprecated_skills`

## KG And Memory Behavior

- Promote recurring lessons to skills only after review.
- Do not embed private memory in public skill docs.

## Safety Boundaries

- No stale skill citation.
- No private/client details in shared skills.
- No generated drift between canonical and copied skills.

## Live Dispatch Proof

Specialist validation must confirm cited skills exist and live dispatches must demonstrate at least one non-basic skill path per major chain.

## Public/Private Disposition

Public: shared skill markdown. Private: local memories/examples if sensitive.

## Cleanup Disposition

Do not remove old shared skill resolver/assets until current validator and catalog cover skill discovery and drift.
