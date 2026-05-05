# Capability Manifest: skeptic

Status: draft, preserve before cleanup
Owner: Shared / all Leads
Canonical current specialist: `shared/specialists/skeptic.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-skeptic/0.1.0/`

## Role Contract

`skeptic` owns epistemic audit, cross-model verification, confidence-stamped verdicts, source triangulation, and council/adversarial review. It verifies claims; it does not fix, rescore, submit, or author final reports.

## Preserved Current Behavior

- Runs standard cross-model verification.
- Preserves writer-family exclusion.
- Absorbs challenger/council behavior for high-stakes disputes.
- Produces confidence-stamped verdicts with minority opinions.

## Old Plugin Capabilities To Preserve

Old method-role dependencies:

- `chrono-dispatch` peer fan-out
- `chrono-kg` recall/record
- `chrono-catalog` tool status/listing
- `sequential-thinking` for high-stakes claim decomposition

Old skills:

- `source-triangulation`
- `chain-atomicity-verify`
- `cross-model-verification`
- `claim-confidence-ladder`
- `adversarial-review-prompt`
- `diff-atomicity-verify`
- shared `adversarial-review`

## Required Tools

- Multi-model peer verification path.
- Source/evidence inspection path.
- KG verdict record path.
- Council/stance fan-out path for escalations.

## Optional Tools

- Dedicated dispatch MCP parallel fan-out.
- Benchmark reproduction helper for deterministic claims.

## MCPs

- `chrono-kg`
- `chrono-catalog`
- `chrono-vault` / `chrono-obsidian`
- `sequential-thinking`
- dispatch/peer-consult surface where available

## Skills

- `source-triangulation`
- `claim-confidence-ladder`
- `adversarial-review-prompt`
- `adversarial-review`
- `preserve-outliers`
- `severity-vocabulary`

## Adaptive Operating Mode

Recall prior verdicts, decompose claims into atomic subclaims, verify direct evidence first, fan out to independent model families for inferred/proposed claims, preserve dissent, emit confidence tier, and return to requesting role.

## Output Contract

- `verdict_tier`
- `confidence`
- `evidence_trail`
- `dissent_log`
- `consult_peer_calls`
- `minority_opinions`
- `recommendation`
- `kg_finding_id`

## KG And Memory Behavior

- Record confidence-stamped verdicts.
- Do not repeat exact prior verdicts without checking freshness.
- Preserve dissent as useful signal.

## Safety Boundaries

- No code patches.
- No scanner/exploit work.
- No direct operator escalation except through requesting Lead/Chrono.
- No severity override; confidence-stamp only.

## Live Dispatch Proof

1. Chrono dispatches a claim review to a Lead.
2. Lead invokes `skeptic`.
3. Specialist uses multi-model or structured missing-provider path.
4. Outbox includes verdict, confidence, evidence, and dissent.
5. Active registry closes.

## Public/Private Disposition

Public repo may ship prompt, manifest, council schema, and sanitized examples. Private model outputs and client/source evidence stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-skeptic` or challenger-equivalent assets until current skeptic preserves cross-model, council, confidence, and dissent behavior.
