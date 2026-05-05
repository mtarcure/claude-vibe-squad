# Capability Manifest: chrono-safety

Status: draft, required core policy surface
Owner: sysmgmt namespace with all Leads
Canonical current surface: `shared/lifecycle.md`, `shared/memory-discipline.md`, `shared/mode-cleanup.md`, `shared/modes/*.md`
Old plugin source: no standalone old plugin found; safety rules appear across old specialist prompts and shared skills.

## Role Contract

`chrono-safety` owns hard gates: operator approval, destructive-action prevention, secret hygiene, spending gates, live exploit limits, memory deletion gates, browser/session boundaries, and public/private repo separation.

## Preserved Current Behavior

- Operator approval required for destructive, spend, live exploit, deletion, and publishing actions.
- Secrets/private memory never ship publicly.
- Browser sessions and credentials stay local.
- Cleanup uses disposition/quarantine before deletion.

## Old Plugin Capabilities To Preserve

Preserve repeated old-prompt prohibitions: no live exploits outside scope, no production changes, no spending, no secret leakage, no unapproved deletion, no unsupported tool claims.

## Required Tools

- Approval token/state path.
- Secret/private pattern checks.
- Product hygiene checks.
- Mode-specific safety gates.
- Cleanup disposition manifests.

## Optional Tools

- Secret scanner.
- Policy-as-code validator.

## MCPs

- `chrono-kg` for incidents.
- `chrono-catalog` for verified status.
- `chrono-obsidian`/vault with private boundaries.

## Skills

- `secret-rotation-discipline`
- `private-config-boundary`
- `reversible-change-protocol`
- `tos-compliance-check`
- `rate-limit-respect`

## Adaptive Operating Mode

Default to proposal for high-risk actions, require explicit approval tokens, retain audit trail, quarantine before deletion, and escalate uncertain safety boundaries to the operator.

## Output Contract

- `gate`
- `status`
- `approval_required`
- `evidence`
- `blocked_action`
- `recovery_path`

## KG And Memory Behavior

- Record safety incidents and approvals.
- Do not store secrets in KG or public docs.

## Safety Boundaries

- This surface defines the safety boundaries; loosening them requires operator re-authorization.

## Live Dispatch Proof

Vibecoding-check and cleanup tests must prove unauthorized deletions and missing approvals block completion.

## Public/Private Disposition

Public: policy docs and checks. Private: approval files, secrets, local sessions.

## Cleanup Disposition

Do not remove safety docs/checks during simplification; consolidation must preserve gates.
