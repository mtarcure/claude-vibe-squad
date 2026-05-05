---
name: web-app
extends: bounty
status: active
---

# Bounty Profile: Web Application

For traditional web bounties — XSS, SQLi, IDOR, SSRF, auth bypass, business logic.

## Auto-detection signals

- URL on hackerone.com / bugcrowd.com / intigriti.com / hackenproof.com (general programs)
- Target is a web app (URL with login flow, API endpoints)
- File types: not directly applicable

## Phase customizations

### Phase 2 Program Scope
- Read program scope, accepted vuln classes (often ranks XSS-Reflected lower than Stored)
- Check disclosure rules
- Tools: persistent browser session for platform pages

### Phase 3 Recon
- Subdomain enum (subfinder + amass)
- Endpoint discovery (gospider, paramspider, LinkFinder)
- Tech stack fingerprinting (wappalyzer)
- Wayback machine for historical URLs

### Phase 4 Threat Modeling
- Focus areas: auth flows, privilege boundaries, session management, input validation, CORS, CSP
- Tools: Burp Suite (manual + extensions like Autorize for IDOR)

### Phase 6/7/8 Exploitation
- Burp / mitmproxy for live testing
- nuclei for known-CVE patterns
- Manual testing for business-logic flaws (often highest-paying)
- Variant hunt: test same vuln class on adjacent endpoints

### Phase 10 Validation
- CVSS v4 against the platform's rubric
- Check NVD/OSV for similar CWE class historical scoring

### Phase 11 Report
- Submission format: HackerOne / Bugcrowd / Intigriti markdown templates
- Attach: HTTP request/response, video PoC if needed
- Persistent session for form-fill submission

## Specialists most active

- security namespace invokes `exploit-developer` via `Task` tool with `subagent_type: exploit-developer` (multi-model)
- security namespace invokes `security-analyst` via `Task` tool with `subagent_type: security-analyst`
- security namespace invokes `scout` via `Task` tool with `subagent_type: scout`
- security namespace invokes `skeptic` via `Task` tool with `subagent_type: skeptic` (cross-cutting)
- security namespace invokes `impact-validator` via `Task` tool with `subagent_type: impact-validator` (CVSS scoring)

## Common pitfalls

- Self-XSS findings (need cross-context impact)
- Out-of-scope subdomains
- Duplicate of public disclosure
- Theoretical attack with no practical preconditions
