---
name: bounty-platform-report-format
description: "Use when authoring bounty findings for submission to HackerOne / Bugcrowd / Code4rena — provides per-platform expected report structure, severity rubric, and submission format."
source: "Distilled from HackerOne docs, Bugcrowd VRT documentation, and Code4rena report templates (public, REMAKE 2026-05-03)"
version: 1.0.0
applies_to:
  - departments/security/specialists/impact-validator
  - departments/security/specialists/scout (for pre-submission validation)
---

# Bounty Platform Report Format

Per-platform expected report structure for the operator's three highest-volume programs. Use *before* drafting a submission — picking the wrong template costs paid time on revisions and risks a "needs more info" close. Intigriti and HackenProof can extend this skill later; their report shapes are close to HackerOne's.

## Selection guide

| Target lives on | Use this section |
|-----------------|------------------|
| HackerOne program (h1.com) | HackerOne |
| Bugcrowd program (bugcrowd.com) | Bugcrowd |
| Code4rena contest (code4rena.com) | Code4rena |
| Multi-platform target (e.g., DeFi protocol with both H1 and Immunefi) | Pick by program, NOT by target. Each program has its own rubric. |

Verify the platform from the program URL before drafting — operators sometimes have multiple programs for the same target.

## HackerOne

### Report fields (mandatory)

1. **Title** — One line, format: `[Asset] [Vulnerability class] — [Concise impact]`. Examples:
   - `app.example.com — Stored XSS in profile bio leads to account takeover`
   - `API v2 — IDOR in /orders/{id} exposes other tenants' invoices`
2. **Asset** — Pick from the program's scope dropdown. Out-of-scope = auto-close.
3. **Weakness** — CWE selection from H1's list. Pick the most specific CWE; "Other" is a smell.
4. **Severity** — Use H1's CVSS v3.1 calculator (CVSS v4 may be available depending on program). Vector string is required, not just the score.
5. **Description** — What the vulnerability is. 1-2 paragraphs. Audience: a triager seeing the report cold; do not assume context.
6. **Steps to reproduce** — Numbered list, copy-pasteable. Each step is independently runnable. Include exact request bodies, headers, payloads. If a step requires UI, screenshot it.
7. **Impact** — What an attacker gains. Concrete: "an attacker can read PII for any user" beats "this could lead to data exposure". Quantify if possible (number of records, dollar amount, blast radius).
8. **Supporting material** — Screenshots, videos, request/response captures. **Attach files directly — H1 strips external links from media in many programs.**

### Optional but high-signal

- **References** — Prior CVEs, OWASP entries, related H1 reports (use the program-disclosed report URL format).
- **Affected components** — If the program has a structured asset list, tag the exact component.

### H1 best practices

- Reports cannot be edited after submission. Preview carefully.
- One report per vulnerability. Chained vulnerabilities go in *one* report only if the chain is the finding (otherwise, submit separately and cross-link).
- Don't share videos as external links (Drive, YouTube, etc.) — many programs reject linked media outright. Direct attachment only.
- Include a CVSS vector string, not just the severity name. Triagers re-score and your vector lets them check your reasoning fast.

### H1 CVSS calibration

CVSS v4 vector includes Vulnerable + Subsequent system impact axes. Follow `chrono.plugin.impact-validator/cvss-v4-gate` for scoring methodology. Cross-check against `nvd-osv-calibration` for the same CWE class.

## Bugcrowd

Bugcrowd uses VRT (Vulnerability Rating Taxonomy) priorities, not CVSS, as the primary severity signal. CVSS may be requested but VRT is the rubric that drives payout.

### VRT priorities

| VRT | Meaning | Examples |
|-----|---------|----------|
| **P1** | Critical | RCE, full account takeover (no user interaction), unauthenticated full DB access |
| **P2** | Severe | Stored XSS with session theft, IDOR exposing all users' PII, authenticated SQLi |
| **P3** | Moderate | Reflected XSS, CSRF on sensitive action, info disclosure with PII |
| **P4** | Low | Open redirect, weak crypto in transit, missing security headers (where impactful) |
| **P5** | Informational / Won't fix | Self-XSS, missing best-practice headers without exploitable impact, version disclosure |

VRT taxonomy is published at `bugcrowd.com/vulnerability-rating-taxonomy` (JSON downloadable, regularly versioned — current as of writing: 1.18). Use the published taxonomy as ground truth; your priority claim must match a VRT entry exactly.

### Report fields

1. **Title** — Same format as H1: `[Target] [Vuln class] — [Impact]`.
2. **VRT category** — Pick from Bugcrowd's taxonomy. The platform UI guides this; don't free-text.
3. **Severity** — Bugcrowd suggests a P-level based on the VRT match. Override only with explicit reasoning.
4. **Description** — Vulnerability explanation, 1-2 paragraphs.
5. **Steps to reproduce** — Same discipline as H1: numbered, copy-pasteable, independently runnable.
6. **Impact** — Concrete attacker capability. Bugcrowd triagers lean on impact narrative more than H1 — tell the story.
7. **Recommended remediation** — Optional but valued. Specific code-level or config-level fix beats generic advice.
8. **Attachments** — Screenshots / videos. Direct attachment preferred.

### Bugcrowd best practices

- VRT mismatch is the most common revision request. Get the category right or expect a downgrade.
- "Could lead to" framing weakens reports. Show the chain working end-to-end.
- Researchers can engage with triagers in-platform; respond promptly to clarification requests (response delay can stall payout).

## Code4rena

Code4rena is a contest platform for smart-contract audits, not a continuous bounty program. Reports are submitted per-contest with strict severity rules and judge-driven grading.

### Severity (per Code4rena rubric)

| Severity | Definition |
|----------|------------|
| **High (3)** | Assets can be stolen / lost / compromised directly. (Or indirectly with a valid attack path that does not rely on hand-wavy hypotheticals.) |
| **Medium (2)** | Assets not at direct risk, but the protocol's function or availability could be impacted. Or value leaked under a hypothetical attack path. |
| **Low / QA** | State-handling errors, spec violations, comment issues, governance/centralization concerns, code-style. Bundled into a single QA report per warden. |
| **Gas** | Gas optimizations. Bundled into a single Gas report per warden. |

Critical doesn't appear as a separate tier in current Code4rena rubric; it's collapsed into High.

### Calibration rules (often-tested edges)

- **Dust amounts** (rounding errors, minor fee variance) → QA, not Medium.
- **Matured yield loss** (already-earned but not-yet-claimed) → High, treated like principal.
- **Unmatured yield loss** (future yield) → cap at Medium.
- **View function findings** → Low at best (no on-chain state impact).
- **User-error dependency** (requires user to make an obvious mistake) → QA. Users are presumed to preview transactions.
- **Centralization / admin trust** — admins are presumed responsible. Reckless admin mistakes are invalid. Direct privilege misuse → QA. Privilege *escalation* (an attacker gains admin) → judged on likelihood and impact, can reach Medium.
- **Speculation on future code** — invalid unless the contest scope explicitly covers the future change.

### Report fields

Each finding is a self-contained markdown file in the contest's submission repo. Required sections:

1. **Lines of code** — Exact GitHub-blob URL with line range, e.g., `https://github.com/code-423n4/2026-01-protocol/blob/abc123/src/Vault.sol#L42-L58`.
2. **Vulnerability details** — What the bug is, why it's exploitable. Plain prose.
3. **Impact** — What an attacker gains and what victims lose. Concrete; quantify when possible.
4. **Proof of Concept** — Foundry test (preferred) that fails at the contest commit and passes after the fix. Inline the test code; judges run it.
5. **Tools used** — Manual review / Slither / Foundry / etc. (Optional but expected.)
6. **Recommended Mitigation** — Smallest change that closes the bug. Diff-style preferred.
7. **Assessed type** — Title-tag the severity (High / Medium / QA / Gas) so judges route quickly.

### Code4rena best practices

- Judges grade strictly to the rubric — frame your impact section in the rubric's language ("assets can be stolen because…" maps cleanly to High).
- One issue per submission. Don't bundle. Bundling can cause a partial-credit verdict.
- PoC is mandatory for High and Medium. A High without a working PoC is often downgraded.
- QA and Gas are submitted as one consolidated report each per warden — write them as a numbered list (`L-01`, `L-02`, `G-01`, `G-02`).
- Duplicates are normal. Code4rena pays partial duplicates pro-rata based on submission order and PoC quality.
- Judges may dispute severity. Frame the impact narrative tightly; speculative chains lose.

## Common pitfalls across platforms

### Duplicate detection (do this *before* drafting)

Before writing a single line of report:

1. Search the program's public disclosed reports (HackerOne hacktivity, Bugcrowd Crowdstream, Code4rena past contests).
2. Search GitHub Security Advisories for the same CWE on the same target.
3. Search the chrono-vault KG (`vault/security/findings/`) for prior internal findings.
4. Search public CVE DB for the same target.

If duplicate exists: do not submit. Cite the prior finding to the operator and route to drop-duplicate. (Per `chrono.plugin.impact-validator/duplicate-detection`.)

### Scope-violation flags

Out-of-scope submissions are auto-closed and can damage researcher reputation.

- Read the program's scope page in full. Subdomain wildcards have exceptions; read them.
- "Acquired companies" / "third-party services" exclusions are easy to miss.
- For Code4rena: only files listed in the contest scope count. Even files imported transitively are usually out-of-scope.
- When uncertain: ask the program before submitting (H1 / Bugcrowd) or use the contest's discord (Code4rena).

### P5 / N/A categorization

What gets rejected as P5 / informational across platforms:

- Self-XSS (only attacker can trigger their own browser)
- Missing security headers without demonstrated impact (e.g., CSP missing on a page that doesn't render user content)
- Version-disclosure / fingerprinting alone
- Outdated library versions without a working exploit
- Best-practice violations (e.g., "you should rotate keys") without a security boundary crossed
- Theoretical timing attacks where realistic networks make it infeasible
- "Could be combined with another vuln" — without that other vuln being demonstrated

If a finding is P5-shaped, route to drop-self-inflicted or drop-low-impact. Don't pad with hypothetical chains.

### Triage hygiene

- Respond to triager questions within 48h. Stale reports get auto-closed.
- Don't argue severity in the initial submission. Submit cleanly; if the triager downgrades, then engage with evidence.
- Disclosure timing: respect the program's policy. Public disclosure on a non-disclosed program kills payout and can ban the researcher.

## Cross-references

- `chrono.plugin.impact-validator/cvss-v4-gate` — CVSS v4 scoring methodology (used for H1 + Bugcrowd CVSS fields).
- `chrono.plugin.impact-validator/program-fit-check` — verify the vulnerability class is accepted by the target program.
- `chrono.plugin.impact-validator/duplicate-detection` — duplicate-search protocol before submission.
- `chrono.plugin.impact-validator/self-inflicted-detector` — pre-submission self-inflicted check.
- `chrono.plugin.impact-validator/nvd-osv-calibration` — historical CVSS calibration for the same CWE class.
- `departments/coding/specialists/smart-contract-engineer/skills/smart-contract-audit-checklist.md` — for Code4rena contest-shaped findings.
