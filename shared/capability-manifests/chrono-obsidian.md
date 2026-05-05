# Capability Manifest: chrono-obsidian

Status: draft, required local/private runtime for daily driver, optional public setup
Owner: sysmgmt namespace
Canonical current surface: `shared/api-catalog.md`, MCP config, Obsidian REST API bridge
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-_shared-chrono-obsidian/0.2.0/`

## Role Contract

`chrono-obsidian` bridges Vibe Squad to the operator's vault for note read/write, search, backlinks, index access, and vault hygiene. Public product ships setup docs and examples, not the live vault.

## Preserved Current Behavior

- Required for local daily-driver memory/vault workflows.
- Used by memory, knowledge, research, and documentation roles.
- Must respect path sandbox and private config boundaries.

## Old Plugin Capabilities To Preserve

Old wrapper surface:

- `get_index`
- `obsidian_cli`
- `path_sandbox`

Old shared tool concepts:

- vault list/read/write/search
- backlinks/dataview/health check when available

## Required Tools

- Vault health/read/search path.
- Write path with sandboxing.
- API auth check.
- Private/public path boundary.

## Optional Tools

- Dataview/backlinks advanced queries.
- Full index cache.

## MCPs

- `chrono-obsidian`: local vault bridge.
- `chrono-vault` / `chrono-kg`: related memory surfaces.
- `chrono-catalog`: availability metadata.

## Skills

- `obsidian-kg-navigation`
- `kg-vault-health-check`
- `private-config-boundary`

## Adaptive Operating Mode

Check vault/API health first, enforce sandbox, read/write only scoped notes, record missing auth/path errors clearly, and never treat live vault contents as public product source.

## Output Contract

- `registered`
- `reachable`
- `auth_ok`
- `usable`
- `vault_path`
- `sandbox_status`
- `issues`

## KG And Memory Behavior

- Vault notes are local/private by default.
- Sanitized examples may be copied to `examples/`.

## Safety Boundaries

- No vault deletion without approval.
- No secret/API key output.
- No path traversal outside approved vault roots.

## Live Dispatch Proof

MCP audit must check reachability/auth/usability, and memory/knowledge live tests must perform read-only or sample-safe vault behavior.

## Public/Private Disposition

Public: setup docs, schemas, examples. Private: operator vault, API key, live notes.

## Cleanup Disposition

Do not delete old shared Obsidian plugin assets until current MCP audit and docs cover path sandbox, health, read/search/write behavior.
