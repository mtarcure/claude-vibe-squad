---
id: bounty/smart-contract-web3
mode: bounty
title: Smart-contract / web3 vulnerability research (EVM · Solana · Cosmos)
capability_state: live
state_reason: Every core-step tool is live. The §12 crypto CLIs (Foundry forge/cast/anvil/chisel, slither, myth, echidna, medusa) are `yes`; chrono-recon and chrono-vault/chrono-obsidian are `yes` on all lanes; the claude-lane web-research tools are `lane-live`.
state_evidence: registry rows — forge/cast/anvil/chisel/slither/myth/echidna/medusa = `local·yes` (api-catalog §12, last_checked 2026-07-12); chrono-recon = `all·yes` (§9); xai_search/perplexity_search_web = `claude·lane-live` (§9 :935-945, verified on Claude; Codex needs a tools/list probe); chrono-vault/chrono-obsidian = `all·yes`.
overlays: [review, impact, privacy, memory]
gates: [public_release]
cost_note: Core analysis runs free public local CLIs (Foundry/slither/myth/echidna — `access: Public`, cost_tier `—`). The S1 web-research passthrough (`xai_search`, `perplexity_search_web`) is `metered` (API-key billed) and needs a budget/rate-limit guard; `arxiv_search` and the chrono-* MCPs are subscription lane-native.
---

**When to use:** authorized bug-bounty research against EVM / Solana / Cosmos contracts. Heightened-risk,
financial. This instantiates the 12-phase `bounty` flow onto the S0–S7 spine, expanding S3.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); target authorization precheck |
| **S1** Frame (OSINT + scope) | `scout`, `research`, `data-extraction-engineer` | `chrono-recon` (all · yes · subscription), `arxiv_search` (claude · yes · subscription), `xai_search` (claude · lane-live · metered), `perplexity_search_web` (claude · lane-live · metered) | `audit-context-prep` (stub), `program-rubric-lookup` (stub) | operator target-engage gate |
| **S2** Design (threat-model) | `threat-modeler`, `security-analyst` | `chrono-vault` (all · yes · subscription) | `attack-coverage-map` (authored) | — |
| **S3** Produce (analyze → PoC) | `smart-contract-engineer`, `exploit-developer` | `forge` (local · yes · —), `cast` (local · yes · —), `anvil` (local · yes · —), `chisel` (local · yes · —), `slither` (local · yes · —), `myth` (local · yes · —), `echidna` (local · yes · —), `medusa` (local · yes · —) | `cross-chain-bridge-audit` (untyped), `solana-anchor-audit-checklist` (untyped), `cosmos-sdk-audit-checklist` (untyped), `known-advisory-backport-check` (untyped), `gas-optimization-pattern` (stub) | heightened-risk; financial; no destructive testing / out-of-scope probing |
| **S4** Verify (impact + PoC-repro) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `forge` (local · yes · —), `anvil` (local · yes · —) | `chain-impact-rescore` (untyped) | impact G1–G4 overlay; cross-family PoC-reproduction (≥2 model families) |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay; staging allowed — **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored) | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record; `restricted` sensitivity) |

**Notes.** Safety-refusal invariant applies: a genuine refusal on any lane surfaces and is never
cross-family re-dispatched. The G1–G4 gate (`impact-validator` owns it) and the PoC-reproduction gate are
mandatory before the operator-gated final Submit. The `(untyped)`/`(stub)` audit-checklist skills exist as
draft references but are not invokable dependencies until typed + authored (registry ground truth).
