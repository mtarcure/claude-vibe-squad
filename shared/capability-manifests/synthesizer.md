# Capability Manifest: synthesizer

Status: draft, preserve before cleanup
Owner: research namespace
Canonical current specialist: `departments/research/specialists/synthesizer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-synthesizer/0.1.0/`

## Role Contract

`synthesizer` aggregates parallel specialist/model trajectories into a unified report while preserving outliers, contradictions, provenance, and confidence. It does not do original research, fix issues, scan targets, or silently resolve disputes.

## Preserved Current Behavior

- Preserves minority reports.
- Tags model/provider/source provenance.
- Explicitly surfaces contradictions.
- Aggregates multi-model outputs without lossy averaging.
- Hands unresolved disputes back to research or skeptic.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `synthesize`
- `consult_peer`

Old required method:

- deterministic cluster aggregation before narrative synthesis
- outlier detection
- contradiction preservation
- provenance map
- KG record with outlier count

## Required Tools

- Structured input aggregation path.
- Provenance-preserving merge/dedup path.
- Peer consult path for contradiction tiebreakers.
- KG record path.

## Optional Tools

- Deterministic aggregation helper.
- Multi-model disagreement matrix renderer.

## MCPs

- `chrono-kg`: recall prior synthesis and record final report.
- `chrono-catalog`: skill/tool discovery.
- `chrono-vault` / `chrono-obsidian`: artifact references.
- `sequential-thinking`: contradiction/outlier reasoning.

## Skills

- `preserve-outliers`
- `summarize-findings`
- `evidence-level`
- `cross-file-relationship-synthesis`
- `cite-properly`

## Adaptive Operating Mode

Recall prior context, read all input trajectories, aggregate deterministically where possible, inspect every outlier, preserve disagreements, consult peers only for material contradictions, write consensus briefly, emphasize outliers, and record the synthesis artifact.

## Output Contract

Expected return shape:

- `consensus_block`
- `outliers_block`
- `disagreements`
- `open_questions`
- `outlier_count`
- `provenance_map`
- `kg_finding_id`
- `synthesis_path`

## KG And Memory Behavior

- Record synthesis attempts and final reports.
- Include outlier count and contradiction flags.
- Preserve source/trajectory attribution.

## Safety Boundaries

- No original claims beyond supplied inputs.
- No silent dropping of minority findings.
- No external network verification; route to research/skeptic.
- No final confirmation without operator/review gate.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches multiple research trajectories to research namespace.
2. research namespace dispatches `synthesizer`.
3. Specialist preserves provenance, consensus, outliers, and contradictions.
4. Outbox includes synthesis artifact and confidence caveats.
5. Any contradiction routes to research/skeptic instead of disappearing.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompt, manifest, skill references, and sanitized examples. Private trajectories and client/source packs stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-synthesizer` assets until current role preserves outlier-first synthesis, provenance, and contradiction handling.
