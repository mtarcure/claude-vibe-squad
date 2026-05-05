# Capability Manifest: social-strategist

Status: draft, current-system capability
Owner: content namespace
Canonical current specialist: `departments/content/specialists/social-strategist.md`
Old plugin source: none direct in old `claude-chrono`.

## Role Contract

`social-strategist` owns social distribution strategy, platform-specific adaptations, cadence, hooks, engagement planning, and campaign calendars. It drafts plans; it does not post without operator approval.

## Preserved Current Behavior

- Produces platform-specific plans and copy constraints.
- Coordinates with editor, brand-voice, content-creator, and research.
- Requires evidence for platform/audience claims.
- Surfaces new-platform launches and major strategy pivots.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve current social planning capability as a Content Mode support role.

## Required Tools

- Social plan/cadence artifact path.
- Brand voice and editor handoff path.
- Citation/source path for audience/platform claims.
- Approval gate for posting.

## Optional Tools

- Analytics import.
- Scheduler/export integration.

## MCPs

- `chrono-kg`: campaign findings and approved patterns.
- `chrono-obsidian` / `chrono-vault`: content calendar references.
- `chrono-catalog`: skill/tool discovery.
- `chrono-research-arsenal`: audience/platform research.
- `sequential-thinking`: campaign planning.

## Skills

- `writing-skills`
- `cite-properly`
- `voice-consistency-audit`
- `platform-adaptation`

## Adaptive Operating Mode

Read content and brand constraints, identify platform fit, draft hooks/cadence/calendar, cite audience/platform assumptions, coordinate asset/copy needs, and surface posting approval.

## Output Contract

- `social_plan_path`
- `cadence_calendar_path`
- `platform_drafts`
- `hook_strategy`
- `approval_required`

## KG And Memory Behavior

- Record approved patterns and campaign results when provided.
- Do not fabricate engagement metrics.
- Keep private account analytics local.

## Safety Boundaries

- No posting.
- No fabricated analytics.
- No cadence mandate; operator sets pace.
- No major positioning pivot without approval.

## Live Dispatch Proof

1. Chrono dispatches distribution task to content namespace.
2. content namespace dispatches `social-strategist`.
3. Specialist writes a platform plan with assumptions/citations.
4. Outbox includes approval-required posting state.
5. Active registry closes.

## Public/Private Disposition

Public repo may ship role prompt, manifest, and sanitized templates. Private account analytics, drafts, and campaign plans stay local/client-private.

## Cleanup Disposition

Keep as current-system capability if Content Mode remains in public product; no cleanup removes campaign planning without explicit disposition.
