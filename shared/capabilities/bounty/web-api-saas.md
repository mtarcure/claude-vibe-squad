---
id: bounty/web-api-saas
mode: bounty
title: Web API / HTTP-surface vulnerability research (authorized)
capability_state: live
state_reason: The live scope is the HTTP/API + SAST-accessible surface — semgrep, nuclei, ffuf, httpx, katana, subfinder, sqlmap, nikto, gitleaks, trufflehog, trivy, interactsh-client are all `local·yes·—`; `chrono-recon` and `chrono-vault`/`chrono-obsidian` are `all·yes`; the claude-lane research tools are `lane-live`. No catalog-absent tool sits on this narrowed path. Fresh/no-auth browser DAST — JS-rendered / client-state testing of UNauthenticated targets — is now a verified route via `chrome-devtools`/`playwright` (`claude·yes·subscription`, fresh Chrome). Browser-AUTHENTICATED / session-state DAST (the authenticated raw-CDP `:9222` path) and mobile-app targets have NO registry-verified tool — they stay explicit `needs_tool` profiles (see Profiles), NOT part of the live claim.
state_evidence: registry rows — semgrep/nuclei/ffuf/httpx/katana/subfinder/sqlmap/nikto/gitleaks/trufflehog/trivy/interactsh-client = `local·yes·—`; chrono-recon = `all·yes·subscription`; xai_search = `all·lane-live·metered`, perplexity_search_web = `claude·lane-live·metered`; chrono-vault/chrono-obsidian = `all·yes·subscription`. playwright/chrome-devtools = `claude·yes·subscription` (verified for fresh no-auth Chrome, not the authenticated `:9222` path); no mobile toolchain is cataloged (→ the browser-AUTHENTICATED-DAST and mobile profiles are `needs_tool`, see Profiles).
overlays: [review, impact, privacy, memory]
gates: [public_release]
cost_note: Core scanning/recon runs free public local CLIs (cost_tier `—`). The S1 web-research passthrough (`xai_search`, `perplexity_search_web`, `Brave Search`, `Serper`, `Apify`) is `metered` (API-key billed) and needs a budget/rate-limit guard — `Apify` scraping additionally requires authorized target scope. `Google Search grounding` (gemini) is subscription-tier, not metered; chrono-* MCPs are subscription lane-native. No paid provider is on the core scanning path.
---

**When to use:** authorized bug-bounty / vuln research against an HTTP API or the HTTP/SAST-accessible surface
of a web app. Heightened-risk. Instantiates the 12-phase `bounty` flow on the S0–S7 spine (S3 expanded).
Fresh/no-auth JS-rendered / client-state DAST is verified via fresh-Chrome browser automation;
session-authenticated SaaS (the authed `:9222` path) and mobile-app targets remain `needs_tool` (see Profiles). Requires an operator-confirmed in-scope target; **no destructive
testing, no out-of-scope probing, respect rate limits.**

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); target authorization precheck |
| **S1** Frame (OSINT + scope) | `scout`, `research`, `data-extraction-engineer` | `chrono-recon` (all · yes · subscription), `subfinder` (local · yes · —), `httpx` (local · yes · —), `katana` (local · yes · —), `xai_search` (all · lane-live · metered), `perplexity_search_web` (claude · lane-live · metered), `codex --search` (codex · yes · subscription), `Brave Search` (codex · yes · metered), `Serper` (codex · yes · metered), `Apify` (codex · yes · metered), `Google Search grounding` (gemini · yes · subscription) | `audit-context-prep` (stub), `program-rubric-lookup` (authored), `dedup-prior-art-check` (authored), `tos-compliance-check` (stub) | operator target-engage gate; **prior-art/dedup runs BEFORE effort** (`dedup-prior-art-check` — disclosure DBs + `chrono-dedup`); `Apify` scraping requires authorized-scope + spend gate (no Actor run outside the authorized target); `Google Search grounding` = CVE/advisory source-fact grounding, not a substitute for the vuln analysis |
| **S2** Design (threat-model + surface map) | `threat-modeler`, `security-analyst`, `experimental-attacker` | `chrono-vault` (all · yes · subscription) | `systematic-attacking` (authored), `attack-coverage-map` (authored), `data-flow-trace` (authored) | governing method: this card is the web/SaaS domain branch of `systematic-attacking` (Phase 2 attack-surface + impact model); **impact-class first** — pre-register HIGH/CRIT termini in the payout classes (RCE · auth-bypass · privilege-escalation/ATO · private-data/PII · funds theft); **dedicated novel-attack ideation pass every engagement** (Phase 2b) — `experimental-attacker` (kimi) generates broad/novel hypotheses (leads only) fanning out to heavy-hitter (Sol / Opus 5) validation; push past known + known-advisory classes, full-arsenal distance is the FLOOR; leads re-enter the verification spine, never ship unproven |
| **S3** Produce (scan → analyze → PoC) | `security-analyst`, `scraping-engineer`, `exploit-developer` | `semgrep` (local · yes · —), `nuclei` (local · yes · —), `ffuf` (local · yes · —), `sqlmap` (local · yes · —), `nikto` (local · yes · —), `gitleaks` (local · yes · —), `trufflehog` (local · yes · —), `trivy` (local · yes · —), `chrome-devtools` (claude · yes · subscription), `playwright` (claude · yes · subscription), `codex --sandbox` (codex · yes · subscription), `claude --worktree` (claude · yes · subscription) | `error-based-ssti` (authored), `parser-differential-route-confusion` (authored), `rate-limit-respect` (stub), `data-flow-trace` (authored) | heightened-risk; no destructive testing / out-of-scope probing; browser DAST here is fresh no-auth Chrome only — authenticated/session-state DAST (`:9222`) is `needs_tool`; **exhaustive-arsenal every engagement** — multi-fuzzer coverage via `ffuf` (content/param) + `nuclei` (template/`-fuzz`) + `sqlmap` (injection), SAST taint via `semgrep`; a Linux-only tool runs in a container (colima/docker present), never skipped |
| **S4** Verify (impact + PoC-repro) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `httpx` (local · yes · —), `interactsh-client` (local · yes · —) | `systematic-attacking` (authored), `multi-agent-evidence-gating` (authored), `evidence-chain-preservation` (stub) | impact G1–G4 overlay; **evidence-gate to ≥0.85 confidence** (`multi-agent-evidence-gating`) before a candidate reaches the operator / heavy-hitter lane; cross-family PoC-reproduction (≥2 model families); runs `systematic-attacking`'s Phase 4 chaining (chain-strike v2) → Phase 6 impact-bar spine |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); staging allowed — **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored), `evidence-chain-preservation` (stub) | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record; `restricted` sensitivity) |

**Notes.** Safety-refusal invariant applies: a genuine refusal on any lane surfaces and is never cross-family
re-dispatched. The G1–G4 impact gate (`impact-validator` owns it) and the cross-family PoC-reproduction gate
are mandatory before the operator-gated final Submit.

**Depth standard (operator).** Full-arsenal distance is the FLOOR, not the ceiling. Every engagement runs the real
exhaustive arsenal and a **dedicated novel/innovative-attack ideation pass** past known + known-advisory classes
(leads re-enter `systematic-attacking`'s verification spine, never ship unproven). **Multi-fuzzer parity** on the
live HTTP surface is `ffuf` (content/parameter) + `nuclei` (`-fuzz`/template) + `sqlmap` (injection-grammar), all
`local·yes`; the static-analysis analog of symbolic execution for this domain is `semgrep` taint/dataflow (`local·yes`)
plus source-map recovery — classic symbolic execution is not part of the HTTP-surface live scope. A **grammar /
stateful API fuzzer** (RESTler, boofuzz) is `needs_tool` — absent from the enforced registry and host PATH — and is
run as a Linux build in a container (colima + docker present) when adopted, never marked "couldn't run". The moat is
**beyond commodity tools+chaining** (AI+SAST is table stakes): custom Semgrep/Nuclei detector rules, purpose-built
request-mutation fuzzers, patch-diff N-day analysis, and dynamic weaponization. Impact-bar discipline holds — only
intrinsic-impact deterministic findings convert (~1/21 lifetime); reachability/disclosure never pays; never resubmit
a non-reproducible finding.

**Impact-class targeting (operator).** S2 pre-registers termini only in the payout classes — **RCE ·
auth-bypass · privilege-escalation/ATO · private-data/PII · funds theft**. The two 2025-26 exploit-derived
audit skills wired at S3 target the top web payout class: `error-based-ssti` (Successful-Errors SSTI →
RCE, PortSwigger #1 of 2025) and `parser-differential-route-confusion` (wp2shell route-confusion → pre-auth
RCE). Reachability/disclosure is at most a lead.

**Experimental fan-out (operator).** `experimental-attacker` (kimi `primary_exception`) emits broad/novel
web hypotheses as **leads only** at S2/S3, fanning out to heavy-hitter (Sol / Opus 5) validation and gated
to ≥0.85 confidence by `multi-agent-evidence-gating` at S4 before reaching the operator — no laxer bar than
known-class hypotheses (`systematic-attacking` Phase 3b).

**Elite tooling — prose/`needs_tool` (not live tuples).** The live multi-fuzzer surface (`ffuf`+`nuclei`+
`sqlmap`, `semgrep` taint — all `local·yes`) stands. Corpus B Tier-1 additions carry **no** live tuple until
promoted into the enforced registry: **Caido** (Rust intercept/replay proxy), **BBOT** (recursive OSINT/EASM),
and a graybox differential proxy fuzzer (**Gudifu**) for HTTP request-smuggling are `needs_tool`; a grammar/
stateful API fuzzer (RESTler, boofuzz) remains `needs_tool` and runs as a Linux container build when adopted.
The HTTP-smuggling / differential-proxy methodology is a noted follow-up skill (`differential-proxy-fuzzing`).

**Needs-tool profiles (NOT part of the live claim):**
- **Browser-AUTHENTICATED / session-state DAST → `needs_tool`.** Fresh/no-auth JS-rendered DAST is live (S3,
  via `chrome-devtools`/`playwright` `claude·yes·subscription` on a fresh Chrome). What stays `needs_tool` is the
  AUTHENTICATED path — driving a session-authenticated target through the raw-CDP `:9222` authed browser — which
  the probe did NOT verify; it cannot go live until an authenticated-session browser route is registry-verified.
- **Mobile-app targets → `needs_tool`.** No mobile toolchain (Frida / objection / apk tooling) is cataloged.

The `live` claim above covers the HTTP/API + SAST-accessible surface AND fresh/no-auth browser DAST; the
remaining profiles (authenticated-session browser DAST, mobile) are genuine `needs_tool`, not an optional
extension of a live card.
