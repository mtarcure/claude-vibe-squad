# Capability Manifest: Security Analyst

Status: draft
Owner: security namespace
Canonical specialist: `departments/security/specialists/security-analyst.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-security-analyst/0.1.0/`

## Role Contract

Security Analyst owns SAST, supply-chain review, OSINT/security analysis, and agentic-safety review. It receives recon from `scout`, returns structured findings, and hands confirmed vulnerability patterns to `exploit-developer` or `impact-validator`. It does not author exploits, score final impact, or run active probes without scope approval.

## Preserved From Current Specialist

- MCP-first behavior.
- Security-sensitive code review and bounty phase support.
- Fanout boundaries to `exploit-developer`, `impact-validator`, and Research.
- Operator gate for high-stakes or coordinated disclosure situations.
- Skills: `security-threat-model`, `supply-chain-audit`, `agentic-safety-audit`, `semgrep-rule-author`, `findings-filter`, `dependency-health-triage`, `osint-platform-audit`, `variant-analysis`, `security-ownership-map`.

## Preserve From Old Plugin

### Required Tool Surface

- Passive/local first: `semgrep_scan`, `semgrep_rule_add`, `gitleaks_scan`, `osv_scan`.
- Active/scope-gated: `nuclei_scan`, `ffuf_fuzz`, `sqlmap_scan`, `nmap_scan`, `nikto_scan`, `wpscan_scan`.
- Finding output: `submit_finding`, `emit_sarif`.
- Rule pack support: `apply_rule_pack`.
- Compliance/sieve support: `darnit_query`.

### Shared Tool Surface

- `httpx_probe`
- `docker_run`
- `dig_query`
- `gh_api`
- `playwright_navigate`
- `playwright_screenshot`
- `http_get`

### Skills

- `agentic-safety-audit`
- `dependency-health-triage`
- `findings-filter`
- `osint-platform-audit`
- `security-ownership-map`
- `security-threat-model`
- `semgrep-rule-author`
- `supply-chain-audit`
- `variant-analysis`
- `web-vuln/cache-poison`
- `web-vuln/idor`
- `web-vuln/jwt`
- `web-vuln/mass-assignment`
- `web-vuln/path-traversal`
- `web-vuln/sqli`
- `web-vuln/ssrf`
- `web-vuln/xss`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> passive scan -> filter false positives -> deepen finding -> pivot if no finding -> record -> handoff
```

Required behavior:

- Query prior target history before scanning.
- Prefer passive/local scans before active probing.
- Treat active scanners as disabled unless the dispatch includes an explicit scope/authorization frame.
- If Semgrep reveals a novel repeatable pattern, author or propose a custom rule.
- If dependency scan returns high-value CVEs, short-circuit lower-priority work and surface quickly.
- Apply `findings-filter` before any handoff.

## Output Contract

Return a structured report with:

- `ok`
- `findings`
- `total_findings`
- `sarif_path`
- `suggested_next_stage`
- evidence paths
- missing-capability list when tools are unavailable

## KG And Memory Behavior

- Recall target history before work.
- Record attempt before scans.
- Record surviving findings after false-positive filtering.
- Never self-promote findings to confirmed state without operator review.

## Safety Boundaries

- No exploit code or PoC payloads.
- No final CVSS scoring.
- No active network scanning without approved scope.
- No out-of-scope target expansion.
- No unapproved production changes or spend.

## Live Dispatch Proof

Minimum production proof:

1. Chrono dispatches a safe local fixture to security namespace.
2. security namespace selects `security-analyst`.
3. Specialist runs at least one passive capability (`semgrep`, `gitleaks`, or `osv`) or returns a structured missing-tool report.
4. Response includes evidence path and false-positive filtering status.
5. Active registry closes.
6. Chrono summarizes the result.

## Public/Private Disposition

- Public: role contract, safety boundaries, skills, expected tools, output schema.
- Private/local: target histories, findings, SARIF outputs, bounty program data, API keys, auth/session artifacts.

## Cleanup Disposition

Do not delete old plugin source until:

- this manifest is complete
- current specialist file is updated from it
- live dispatch proof passes
- required tools are either installed, documented optional, or reported as missing in doctor
