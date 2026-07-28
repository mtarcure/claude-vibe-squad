---
name: error-based-ssti
status: authored
---

# Error-Based SSTI ("Successful Errors")

Detect and exploit server-side template injection (and code injection) in blind / output-blocked
environments by deliberately forcing runtime **errors** that reflect the result of evaluated code in
the exception message. When even error text is suppressed, use a boolean error-based oracle
(evaluate-then-conditionally-throw, e.g. division-by-zero on a true bit) to exfiltrate bit-by-bit via
HTTP 500-vs-200 status differentials — zero dependency on rendered output.

**Source:** corpus A §I.1 — Korchagin, "Successful Errors" (PortSwigger Top 10 Web Hacking Techniques
of 2025, #1). **Impact class:** RCE / private-data exposure (intrinsic).
**Governing method:** Phase-3a hypothesis lane of `systematic-attacking`; **leads** only into the
verification spine. Only fired against operator-authorized in-scope targets, honoring rate limits.

## Method
1. Identify template/expression sinks (user input flowing into Jinja2/Mako, Twig/Smarty, Spring EL,
   Handlebars, etc.) via source-map recovery + `semgrep` taint rules; note which reflect output vs.
   are blind.
2. For blind sinks, send **error-forcing** payloads per engine: Python `AttributeError`/`mro`
   probes (`().__class__.__mro__[1].__subclasses__()`), Twig `include(...)`/not-found errors, Spring
   EL type-conversion faults — and read the reflected exception, not the page body.
3. For error-suppressed sinks, build a boolean oracle: an expression that evaluates a target bit and
   conditionally triggers a fault (e.g. `1/0` on true), then read the HTTP status. Iterate to
   exfiltrate a secret / prove code execution one bit at a time.
4. Escalate carefully to a contained impact proof (read a scoped file, echo a unique token via an
   `interactsh-client` OOB callback) sufficient to demonstrate RCE — never destructive, never
   out-of-scope. Encode the winning payloads as custom `nuclei` templates for regression.
5. Negative control: a benign input over the same path produces the baseline status/response, proving
   the differential is attacker-caused.

## Acceptance
- Blind vs. reflected template sinks are enumerated; the exploited sink names its engine.
- Code execution or data exfiltration is proven via the error/boolean oracle with an OOB or
  scoped-read impact proof and a benign negative control.
- Payloads are captured as reusable `nuclei` templates; finding deduped against known SSTI CVEs for
  the stack before submission.
