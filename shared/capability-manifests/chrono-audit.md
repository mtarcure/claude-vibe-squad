# Capability Manifest: chrono-audit

Status: draft, required product hygiene surface
Owner: sysmgmt namespace
Canonical current surface: `bin/doctor.sh`, `bin/mcp-audit.sh`, `bin/memory-audit.sh`, `bin/product-hygiene.sh`
Old plugin source: no standalone old plugin found; audit behavior is distributed across old harness, memory, and common tools.

## Role Contract

`chrono-audit` owns automated health and hygiene checks: MCP status, specialist validation, product hygiene, private/runtime file detection, memory audit, and CI-oriented drift checks.

## Preserved Current Behavior

- Doctor is the broad health entrypoint.
- MCP audit verifies real usability, not just registration.
- Product hygiene prevents runtime/private debris from shipping.
- Memory audit checks local/private boundaries.

## Old Plugin Capabilities To Preserve

Preserve audit concepts from old harness/memory/common plugins: baseline audit, KG/vault health, stale knowledge review, tool status probes, and reversible-change discipline.

## Required Tools

- Shell syntax/validator checks.
- MCP audit.
- Product hygiene/private pattern check.
- Specialist/manifest validation.
- Memory/vault boundary audit.

## Optional Tools

- Shellcheck.
- CI artifact reporting.
- Scheduled nightly/weekly runner.

## MCPs

- `chrono-catalog`
- `chrono-kg`
- `chrono-obsidian`
- required/optional MCPs under audit

## Skills

- `harness-baseline-audit`
- `mcp-reachability-audit`
- `kg-vault-health-check`
- `private-config-boundary`

## Adaptive Operating Mode

Run read-only checks first, classify warnings/issues, route fixes to owners, write audit artifacts, and block public release on secrets/runtime/private debris.

## Output Contract

- `issue_count`
- `warning_count`
- `checks`
- `artifacts`
- `owners`
- `release_blockers`

## KG And Memory Behavior

- Record repeated audit failures.
- Keep raw local audit logs private if they include paths/content.

## Safety Boundaries

- No destructive cleanup without approval.
- No secret output.
- No false pass from stale metadata.

## Live Dispatch Proof

Doctor and product hygiene must run locally and report zero release-blocking issues before v1 release.

## Public/Private Disposition

Public: scripts, schemas, CI checks, sanitized logs. Private: raw local logs and vault details.

## Cleanup Disposition

Do not remove audit scripts until equivalent CI/local checks exist and are documented.
