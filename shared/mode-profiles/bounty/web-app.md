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

### Phase 1 Intelligence
- Read program scope, accepted vuln classes (often ranks XSS-Reflected lower than Stored)
- Check disclosure rules
- Tools: persistent browser session for platform pages

### Phase 2 Recon
- Subdomain enum (subfinder + amass)
- Endpoint discovery (gospider, paramspider, LinkFinder)
- Tech stack fingerprinting (wappalyzer)
- Wayback machine for historical URLs

### Phase 3 Threat Modeling
- Focus areas: auth flows, privilege boundaries, session management, input validation, CORS, CSP
- Tools: Burp Suite (manual + extensions like Autorize for IDOR)

### Phase 5/6/7 Exploitation
- Burp / mitmproxy for live testing
- nuclei for known-CVE patterns
- Manual testing for business-logic flaws (often highest-paying)
- Variant hunt: test same vuln class on adjacent endpoints

### Phase 9 Validation
- CVSS v4 against the platform's rubric
- Check NVD/OSV for similar CWE class historical scoring

### Phase 10 Report
- Submission format: HackerOne / Bugcrowd / Intigriti markdown templates
- Attach: HTTP request/response, video PoC if needed
- Persistent session for form-fill submission

## Specialists most active

- exploit-developer (multi-model)
- security-analyst
- scout
- skeptic (cross-cutting)
- impact-validator (CVSS scoring)

## Common pitfalls

- Self-XSS findings (need cross-context impact)
- Out-of-scope subdomains
- Duplicate of public disclosure
- Theoretical attack with no practical preconditions
