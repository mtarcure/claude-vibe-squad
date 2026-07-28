---
name: osint-platform-audit
status: authored
---

# OSINT Platform Audit

Map an organization's externally-observable footprint from public sources only, and convert it into a defensible exposure inventory.

## Steps
1. Fix the authorization boundary before collecting anything: which domains, orgs, and identities are in scope, and confirm that collection is passive and permitted. Out-of-scope assets are not audited, only noted as adjacency.
2. Enumerate the domain surface from public records — certificate transparency, passive DNS, WHOIS, and public subdomain sources — and record where each observation came from.
3. Enumerate the code and artifact surface: public repositories, package registries, container registries, and published build artifacts belonging to the org.
4. Enumerate the human surface only to the extent the audit requires: role pages, public profiles that establish who owns which system. Collect the minimum, and treat personal data as sensitive throughout.
5. Search public leak and paste sources for org-linked credentials and tokens. Never authenticate with anything found; record existence and location only.
6. Check public cloud surfaces for unintended exposure — open buckets, public snapshots, exposed dashboards — using read-only, unauthenticated checks.
7. Correlate: link each observed asset to an owner, a purpose, and a confidence level. Unattributed assets are the most valuable output, because they are what the org does not know it has.
8. Classify each exposure by what it enables, and separate "public by design" from "public by accident."
9. Record collection dates and sources for everything; OSINT ages quickly and an undated finding cannot be re-verified.

## Acceptance
- Scope and authorization are stated before any collection, and collection stayed passive.
- Every asset carries its source, observation date, and confidence.
- Assets are attributed to an owner and purpose, with unattributed ones called out.
- Discovered credentials were never used, only reported.
- Exposures are split into by-design and by-accident, with the enabled impact stated for each.
