# Capability Manifest: shared-common-tools

Status: draft, required tool inventory foundation
Owner: sysmgmt namespace with all Leads
Canonical current surface: `shared/api-catalog.md`, `bin/mcp-audit.sh`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-shared-common-tools/0.1.0/`

## Role Contract

`shared-common-tools` is the common tool inventory for safe reusable capabilities across roles. It documents and audits tools; it should not become a sprawling Python brain.

## Preserved Current Behavior

- Tool availability is declared in `shared/api-catalog.md`.
- MCP audit validates runtime state.
- Specialists use named tools when task shape matches.

## Old Plugin Capabilities To Preserve

Old wrapper surface:

- `dig`
- `docker`
- `elevenlabs_stt`
- `gh`
- `http`
- `httpx`
- `hwloc`
- `net`
- `npm`
- `playwright`
- `pnpm`
- `semgrep`
- `whois`

## Required Tools

- HTTP probe/fetch.
- GitHub API/CLI path.
- Docker path where needed.
- Playwright/browser path where needed.
- Tool status audit.

## Optional Tools

- semgrep, whois/dig/net tools for security.
- hwloc for systems/perf.
- npm/pnpm install helpers.
- ElevenLabs STT.

## MCPs

- `chrono-catalog`
- `chrono-kg`
- relevant optional tool MCPs by domain

## Skills

- `mcp-reachability-audit`
- `sandbox-provision-discipline`
- `rate-limit-respect`

## Adaptive Operating Mode

Prefer standard CLI/tooling over bespoke wrappers where possible, audit availability live, document missing optional tools, and consolidate scripts only after caller search and live proof.

## Output Contract

- `tool_inventory`
- `required_tools`
- `optional_tools`
- `missing_tools`
- `deprecation_candidates`

## KG And Memory Behavior

- Record recurring tool failures and fixes.
- Do not store auth tokens or raw env.

## Safety Boundaries

- No tool claims without verification.
- No installs/spend without approval.
- No private runtime artifacts in public tool docs.

## Live Dispatch Proof

Doctor/MCP audit plus major-chain smoke tests must demonstrate common tool availability or structured missing-tool reports.

## Public/Private Disposition

Public: tool docs and setup checks. Private: local auth state and provider keys.

## Cleanup Disposition

Do not delete old common tool wrappers until each tool is classified required/optional/deprecated/private/not shipped.
