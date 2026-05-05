# Capability Manifest: chrono-kg

Status: draft, required core runtime
Owner: sysmgmt namespace
Canonical current surface: `shared/api-catalog.md`, `bin/mcp-audit.sh`, Chrono MCP config
Old plugin source: no standalone old plugin found; used by most old plugins as shared MCP.

## Role Contract

`chrono-kg` is the durable knowledge graph surface for recall, attempt records, findings, contradictions, and recurring system lessons. It is runtime infrastructure, not a specialist.

## Preserved Current Behavior

- Required by Leads and many specialists before significant work.
- Stores attempts/findings and recurring incidents.
- Supports cleanup and memory review through `memory-curator` and `agentops`.

## Old Plugin Capabilities To Preserve

Old plugins depended on `mcp__chrono_kg__recall`, `record_attempt`, and `record_finding`. Preserve recall-before-work and record-after-work behavior across roles.

## Required Tools

- MCP registration and reachability check.
- Recall/read path.
- Attempt/finding write path.
- Sanitized audit/report path.

## Optional Tools

- Graph visualization.
- Bulk migration/export.

## MCPs

- `chrono-kg`: required core.
- `chrono-vault`: paired backing surface where current implementation shares binary/namespace.
- `chrono-catalog`: verification metadata.

## Skills

- `kg-vault-health-check`
- `kg-integrity-gate`
- `stale-knowledge-purge`

## Adaptive Operating Mode

Treat KG as live memory support: recall before repeating work, record attempts/findings after evidence stabilizes, keep private memories out of public artifacts, and audit reachability nightly.

## Output Contract

- `registered`
- `reachable`
- `auth_ok`
- `usable`
- `last_audit`
- `issues`

## KG And Memory Behavior

- Never store raw secrets.
- Public repo ships schema/docs only, not live graph data.
- Memory deletion requires proposal and approval.

## Safety Boundaries

- No blind purge.
- No public commit of KG contents.
- No stale `verified: yes` claims without live audit.

## Live Dispatch Proof

`bin/mcp-audit.sh` must prove registration/reachability/usability, and at least one live dispatch proof per major chain must use KG recall or record a structured missing-tool disposition.

## Public/Private Disposition

Public: docs, config template, audit script. Private/local: live KG data, operator memories, findings, client data.

## Cleanup Disposition

Do not remove KG config, audit, or memory docs until replacement core memory surface passes live audit.
