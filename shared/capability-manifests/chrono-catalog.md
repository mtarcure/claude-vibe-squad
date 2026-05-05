# Capability Manifest: chrono-catalog

Status: draft, required core runtime
Owner: sysmgmt namespace
Canonical current surface: `shared/api-catalog.md`, `bin/mcp-audit.sh`
Old plugin source: no standalone old plugin found; old roles depended on catalog self-discovery.

## Role Contract

`chrono-catalog` is the capability inventory surface: roles use it to discover available tools, skills, MCPs, and verification status at dispatch time.

## Preserved Current Behavior

- Specialists are instructed to use catalog self-discovery.
- Doctor/audit distinguishes registered from reachable/usable.
- Catalog text must not drift from actual setup.

## Old Plugin Capabilities To Preserve

Old role prompts repeatedly required `mcp__chrono_catalog__list_skills`, `list_tools`, and `tool_status`. Preserve skill/tool discovery and verified-status checks.

## Required Tools

- List skills/tools by role.
- Tool status probe.
- MCP availability metadata.
- Drift detection against manifests/API catalog.

## Optional Tools

- Generated inventory pages.
- Searchable plugin index.

## MCPs

- `chrono-catalog`: required core.
- `chrono-kg`: records catalog drift incidents.

## Skills

- `mcp-reachability-audit`
- `skill-description-trigger-authoring`
- `capability-inventory-audit`

## Adaptive Operating Mode

Use catalog as discovery, not proof. Pair catalog entries with live MCP/tool audit before claiming a capability is usable.

## Output Contract

- `registered`
- `reachable`
- `usable`
- `role_inventory`
- `drift_findings`

## KG And Memory Behavior

- Record drift incidents and fixes.
- Do not preserve stale `verified: yes` without live audit evidence.

## Safety Boundaries

- No fake capability claims.
- No public secrets in catalog.
- No removal of old capabilities without manifest disposition.

## Live Dispatch Proof

Each major live dispatch proof should call catalog or record missing-catalog status; `bin/mcp-audit.sh` must verify catalog reachability.

## Public/Private Disposition

Public: API catalog, manifests, setup docs. Private/local: provider secrets and live machine-specific status.

## Cleanup Disposition

Do not remove catalog scripts/docs until replacement inventory can prove registered/reachable/auth/usable states.
