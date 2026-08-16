---
id: project/smart-contract-web3
mode: project
title: Smart-contract / web3 BUILD — EVM/Solidity (on-chain, non-bounty)
overlays: [review, privacy, memory]
gates: [public_release, production_mutation]
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

**When to use:** author, test, and deploy **EVM/Solidity** on-chain contracts. Solana (Anchor) and Cosmos
SDK are out of the live scope (`needs_tool` — no verified toolchain; see Notes). For authorized
vulnerability research against an existing target, use `bounty/smart-contract-web3` instead.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (spec) | `product-manager`, `architect` | — | `requirements-elicitation`, `scope-decomposition` | — |
| **S2** Design (contract arch + invariants) | `architect`, `smart-contract-engineer` | `context7` | `dependency-cycle-audit`, `gas-optimization-pattern` | — |
| **S3** Produce (EVM/Solidity implement + unit test) | `smart-contract-engineer` | `forge`, `cast`, `anvil`, `chisel` | `known-advisory-backport-check` | financial |
| **S4** Verify (EVM/Solidity static + property/fuzz) | `test-engineer`, `security-analyst` | `slither`, `myth`, `echidna`, `medusa`, `halmos`, `aderyn` | `behavior-preservation-test` | security review overlay (heightened-risk) |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (mandatory cross-family; review tools MECHANICS ONLY — never replace the independent cross-family reviewer); mainnet deploy operator-gated |
| **S6** Ship/Deliver (deploy) | `smart-contract-engineer`, `devops-engineer` | `plugin:github:github` | — | `public_release`, `production_mutation` (deploy) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** This is BUILD, not audit — `smart-contract-engineer` is heightened-risk (financial) and Claude
reviews risk/impact at S4/S5. Mainnet deployment is operator-gated (`public_release` + `production_mutation`).
The ``/`` audit-checklist skills are draft references, not invokable dependencies until typed.
**Multi-chain extension is a documented gap, not a live claim:** Solana (Anchor) and Cosmos SDK builds are
`needs_tool`/`needs_specialist` — the registry verifies no Anchor / `cargo` / Cosmos build+test toolchain (the
`solana-anchor-audit-checklist` / `cosmos-sdk-audit-checklist` entries are untyped skill docs, not tooling).
Extending the live scope to those ecosystems requires cataloging that toolchain first; derived `live` here
covers the EVM/Solidity scope only.
