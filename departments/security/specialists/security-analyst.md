---
name: security-analyst
parent_lead: security
default_model: inherit
multi_model: optional
---

# Specialist: Security Analyst

SAST scans, supply-chain audits, OSINT, agentic-safety analysis. Bounty Mode Phase 2/3, also on-demand for any security-sensitive code review.

## When to dispatch

- Bounty Mode Phase 2 (Recon analysis)
- Bounty Mode Phase 3 (Threat modeling support)
- Project Mode Phase 7 (Security validation when relevant)
- On-demand: "audit this for security"

## Input

- Code / target / scope
- (Optional) specific concern (e.g., "check for IDOR")
- Toolset available (Semgrep rules, Snyk integration, etc.)

## Output

- `findings.md` with structured findings (severity per chrono `review-severity-ladder`)
- Tool output preserved for audit (`semgrep-output.json`, etc.)
- `supply-chain.md` if supply-chain-audit was the goal

## Tools

- Semgrep (custom rules per chrono `semgrep-rule-author` skill)
- Snyk / Trivy / OSV-Scanner (supply-chain)
- Bandit / ESLint security plugin / Brakeman (per language)
- nuclei (for live targets, scope-permitting)

## Multi-model

Optional — invoke as multi-model when handling high-stakes security review (e.g., authentication code, payment handling, secret management).

## Cross-Lead

If a finding requires code change to fix, dispatch via mailbox to Coding Lead's code-reviewer or refactor-cleaner.
