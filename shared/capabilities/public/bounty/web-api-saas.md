---
id: bounty/web-api-saas
mode: bounty
title: Web API / HTTP-surface vulnerability research (authorized)
overlays: [review, impact, privacy, memory]
gates: [public_release]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

## Availability in a fresh clone

A zero-key checkout gets this protocol and its validation metadata as documentation; automated dispatch is `needs_tool`. To make it runnable, install and authenticate the selected model CLI, configure every MCP declared by the dispatched specialists, bind the private vault (`CHRONO_VAULT_ROOT`; Kimi also requires its exact vault context), install any required host-local binaries, and provide approved credentials plus a bounded budget for any metered provider named below. After setup, re-run the production role planner and validators on that host; availability remains subject to the narrower gaps and operator gates documented in this card.

**When to use:** authorized bug-bounty / vuln research against an HTTP API or the HTTP/SAST-accessible surface
of a web app. Heightened-risk. Instantiates the 12-phase `bounty` flow on the S0–S7 spine (S3 expanded).
Fresh/no-auth JS-rendered / client-state DAST is verified via fresh-Chrome browser automation;
session-authenticated SaaS (the authed `:9222` path) and mobile-app targets remain `needs_tool` (see Profiles). Requires an operator-confirmed in-scope target; **no destructive
testing, no out-of-scope probing, respect rate limits.**

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` | — | memory overlay (recall); target authorization precheck |
| **S1** Frame (OSINT + scope) | `scout`, `research`, `data-extraction-engineer` | `chrono-recon`, `subfinder`, `httpx`, `katana`, `xai_search`, `perplexity_search`, `codex --search`, `Brave Search`, `Serper`, `Apify`, `Google Search grounding` | `audit-context-prep`, `program-rubric-lookup`, `dedup-prior-art-check`, `tos-compliance-check` | operator target-engage gate; **prior-art/dedup runs BEFORE effort** (`dedup-prior-art-check` — disclosure DBs + `chrono-dedup`); `Apify` scraping requires authorized-scope + spend gate (no Actor run outside the authorized target); `Google Search grounding` = CVE/advisory source-fact grounding, not a substitute for the vuln analysis |
| **S2** Design (threat-model + surface map) | `threat-modeler`, `security-analyst`, `experimental-attacker` | `chrono-vault` | `systematic-attacking`, `attack-coverage-map`, `data-flow-trace` | governing method: this card is the web/SaaS domain branch of `systematic-attacking` (Phase 2 attack-surface + impact model); **impact-class first** — pre-register HIGH/CRIT termini in the payout classes; **dedicated novel-attack ideation pass every engagement** (Phase 2b) — `experimental-attacker` (kimi) generates broad/novel hypotheses (leads only) fanning out to heavy-hitter (Sol / Opus 5) validation; push past known + known-advisory classes, full-arsenal distance is the FLOOR; leads re-enter the verification spine, never ship unproven |
| **S3** Produce (scan → analyze → PoC) | `security-analyst`, `scraping-engineer`, `exploit-developer` | `semgrep`, `nuclei`, `ffuf`, `sqlmap`, `nikto`, `gitleaks`, `trufflehog`, `trivy`, `chrome-devtools`, `playwright`, `codex --sandbox`, `claude --worktree` | `error-based-ssti`, `parser-differential-route-confusion`, `rate-limit-respect`, `data-flow-trace` | heightened-risk; no destructive testing / out-of-scope probing; browser DAST here is fresh no-auth Chrome only — authenticated/session-state DAST (`:9222`) is `needs_tool`; **exhaustive-arsenal every engagement** — multi-fuzzer coverage via `ffuf` (content/param) + `nuclei` (template/`-fuzz`) + `sqlmap` (injection), SAST taint via `semgrep`; a Linux-only tool runs in a container (colima/docker present), never skipped |
| **S4** Verify (impact + PoC-repro) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `httpx`, `interactsh-client` | `systematic-attacking`, `multi-agent-evidence-gating`, `evidence-chain-preservation` | impact G1–G4 overlay; **evidence-gate to ≥0.85 confidence** (`multi-agent-evidence-gating`) before a candidate reaches the operator / heavy-hitter lane; cross-family PoC-reproduction (≥2 model families); runs `systematic-attacking`'s Phase 4 chaining (chain-strike v2) → Phase 6 impact-bar spine |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); staging allowed — **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` | `citation-audit`, `evidence-chain-preservation` | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | `evidence-chain-preservation` | memory overlay (record; `restricted` sensitivity) |

**Notes.** Safety-refusal invariant applies: a genuine refusal on any lane surfaces and is never cross-family
re-dispatched. The G1–G4 impact gate (`impact-validator` owns it) and the cross-family PoC-reproduction gate
are mandatory before the operator-gated final Submit.

**Depth standard (operator).** Full-arsenal distance is the FLOOR, not the ceiling. Every engagement runs the real
exhaustive arsenal and a **dedicated novel/innovative-attack ideation pass** past known + known-advisory classes
(leads re-enter `systematic-attacking`'s verification spine, never ship unproven). **Multi-fuzzer parity** on the
live HTTP surface is `ffuf` (content/parameter) + `nuclei` (`-fuzz`/template) + `sqlmap` (injection-grammar), all
; the static-analysis analog of symbolic execution for this domain is `semgrep` taint/dataflow
plus source-map recovery — classic symbolic execution is not part of the HTTP-surface live scope. A **grammar /
stateful API fuzzer** (RESTler, boofuzz) is `needs_tool` — absent from the enforced registry and host PATH — and is
run as a Linux build in a container (colima + docker present) when adopted, never marked "couldn't run". Go
**beyond commodity tools+chaining** (AI+SAST is table stakes): custom Semgrep/Nuclei detector rules, purpose-built
request-mutation fuzzers, patch-diff N-day analysis, and dynamic weaponization. Impact-bar discipline holds — only
intrinsic-impact deterministic findings convert; reachability/disclosure never pays; never resubmit
a non-reproducible finding.

**Impact-class targeting (operator).** S2 pre-registers termini only in the payout classes — **RCE ·
auth-bypass · privilege-escalation/ATO · private-data/PII · funds theft**. The two 2025-26 exploit-derived
audit skills wired at S3 target the top web payout class: `error-based-ssti` (Successful-Errors SSTI →
RCE, PortSwigger #1 of 2025) and `parser-differential-route-confusion` (wp2shell route-confusion → pre-auth
RCE). Reachability/disclosure is at most a lead.

**Experimental fan-out (operator).** `experimental-attacker` emits broad/novel
web hypotheses as **leads only** at S2/S3, fanning out to heavy-hitter (Sol / Opus 5) validation and gated
to ≥0.85 confidence by `multi-agent-evidence-gating` at S4 before reaching the operator — no laxer bar than
known-class hypotheses (`systematic-attacking` Phase 3b).

**Elite tooling — prose/`needs_tool` (not live tuples).** The live multi-fuzzer surface (`ffuf`+`nuclei`+
`sqlmap`, `semgrep` taint — all ) stands. Corpus B Tier-1 additions carry **no** live tuple until
promoted into the enforced registry: **Caido** (Rust intercept/replay proxy), **BBOT** (recursive OSINT/EASM),
and a graybox differential proxy fuzzer (**Gudifu**) for HTTP request-smuggling are `needs_tool`; a grammar/
stateful API fuzzer (RESTler, boofuzz) remains `needs_tool` and runs as a Linux container build when adopted.
The HTTP-smuggling / differential-proxy methodology is a noted follow-up skill (`differential-proxy-fuzzing`).

**Needs-tool profiles (NOT part of the live claim):**
- **Browser-AUTHENTICATED / session-state DAST → `needs_tool`.** Fresh/no-auth JS-rendered DAST is live (S3,
  via `chrome-devtools`/`playwright`  on a fresh Chrome). What stays `needs_tool` is the
  AUTHENTICATED path — driving a session-authenticated target through the raw-CDP `:9222` authed browser — which
  the probe did NOT verify; it cannot go live until an authenticated-session browser route is registry-verified.
- **Mobile-app targets → `needs_tool`.** No mobile toolchain (Frida / objection / apk tooling) is cataloged.

The `live` claim above covers the HTTP/API + SAST-accessible surface AND fresh/no-auth browser DAST; the
remaining profiles (authenticated-session browser DAST, mobile) are genuine `needs_tool`, not an optional
extension of a live card.
