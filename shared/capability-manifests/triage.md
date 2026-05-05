# Capability Manifest: triage

Status: draft, preserve before cleanup
Owner: Shared / Chrono
Canonical current specialist: `shared/specialists/triage.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-triage/0.1.0/`

## Role Contract

`triage` owns classification, routing, severity/priority labeling, duplicate checks, and next-action recommendations for ambiguous incoming work. It routes; it does not approve, reject, rescore final severity, or submit findings.

## Preserved Current Behavior

- Classifies type/domain/severity.
- Recommends mode, Lead, and specialist.
- Checks duplicates in trackers/KG where available.
- Respects explicit operator routing overrides.

## Old Plugin Capabilities To Preserve

Old method-role dependencies:

- `chrono-dispatch` single/parallel consults.
- `chrono-kg` duplicate recall and decision records.
- `chrono-catalog` tool status/listing.
- `chrono_common_tools gh_api` for GitHub tracker checks.
- `sequential-thinking` before critical severity escalation.

Old skills:

- `severity-rubric`
- `severity-vocabulary`
- `duplicate-detection`
- `routing-heuristics`

Preserve Linear/Sentry/GitHub routing disposition from old plugin docs even if some tracker integrations are optional/private.

## Required Tools

- KG duplicate lookup.
- GitHub issue/search path.
- Routing table/specialist index lookup.
- Decision artifact path.

## Optional Tools

- Linear/Sentry integrations.
- Cross-model routing verification for low-confidence cases.

## MCPs

- `chrono-kg`
- `chrono-catalog`
- `chrono-vault` / `chrono-obsidian`
- `sequential-thinking`
- GitHub/issue-tracker tools where configured

## Skills

- `routing-heuristics`
- `severity-rubric`
- `duplicate-detection`
- `severity-vocabulary`

## Adaptive Operating Mode

Recall duplicate context, classify artifact and domain, assign priority/severity, check tracker/KG duplicates, recommend route, escalate critical/ambiguous/likely-duplicate cases, and record the triage decision.

## Output Contract

- `classification`
- `severity`
- `domain`
- `routing_recommendation`
- `duplicate_check`
- `confidence`
- `operator_action_required`
- `kg_finding_id`

## KG And Memory Behavior

- Record routing decisions and duplicate links.
- Do not create new work when a duplicate exists.
- Feed routing drift to harness-optimizer.

## Safety Boundaries

- No final severity override.
- No issue closure without operator confirmation.
- No bounty submission.
- No routing override against explicit operator instruction.

## Live Dispatch Proof

1. Chrono dispatches ambiguous intake to triage.
2. Triage checks KG/catalog and at least one tracker path or missing-tool disposition.
3. Outbox includes classification, route, confidence, and duplicate result.
4. Active registry closes.

## Public/Private Disposition

Public repo may ship prompt, manifest, schemas, and GitHub-based examples. Linear/Sentry/customer tracker details stay private/local.

## Cleanup Disposition

Do not delete old `chrono-plugin-triage` assets until current route/duplicate/severity behavior and tracker disposition are covered.
