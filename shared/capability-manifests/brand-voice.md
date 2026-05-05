# Capability Manifest: brand-voice

Status: draft, current-system capability
Owner: content namespace
Canonical current specialist: `departments/content/specialists/brand-voice.md`
Old plugin source: none direct in old `claude-chrono`.

## Role Contract

`brand-voice` owns tone, positioning, voice memory, audience fit, and voice consistency. It reviews or establishes what a brand would say and what it should avoid.

## Preserved Current Behavior

- Uses content namespace memory for voice anchors.
- Requires evidence for audience claims.
- Proposes voice pivots to operator.
- Coordinates with editor, social-strategist, designer, and research.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve current voice-memory and content-review capability, especially the `voice-consistency-audit` skill path used by editor/content mode.

## Required Tools

- Brand memory read/write path.
- Prior approved/rejected content comparison.
- Voice review artifact path.
- Source/citation path for audience claims.

## Optional Tools

- Audience research via research namespace.
- Engagement analytics import.

## MCPs

- `chrono-kg`: voice findings and approved anchors.
- `chrono-obsidian` / `chrono-vault`: Content memory and artifacts.
- `chrono-catalog`: skill availability.
- `sequential-thinking`: positioning tradeoffs.

## Skills

- `writing-skills`
- `voice-consistency-audit`
- `cite-properly`
- `skill-description-trigger-authoring`

## Adaptive Operating Mode

Read voice anchors, compare draft or strategy against approved examples and anti-patterns, cite any audience/market claims, suggest concrete revisions, and surface structural voice pivots for operator approval.

## Output Contract

- `voice_review_path`
- `tone_fit`
- `vocabulary_fit`
- `structure_fit`
- `specific_rewrites`
- `approval_required`

## KG And Memory Behavior

- Record only operator-approved voice anchors as durable memory.
- Preserve rejected examples as anti-patterns when approved.
- Do not overwrite voice memory without approval.

## Safety Boundaries

- No fabricated audience data.
- No voice pivot without approval.
- No publishing.
- No imposing model voice over operator voice.

## Live Dispatch Proof

1. Chrono dispatches voice review to content namespace.
2. content namespace dispatches `brand-voice`.
3. Specialist reads current memory or reports missing anchors.
4. Outbox includes voice fit and concrete revision evidence.
5. Active registry closes.

## Public/Private Disposition

Public repo may ship role prompt, manifest, and sanitized voice review examples. Real brand/customer voice memory stays local or client-private.

## Cleanup Disposition

Keep this current-system role because content quality depends on voice memory; no cleanup removes voice anchors or review flow without disposition.
