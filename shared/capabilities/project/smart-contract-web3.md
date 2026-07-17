---
id: project/smart-contract-web3
mode: project
title: Smart-contract / web3 BUILD — EVM/Solidity (on-chain, non-bounty)
capability_state: live
state_reason: Live scope is EVM/Solidity — contract implementation + testing runs the verified §12 Foundry + static/fuzz toolchain (all `local·yes`), no catalog-absent tool on the build path. Solana (Anchor) and Cosmos SDK are OUT of the live scope — `needs_tool`/`needs_specialist`: no Anchor/`cargo`/Cosmos build+test toolchain is registry-verified. This is BUILD — distinct from `bounty/smart-contract-web3` (audit): no G1–G4 gate, no submission gate.
state_evidence: registry rows — forge/cast/anvil/chisel/slither/myth/echidna/medusa/halmos/aderyn = `local·yes·—` (api-catalog §12, reconciled at `d1f3c5f`); chrono-vault = `all·yes`. No Solana/Cosmos/Anchor/cargo build tool exists in the registry (only untyped `solana-anchor-audit-checklist` / `cosmos-sdk-audit-checklist` skills, not a build/test toolchain) → those ecosystems are `needs_tool`.
overlays: [review, privacy, memory]
gates: [public_release, production_mutation]
cost_note: the on-chain build/test toolchain is free public local CLIs (cost_tier `—`); chrono MCPs are subscription. No metered provider is required.
---

**When to use:** author, test, and deploy **EVM/Solidity** on-chain contracts. Solana (Anchor) and Cosmos
SDK are out of the live scope (`needs_tool` — no verified toolchain; see Notes). For authorized
vulnerability research against an existing target, use `bounty/smart-contract-web3` instead.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (spec) | `product-manager`, `architect` | — | `requirements-elicitation` (stub), `scope-decomposition` (stub) | — |
| **S2** Design (contract arch + invariants) | `architect`, `smart-contract-engineer` | `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub), `gas-optimization-pattern` (stub) | — |
| **S3** Produce (EVM/Solidity implement + unit test) | `smart-contract-engineer` | `forge` (local · yes · —), `cast` (local · yes · —), `anvil` (local · yes · —), `chisel` (local · yes · —) | `known-advisory-backport-check` (untyped) | financial |
| **S4** Verify (EVM/Solidity static + property/fuzz) | `test-engineer`, `security-analyst` | `slither` (local · yes · —), `myth` (local · yes · —), `echidna` (local · yes · —), `medusa` (local · yes · —), `halmos` (local · yes · —), `aderyn` (local · yes · —) | `behavior-preservation-test` (stub) | security review overlay (heightened-risk) |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay (mandatory cross-family); mainnet deploy operator-gated |
| **S6** Ship/Deliver (deploy) | `smart-contract-engineer`, `devops-engineer` | `plugin:github:github` (claude · lane-live · subscription) | — | `public_release`, `production_mutation` (deploy) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** This is BUILD, not audit — `smart-contract-engineer` is heightened-risk (financial) and Claude
reviews risk/impact at S4/S5. Mainnet deployment is operator-gated (`public_release` + `production_mutation`).
The `(untyped)`/`(stub)` audit-checklist skills are draft references, not invokable dependencies until typed.
**Multi-chain extension is a documented gap, not a live claim:** Solana (Anchor) and Cosmos SDK builds are
`needs_tool`/`needs_specialist` — the registry verifies no Anchor / `cargo` / Cosmos build+test toolchain (the
`solana-anchor-audit-checklist` / `cosmos-sdk-audit-checklist` entries are untyped skill docs, not tooling).
Extending the live scope to those ecosystems requires cataloging that toolchain first; derived `live` here
covers the EVM/Solidity scope only.
