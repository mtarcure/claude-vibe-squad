---
name: parser-differential-route-confusion
status: authored
---

# Parser-Differential Route Confusion

Audit API gateways, batch processors, and microservice routers for route/permission desynchronization:
one component validates a request's route/permissions using one parser while a *different* component
executes it using another, so a nested or crafted path passes auth as a "safe" route but resolves at
execution to a privileged one. Chain with a downstream injection (SQLi/command) reachable only through
the confused route for pre-auth RCE.

**Source:** corpus A §I.2 — Assetnote "wp2shell" (CVE-2026-63030 / CVE-2026-60137): WordPress
`/wp-json/batch/v1` validated nested routes in one loop and executed in another; a `wp_parse_url()`
path discrepancy let an unauthenticated batch sub-request execute against a privileged admin route,
chained to `author__not_in` SQLi → admin creation → webshell.
**Impact class:** RCE / privilege escalation (intrinsic).
**Governing method:** Phase-3a hypothesis lane of `systematic-attacking`; **leads** only into the
verification spine. Authorized in-scope targets only.

## Method
1. Map every place a request's path/route is parsed more than once: gateway vs. origin, batch/GraphQL/
   JSON-RPC sub-request processors, reverse-proxy rewrite rules, framework `parse_url` calls
   (`katana` to crawl, source-map + `semgrep` to locate dual parsers).
2. Probe for validation-vs-execution divergence: encoded slashes, dot-segments, nested batch
   entries, trailing-data, unicode/overlong forms, and matrix params that resolve differently in the
   two parsers. Watch for a request that authenticates as unauthenticated/safe but reaches a
   privileged handler.
3. Once a confused route reaches a privileged handler, enumerate the injection surface it exposes
   (`sqlmap` for SQLi on parameters the confused route stops sanitizing, command sinks) and build the
   chain to RCE/admin.
4. PoC: the full unauthenticated request that desynchronizes and lands the privileged/injection
   effect, with an `interactsh-client` OOB or scoped-read impact proof. Link-level negative control =
   the equivalent direct request is correctly rejected by auth.
5. Capture the differential as a `nuclei` template / custom detector for variant analysis across the
   target's other batch/router surfaces.

## Acceptance
- All multi-parse route points are enumerated; the confused route names both parsers and the
  privilege gap.
- The chain is proven end-to-end (auth bypass → privileged handler → injection/RCE) against the real
  target with a benign negative control.
- Finding deduped against the wp2shell advisories and the stack's router CVEs before submission.
