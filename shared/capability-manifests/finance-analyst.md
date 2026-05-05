# Capability Manifest: finance-analyst

Status: draft, current-system capability, local/private by default
Owner: sysmgmt namespace
Canonical current specialist: `departments/sysmgmt/specialists/finance-analyst.md`
Old plugin source: none direct in old `claude-chrono`; related surfaces are AgentOps cost/token monitoring and private operator workflows.

## Role Contract

`finance-analyst` owns read-only subscription, invoice, receipt, tax-document, budget, and spend-summary analysis. For Vibe Squad production readiness, its core public-relevant scope is token/cost/subscription awareness and anomaly surfacing. It has no transaction authority.

## Preserved Current Behavior

- Read-only by default.
- Tracks subscriptions, renewals, invoices, and spend summaries.
- Surfaces recurring charge and spend anomalies to the operator.
- Coordinates with `agentops` for CLI/model usage anomalies.
- Coordinates with `knowledge-librarian` for tax/document organization.

## Old Plugin Capabilities To Preserve

No direct old plugin existed for `finance-analyst`. Preserve current-system capability where it supports:

- token/cost usage review
- subscription health
- renewal awareness
- private financial document organization
- spend anomaly detection tied to runaway loops or model usage spikes

## Required Tools

- CSV parsing path.
- PDF/receipt text extraction path.
- Local markdown report writing path.
- Usage/cost summary path from CLI/provider reports when available.
- Secret redaction rules for financial data.

## Optional Tools

- Plaid integration, operator configured only.
- OCR for receipt images.
- Email/export ingestion, operator approved only.

## MCPs

- `chrono-kg`: sanitized anomaly records and recurring subscription findings.
- `chrono-obsidian` / `chrono-vault`: private report references.
- `chrono-catalog`: available parser/tool discovery.
- `sequential-thinking`: categorization/taxonomy decisions for ambiguous finances.

## Skills

Current or required skills:

- `financial-data-redaction`
- `subscription-audit`
- `spend-anomaly-detection`
- `token-cost-review`
- `binary-doc-to-markdown`
- `private-config-boundary`

## Adaptive Operating Mode

Identify data source and sensitivity, redact before summaries, normalize dates/amounts/categories, compare to baseline or renewal schedule, produce numbers and dates, surface actions as proposals only, and route operational model-usage anomalies to `agentops` and `harness-optimizer`.

## Output Contract

Expected return shape:

- `report_path`
- `period`
- `total_spend`
- `category_summary`
- `subscriptions`
- `renewal_warnings`
- `usage_or_token_anomalies`
- `redaction_applied`
- `operator_action_required`

## KG And Memory Behavior

- Store only sanitized summaries or references.
- Do not store account numbers, card numbers, bank credentials, raw statements, or private tax documents in public/product paths.
- Keep financial source files in local/private vault paths only.

## Safety Boundaries

- No transactions.
- No subscription cancellation without explicit operator action.
- No live banking access unless the operator configures and approves it for a specific task.
- No public commits of financial data.
- No lifestyle/spending judgment; report numbers and dates.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches token/cost or subscription audit task to sysmgmt namespace.
2. sysmgmt namespace dispatches `finance-analyst`.
3. Specialist uses sanitized sample data or reports missing private data/tooling.
4. Specialist produces a redacted report with numbers/dates and no transaction action.
5. Outbox includes privacy boundary and operator decision points.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship the role prompt, manifest, redaction schema, and sanitized examples. Real financial records, subscription invoices, provider account exports, and tax documents are local/private only.

## Cleanup Disposition

Keep this manifest because token/cost awareness is in product scope. Treat full personal finance workflows as optional local/private capability unless the public product explicitly supports them later.
