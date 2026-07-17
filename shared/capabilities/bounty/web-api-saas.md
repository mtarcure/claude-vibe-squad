---
id: bounty/web-api-saas
mode: bounty
title: Web API / HTTP-surface vulnerability research (authorized)
capability_state: live
state_reason: The live scope is the HTTP/API + SAST-accessible surface — semgrep, nuclei, ffuf, httpx, katana, subfinder, sqlmap, nikto, gitleaks, trufflehog, trivy, interactsh-client are all `local·yes·—`; `chrono-recon` and `chrono-vault`/`chrono-obsidian` are `all·yes`; the claude-lane research tools are `lane-live`. No catalog-absent tool sits on this narrowed path. Fresh/no-auth browser DAST — JS-rendered / client-state testing of UNauthenticated targets — is now a verified route via `chrome-devtools`/`playwright` (`claude·yes·subscription`, fresh Chrome). Browser-AUTHENTICATED / session-state DAST (the authenticated raw-CDP `:9222` path) and mobile-app targets have NO registry-verified tool — they stay explicit `needs_tool` profiles (see Profiles), NOT part of the live claim.
state_evidence: registry rows — semgrep/nuclei/ffuf/httpx/katana/subfinder/sqlmap/nikto/gitleaks/trufflehog/trivy/interactsh-client = `local·yes·—`; chrono-recon = `all·yes·subscription`; xai_search = `all·lane-live·metered`, perplexity_search_web = `claude·lane-live·metered`; chrono-vault/chrono-obsidian = `all·yes·subscription`. playwright/chrome-devtools = `claude·yes·subscription` (verified for fresh no-auth Chrome, not the authenticated `:9222` path); no mobile toolchain is cataloged (→ the browser-AUTHENTICATED-DAST and mobile profiles are `needs_tool`, see Profiles).
overlays: [review, impact, privacy, memory]
gates: [public_release]
cost_note: Core scanning/recon runs free public local CLIs (cost_tier `—`). The S1 web-research passthrough (`xai_search`, `perplexity_search_web`) is `metered` (API-key billed) and needs a budget/rate-limit guard; chrono-* MCPs are subscription lane-native. No paid provider is on the core path.
---

**When to use:** authorized bug-bounty / vuln research against an HTTP API or the HTTP/SAST-accessible surface
of a web app. Heightened-risk. Instantiates the 12-phase `bounty` flow on the S0–S7 spine (S3 expanded).
Fresh/no-auth JS-rendered / client-state DAST is verified via fresh-Chrome browser automation;
session-authenticated SaaS (the authed `:9222` path) and mobile-app targets remain `needs_tool` (see Profiles). Requires an operator-confirmed in-scope target; **no destructive
testing, no out-of-scope probing, respect rate limits.**

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); target authorization precheck |
| **S1** Frame (OSINT + scope) | `scout`, `research`, `data-extraction-engineer` | `chrono-recon` (all · yes · subscription), `subfinder` (local · yes · —), `httpx` (local · yes · —), `katana` (local · yes · —), `xai_search` (all · lane-live · metered), `perplexity_search_web` (claude · lane-live · metered), `codex --search` (codex · yes · subscription) | `audit-context-prep` (stub), `program-rubric-lookup` (stub), `tos-compliance-check` (stub) | operator target-engage gate |
| **S2** Design (threat-model + surface map) | `threat-modeler`, `security-analyst` | `chrono-vault` (all · yes · subscription) | `attack-coverage-map` (authored), `data-flow-trace` (stub) | — |
| **S3** Produce (scan → analyze → PoC) | `security-analyst`, `scraping-engineer`, `exploit-developer` | `semgrep` (local · yes · —), `nuclei` (local · yes · —), `ffuf` (local · yes · —), `sqlmap` (local · yes · —), `nikto` (local · yes · —), `gitleaks` (local · yes · —), `trufflehog` (local · yes · —), `trivy` (local · yes · —), `chrome-devtools` (claude · yes · subscription), `playwright` (claude · yes · subscription), `codex --sandbox` (codex · yes · subscription), `claude --worktree` (claude · yes · subscription) | `rate-limit-respect` (stub), `data-flow-trace` (stub) | heightened-risk; no destructive testing / out-of-scope probing; browser DAST here is fresh no-auth Chrome only — authenticated/session-state DAST (`:9222`) is `needs_tool` |
| **S4** Verify (impact + PoC-repro) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `httpx` (local · yes · —), `interactsh-client` (local · yes · —) | `evidence-chain-preservation` (stub) | impact G1–G4 overlay; cross-family PoC-reproduction (≥2 model families) |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); staging allowed — **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored), `evidence-chain-preservation` (stub) | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record; `restricted` sensitivity) |

**Notes.** Safety-refusal invariant applies: a genuine refusal on any lane surfaces and is never cross-family
re-dispatched. The G1–G4 impact gate (`impact-validator` owns it) and the cross-family PoC-reproduction gate
are mandatory before the operator-gated final Submit.

**Needs-tool profiles (NOT part of the live claim):**
- **Browser-AUTHENTICATED / session-state DAST → `needs_tool`.** Fresh/no-auth JS-rendered DAST is live (S3,
  via `chrome-devtools`/`playwright` `claude·yes·subscription` on a fresh Chrome). What stays `needs_tool` is the
  AUTHENTICATED path — driving a session-authenticated target through the raw-CDP `:9222` authed browser — which
  the probe did NOT verify; it cannot go live until an authenticated-session browser route is registry-verified.
- **Mobile-app targets → `needs_tool`.** No mobile toolchain (Frida / objection / apk tooling) is cataloged.

The `live` claim above covers the HTTP/API + SAST-accessible surface AND fresh/no-auth browser DAST; the
remaining profiles (authenticated-session browser DAST, mobile) are genuine `needs_tool`, not an optional
extension of a live card.
