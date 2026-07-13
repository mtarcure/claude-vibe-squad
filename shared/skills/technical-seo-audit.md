---
name: technical-seo-audit
status: authored
---

# Technical SEO Audit

Audit a page/site for search discoverability by mechanism — crawl, index, intent — without inventing metrics.

## Steps
1. Check indexability: robots/meta directives, canonical tags, sitemap presence, HTTP status.
2. Audit on-page technical SEO: titles, meta descriptions, heading hierarchy, internal linking.
3. Validate structured data (see `structured-data-authoring`).
4. Record source date, locale, and device assumptions for every finding.
5. Write each recommendation with the mechanism it moves (crawl/index/intent); mark anything requiring live analytics as "measure after connector."

## Acceptance
- Every recommendation names the mechanism it affects.
- Structured data is validated.
- No fabricated rankings/traffic; measurement gaps are explicitly deferred to a connector.
