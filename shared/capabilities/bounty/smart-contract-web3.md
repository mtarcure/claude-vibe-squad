---
id: bounty/smart-contract-web3
mode: bounty
title: Smart-contract / web3 vulnerability research (EVM · Solana · Cosmos)
capability_state: live
state_reason: Every core-step tool is live. The §12 crypto CLIs (Foundry forge/cast/anvil/chisel, slither, symbolic `myth`+`halmos`, property/coverage fuzzers `echidna`+`medusa`) are `yes` — the domain carries dual-symbolic and dual-fuzzer parity natively; chrono-recon and chrono-vault/chrono-obsidian are `yes` on all lanes; the claude-lane web-research tools are `lane-live`.
state_evidence: registry rows — forge/cast/anvil/chisel/slither/myth/halmos/echidna/medusa = `local·yes` (skill-tool-registry.tsv; api-catalog §12, halmos = api-catalog:1147, last_checked 2026-07-12); chrono-recon = `all·yes` (§9); xai_search/perplexity_search_web = `claude·lane-live` (§9 :935-945, verified on Claude; Codex needs a tools/list probe); chrono-vault/chrono-obsidian = `all·yes`.
overlays: [review, impact, privacy, memory]
gates: [public_release]
cost_note: Core analysis runs free public local CLIs (Foundry/slither/myth/echidna — `access: Public`, cost_tier `—`). The S1 web-research passthrough (`xai_search`, `perplexity_search_web`, `Brave Search`, `Serper`, `Apify`) is `metered` (API-key billed) and needs a budget/rate-limit guard — `Apify` scraping additionally requires authorized target scope; `arxiv_search`, `Google Search grounding` (gemini), and the chrono-* MCPs are subscription lane-native.
---

**When to use:** authorized bug-bounty research against EVM / Solana / Cosmos contracts. Heightened-risk,
financial. This instantiates the 12-phase `bounty` flow onto the S0–S7 spine, expanding S3.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); target authorization precheck |
| **S1** Frame (OSINT + scope) | `scout`, `research`, `data-extraction-engineer` | `chrono-recon` (all · yes · subscription), `arxiv_search` (claude · yes · subscription), `xai_search` (claude · lane-live · metered), `perplexity_search_web` (claude · lane-live · metered), `codex --search` (codex · yes · subscription), `Brave Search` (codex · yes · metered), `Serper` (codex · yes · metered), `Apify` (codex · yes · metered), `Google Search grounding` (gemini · yes · subscription) | `audit-context-prep` (stub), `program-rubric-lookup` (authored), `dedup-prior-art-check` (authored) | operator target-engage gate; **prior-art/dedup runs BEFORE effort** (`dedup-prior-art-check` — Solodit + `chrono-dedup`); `Apify` scraping requires authorized-scope + spend gate (no Actor run outside the authorized target); `Google Search grounding` = advisory/disclosure source-fact grounding, not a substitute for the vuln analysis |
| **S2** Design (threat-model) | `threat-modeler`, `security-analyst`, `experimental-attacker` | `chrono-vault` (all · yes · subscription) | `systematic-attacking` (authored), `attack-coverage-map` (authored) | governing method: this card is the smart-contract/DeFi domain branch of `systematic-attacking` (Phase 2 attack-surface + impact model); **impact-class first** — pre-register HIGH/CRIT termini in the payout classes (funds theft/drain · auth-bypass · privilege-escalation/ATO · private-data/PII · RCE); **dedicated novel-attack ideation pass every engagement** (Phase 2b) — `experimental-attacker` (kimi) generates broad/novel hypotheses (leads only) that fan out to heavy-hitter (Sol / Opus 5) validation; push past known + known-advisory classes, full-arsenal distance is the FLOOR; leads re-enter the verification spine, never ship unproven |
| **S3** Produce (analyze → PoC) | `smart-contract-engineer`, `exploit-developer` | `forge` (local · yes · —), `cast` (local · yes · —), `anvil` (local · yes · —), `chisel` (local · yes · —), `slither` (local · yes · —), `myth` (local · yes · —), `halmos` (local · yes · —), `echidna` (local · yes · —), `medusa` (local · yes · —), `codex --sandbox` (codex · yes · subscription), `claude --worktree` (claude · yes · subscription) | `erc1271-revert-data-check` (authored), `signature-validation-audit` (authored), `uniswap-v4-hook-access-control` (authored), `read-only-reentrancy-check` (authored), `durable-nonce-exploitation` (authored), `cross-chain-dvn-audit` (authored), `cross-chain-bridge-audit` (untyped), `solana-anchor-audit-checklist` (untyped), `cosmos-sdk-audit-checklist` (untyped), `known-advisory-backport-check` (untyped), `gas-optimization-pattern` (stub) | heightened-risk; financial; no destructive testing / out-of-scope probing; **exhaustive-arsenal every engagement** — dual-symbolic (`myth`+`halmos`) + dual-fuzzer (`echidna`+`medusa`) + `forge` auth/invariant fuzz; a macOS-only-blocked engine (e.g. ItyFuzz, `needs_tool`) runs in a Linux container (colima/docker present), never skipped |
| **S4** Verify (impact + PoC-repro) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `forge` (local · yes · —), `anvil` (local · yes · —) | `systematic-attacking` (authored), `multi-agent-evidence-gating` (authored), `chain-impact-rescore` (untyped) | impact G1–G4 overlay; **evidence-gate to ≥0.85 confidence** (`multi-agent-evidence-gating`) before a candidate reaches the operator / heavy-hitter lane; cross-family PoC-reproduction (≥2 model families); PoC reproduced against a REAL mainnet fork (`anvil --fork`), never a blind mock harness; runs `systematic-attacking`'s Phase 4 chaining (chain-strike v2) → Phase 6 impact-bar spine |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); staging allowed — **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored) | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record; `restricted` sensitivity) |

**Notes.** Safety-refusal invariant applies: a genuine refusal on any lane surfaces and is never
cross-family re-dispatched. The G1–G4 gate (`impact-validator` owns it) and the PoC-reproduction gate are
mandatory before the operator-gated final Submit. The `(untyped)`/`(stub)` audit-checklist skills exist as
draft references but are not invokable dependencies until typed + authored (registry ground truth).

**Depth standard (operator).** Full-arsenal distance is the FLOOR, not the ceiling. Every engagement runs the
real exhaustive arsenal — **symbolic execution** (`myth` + `halmos`, both `local·yes`) AND **multiple
property/coverage fuzzers** (`echidna` + `medusa`, both `local·yes`), plus `forge` auth/invariant fuzzing against a
**REAL mainnet fork** (`anvil --fork`), never a blind mock harness (mocks are blind to valuation/oracle bugs) —
and a **dedicated novel/innovative-attack ideation pass** that pushes past known and known-advisory classes (its
leads re-enter `systematic-attacking`'s verification spine and stay leads until independently reproduced). A tool
that will not run natively on macOS (e.g. ItyFuzz — `needs_tool`, no registry/host row) is run as a Linux build in
a container (colima + docker are present on the host), never marked "couldn't run". The moat is **beyond commodity
tools+chaining** (AI+SAST is table stakes): custom detector queries, purpose-built symbolic/fuzz harnesses,
patch-diff N-day backport analysis, and dynamic weaponization. Impact-bar discipline holds — only intrinsic-impact
deterministic findings convert (~1/21 lifetime); reachability/disclosure never pays; never resubmit a
non-reproducible finding.

**Impact-class targeting (operator).** S2 pre-registers termini in the payout classes only — **funds
theft/drain · auth-bypass · privilege-escalation/ATO · private-data/PII · RCE**. Reachability/disclosure
does not pay and is at most a lead. The six 2025-26 exploit-derived audit skills wired at S3
(`erc1271-revert-data-check`, `signature-validation-audit`, `uniswap-v4-hook-access-control`,
`read-only-reentrancy-check`, `durable-nonce-exploitation`, `cross-chain-dvn-audit`) each map to a
funds-theft/auth-bypass class with a real-world loss precedent.

**Experimental fan-out (operator).** The novel-attack ideation pass is run as a real swarm step:
`experimental-attacker` (kimi `primary_exception`, `offensive_execution` hold) emits broad/novel
hypotheses as **leads only** at S2/S3; those fan out to heavy-hitter validation (Sol / Opus 5) and are
gated to ≥0.85 confidence by `multi-agent-evidence-gating` at S4 before anything reaches the operator.
Experimental leads earn **no** laxer verification than known-class ones (`systematic-attacking` Phase 3b).

**Elite tooling — prose/`needs_tool` (not live tuples).** Symbolic/fuzzing parity is already live
(`myth`+`halmos` symbolic, `echidna`+`medusa` fuzz, `forge` invariant — all `local·yes`). Corpus B
Tier-1 additions are **not** promoted into the enforced `skill-tool-registry.tsv`, so they carry no live
tuple: **Solodit-MCP** (49k-finding prior-art corpus — the tool backing `dedup-prior-art-check`) and
**Halmos-as-MCP** are `needs_tool`; a macOS-only-blocked engine (e.g. ItyFuzz) still runs as a Linux
build in a container (colima+docker present), never skipped.
