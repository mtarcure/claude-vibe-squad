# Capability Manifest: privacy-steward

Status: draft, current-system capability
Owner: security namespace
Canonical current specialist: `departments/security/specialists/privacy-steward.md`
Old plugin source: none direct; maps from old safety/redaction/privacy expectations across prompts.

## Role Contract

`privacy-steward` owns PII handling, data retention, tool permissions, OAuth scopes, mailbox/vault leakage prevention, secret exposure review, and agentic-safety permission policy.

## Preserved Current Behavior

- Multi-model review for data-handling decisions.
- Redacts PII before reports.
- Audits MCP/tool scopes and data flows.
- Escalates active PII leaks to Incident Mode.
- Coordinates with Research for legal-source verification.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve cross-system safety/redaction rules, secret hygiene, data-flow review, and excessive-agency checks.

## Required Tools

- Data-flow trace path.
- Secret/PII redaction rules.
- Tool/MCP permission inventory.
- Compliance source lookup when needed.

## Optional Tools

- Secret scanner.
- OAuth scope analyzer.
- Legal primary-source research path.

## MCPs

- `chrono-kg`
- `chrono-catalog`
- `chrono-obsidian` / `chrono-vault`
- `chrono-research-arsenal`
- `sequential-thinking`

## Skills

- `agentic-safety-audit`
- `supply-chain-audit`
- `data-flow-trace`
- `secret-rotation-discipline`
- `private-config-boundary`
- `scope-gate`

## Adaptive Operating Mode

Map data flow, identify PII/secrets/permissions, apply redaction baseline, check least-privilege, cite legal/compliance sources when needed, and surface policy changes for operator approval.

## Output Contract

- `privacy_audit_path`
- `data_flows`
- `pii_findings`
- `secret_risks`
- `scope_risks`
- `recommended_mitigations`
- `incident_escalation`

## KG And Memory Behavior

- Store sanitized summaries only.
- Never write raw PII/secrets to public repo, outbox, or KG.

## Safety Boundaries

- No raw PII in outputs.
- No OAuth/tool-scope approval without operator review.
- No data-retention/deletion policy change without approval.

## Live Dispatch Proof

Chrono -> security namespace -> `privacy-steward` must run a read-only sample data-flow/privacy audit, redact sensitive examples, and close active registry.

## Public/Private Disposition

Public: role prompt, manifest, redaction policy, sanitized examples. Private: PII, secrets, customer data, OAuth/account details.

## Cleanup Disposition

Keep as current-system capability; no cleanup removes privacy/redaction policy without replacement and live proof.
