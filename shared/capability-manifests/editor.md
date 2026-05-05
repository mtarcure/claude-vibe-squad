# Capability Manifest: editor

Status: draft, current-system capability
Owner: content namespace
Canonical current specialist: `departments/content/specialists/editor.md`
Old plugin source: none direct in old `claude-chrono`.

## Role Contract

`editor` owns long-form editing, copywriting, structure/flow review, copy polish, and voice-aware revision. It improves text while preserving intent and verified claims; it does not publish or invent facts.

## Preserved Current Behavior

- Edits for clarity, structure, flow, grammar, and voice consistency.
- Hands brand ambiguity to `brand-voice`.
- Hands technical/factual disputes to `skeptic`, `research`, or source owner.
- Requires operator approval before publish-grade external commitments.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve current edit/copywriting/voice-check capability and its handoff to brand/research/skeptic.

## Required Tools

- Draft read/write path.
- Voice memory/review path.
- Citation/source validation path for factual claims.
- Edit notes artifact path.

## Optional Tools

- Grammar/style linting.
- Platform-specific copy length checks.

## MCPs

- `chrono-kg`: edit decisions and recurring voice notes.
- `chrono-obsidian` / `chrono-vault`: draft and memory references.
- `chrono-catalog`: skill/tool discovery.
- `sequential-thinking`: structural edit planning.

## Skills

- `writing-skills`
- `voice-consistency-audit`
- `cite-properly`
- `skill-description-trigger-authoring`

## Adaptive Operating Mode

Read target audience and voice constraints, preserve intent, edit for structure and clarity, flag unverifiable claims, ask brand/research/skeptic for unresolved issues, provide edit notes when changes are structural.

## Output Contract

- `edited_draft_path`
- `edit_notes_path`
- `voice_consistency`
- `claim_flags`
- `approval_required`

## KG And Memory Behavior

- Record durable voice lessons only after approval.
- Do not store private drafts publicly.

## Safety Boundaries

- No publishing.
- No fabricated facts or citations.
- No legal/market positioning commitments without approval.
- No overriding operator voice.

## Live Dispatch Proof

1. Chrono dispatches an editing task to content namespace.
2. content namespace dispatches `editor`.
3. Specialist returns edited draft plus notes or missing-source flags.
4. Outbox records approval gates for external publication.
5. Active registry closes.

## Public/Private Disposition

Public repo may ship prompt, manifest, and sanitized samples. Private drafts, client copy, and unpublished campaigns stay local/private.

## Cleanup Disposition

Keep as current-system capability; no cleanup removes content review, edit notes, or voice-aware handoff behavior.
