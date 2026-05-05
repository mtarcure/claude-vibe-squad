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

### Phase 2 Program Scope
- Read OpenAPI / GraphQL schema if accessible
- Map endpoint inventory + auth requirements per endpoint
- Note API rate limit policies

### Phase 3 Recon
- Endpoint discovery (often via swagger.json, robots.txt, /api routes)
- Parameter discovery (paramspider, ffuf with API wordlists)
- Auth flow mapping (OAuth, JWT, API key, mTLS)

### Phase 4 Threat Modeling
- BOLA (object-level auth) — most common API vuln class
- Rate-limiting bypasses
- IDOR via predictable IDs
- GraphQL introspection / depth attacks
- JWT flaws (algorithm confusion, weak secrets, kid injection)
- API key in code / git history
- Mass assignment

### Phase 6/7/8 Exploitation
- Tools: Burp + extensions (Autorize for BOLA, GraphQL Voyager)
- Custom scripts for API enumeration
- BOLA testing: change object IDs systematically, check auth boundaries

### Phase 10 Validation
- API bounties often pay well for BOLA / IDOR (clear impact)
- Rate-limit bypasses lower-paying unless DoS-grade

### Phase 11 Report
- HTTP request/response pairs as evidence
- Specific user IDs / object IDs that demonstrated boundary cross
- Reproducible curl commands

## Specialists most active

- security namespace invokes `exploit-developer` via `Task` tool with `subagent_type: exploit-developer` (multi-model)
- security namespace invokes `security-analyst` via `Task` tool with `subagent_type: security-analyst`
- security namespace invokes `scout` via `Task` tool with `subagent_type: scout` (API endpoint discovery)
- skeptic (BOLA findings need careful verification)
