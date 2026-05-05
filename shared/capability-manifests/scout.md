# Capability Manifest: Scout

Status: draft
Owner: security namespace
Canonical specialist: `departments/security/specialists/scout.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-scout/0.1.0/`

## Role Contract

Scout owns bounty/program recon, target scope reading, asset inventory, attack-surface mapping, and chain-potential seeding. It operates before `security-analyst`, `exploit-developer`, and `impact-validator`. It does not author findings, write PoCs, score impact, or submit reports.

## Preserved From Current Specialist

- Bounty Mode Phase 2/3 ownership.
- Scope gate before probing.
- Passive and active recon distinction.
- Fanout to `security-analyst` for static/deep analysis and Research for OSINT-heavy context.
- Multi-model optional coverage for high-value recon.

## Preserve From Old Plugin

### Required Tool Surface

- Passive recon: `subfinder_scan`, `amass_scan`, `bbscope_fetch`, `paramspider_scan`, `uro_dedupe`, `gitdorker_scan`, `spiderfoot_scan`, `waybackurls_fetch`.
- Active recon after scope gate only: `katana_crawl`, `gowitness_capture`, `naabu_portscan`, `nuclei_scan`, `nuclei_scan_list`.
- Scope and intel: `scope_check`, `program_intel_query`.

### Shared Tool Surface

- `httpx_probe`
- `dig_query`
- `whois_lookup`
- `playwright_navigate`
- `playwright_screenshot`
- `docker_run`
- `gh_api`
- `http_get`

### Skills

- `api-surface-mapper`
- `github-recon`
- `nuclei-scan`
- `program-intel-query`
- `recon-chain-orchestrator`
- `scope-gate`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> program/scope gate -> passive recon -> dedupe -> active recon only if scoped -> chain-potential annotations -> record -> handoff
```

Required behavior:

- Never probe before scope-gate completes.
- Prefer passive recon first.
- Deduplicate URLs/assets before handoff.
- Annotate high-value assets with chain potential.
- If scope rules are ambiguous, stop for operator decision.
- If program intel says a candidate class is not accepted, surface early instead of wasting downstream effort.

## Output Contract

Return a structured report with:

- `ok`
- `asset_manifest`
- `total_assets`
- `chain_seeds`
- `scope_decisions`
- `program_intel`
- `kg_finding_id`
- `suggested_next_stage`
- missing-capability list when tools are unavailable

## KG And Memory Behavior

- Recall target/program history before recon.
- Record attempt before enumeration.
- Record final asset manifest and chain-potential notes.
- Never self-promote assets or findings to confirmed vulnerability status.

## Safety Boundaries

- No vulnerability findings or PoCs.
- No CVSS/severity scoring beyond chain-potential labels.
- No active scanning before explicit in-scope confirmation.
- No submission to bounty platforms.
- No smart-contract-specific audit work.

## Live Dispatch Proof

Minimum production proof:

1. Chrono dispatches a sanitized local/safe target or fixture scope to security namespace.
2. security namespace selects `scout`.
3. Specialist runs scope-gate plus one passive recon/categorization capability or returns structured missing-tool output.
4. Response includes asset/scope evidence and suggested next stage.
5. Active registry closes.
6. Chrono summarizes whether `security-analyst` should run next.

## Public/Private Disposition

- Public: scope-gate rules, tool expectations, sanitized fixture behavior, output schema.
- Private/local: bounty platform sessions, target lists, program intel, authenticated browser state, API keys.

## Cleanup Disposition

Do not delete old plugin source until:

- this manifest is complete
- current scout specialist is updated from it
- scope-gated live dispatch proof passes
- bounty/private target artifacts are quarantined outside public repo
