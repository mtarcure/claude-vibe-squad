---
name: api-service
extends: bounty
status: active
---

# Bounty Profile: API Service

REST / GraphQL API bounties — BOLA (Broken Object Level Auth), rate limits, auth flow flaws, GraphQL-specific attacks.

## Auto-detection signals

- Target is `*.api.<domain>` or has documented API endpoints
- OpenAPI / Swagger docs available
- GraphQL endpoint detected (/graphql, /gql)

## Phase customizations

### Phase 1 Intelligence
- Read OpenAPI / GraphQL schema if accessible
- Map endpoint inventory + auth requirements per endpoint
- Note API rate limit policies

### Phase 2 Recon
- Endpoint discovery (often via swagger.json, robots.txt, /api routes)
- Parameter discovery (paramspider, ffuf with API wordlists)
- Auth flow mapping (OAuth, JWT, API key, mTLS)

### Phase 3 Threat Modeling
- BOLA (object-level auth) — most common API vuln class
- Rate-limiting bypasses
- IDOR via predictable IDs
- GraphQL introspection / depth attacks
- JWT flaws (algorithm confusion, weak secrets, kid injection)
- API key in code / git history
- Mass assignment

### Phase 5/6/7 Exploitation
- Tools: Burp + extensions (Autorize for BOLA, GraphQL Voyager)
- Custom scripts for API enumeration
- BOLA testing: change object IDs systematically, check auth boundaries

### Phase 9 Validation
- API bounties often pay well for BOLA / IDOR (clear impact)
- Rate-limit bypasses lower-paying unless DoS-grade

### Phase 10 Report
- HTTP request/response pairs as evidence
- Specific user IDs / object IDs that demonstrated boundary cross
- Reproducible curl commands

## Specialists most active

- exploit-developer (multi-model)
- security-analyst
- scout (API endpoint discovery)
- skeptic (BOLA findings need careful verification)
