# Capability Manifest: content-creator

Status: current-system capability
Owner: content namespace
Canonical current specialist: `departments/content/specialists/content-creator.md`
Old plugin source: none direct in old `claude-chrono`.

## Role Contract

`content-creator` owns prose, campaign copy, draft narratives, and channel-specific text. Media generation moved to `media-producer`.

## Preserved Current Behavior

- Drafts and revises content from briefs and research packs.
- Flags unsupported claims and citation gaps.
- Coordinates with editor, brand-voice, social-strategist, designer, and media-producer.
- Keeps publishing/sending behind operator approval.

## Old Plugin Capabilities To Preserve

No direct old specialist plugin existed. Preserve current text-production behavior:

- long-form copy
- proposal/email draft copy
- campaign copy
- channel-specific variants
- handoff notes for media/design/review

## Required Tools

- `chrono-vault` / `chrono-obsidian` for sourced draft storage.
- `chrono-kg` for reusable audience/content learnings.
- Citation and claim-gap tracking.
- Clear handoff to `media-producer` for assets.

## Optional Tools

- Research handoff from research namespace.
- Brand voice memory.

## MCPs

- `chrono-kg`: generation findings and asset references.
- `chrono-catalog`: provider/tool availability.
- `chrono-vault` / `chrono-obsidian`: asset log references.
- `sequential-thinking`: complex content planning.

## Skills

- `writing-skills`
- `cite-properly`
- `skill-description-trigger-authoring`

## Adaptive Operating Mode

Clarify audience, channel, source requirements, voice, and desired action. Draft the minimum useful copy, mark citation gaps, and hand off polish/review/media work to the right specialists.

## Output Contract

- `draft_path`
- `channel_variants`
- `claim_gaps`
- `review_handoffs`
- `approval_required_before_publish_or_send`

## KG And Memory Behavior

- Record reusable audience/content learnings.
- Do not store private client/contact material publicly.

## Safety Boundaries

- No media generation.
- No publishing or sending.
- No unsupported factual claims.
- No private lead/client data in public repo.

## Live Dispatch Proof

1. Chrono dispatches a safe sample draft task to content namespace.
2. content namespace dispatches `content-creator`.
3. Specialist writes a draft and marks source gaps.
4. Outbox includes draft path, review needs, and approval gate.
5. Active registry closes.

## Public/Private Disposition

Public repo may ship role prompt, manifest, schemas, and sanitized examples. Private outreach/client drafts stay local.

## Cleanup Disposition

Keep this role for text generation. `media-producer` owns media/provider routes and provenance logging.
