---
id: bounty/smart-contract-web3
mode: bounty
title: Smart-contract / web3 vulnerability research (EVM · Solana · Cosmos)
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

**When to use:** authorized bug-bounty research against EVM / Solana / Cosmos contracts. Heightened-risk,
financial. This instantiates the 12-phase `bounty` flow onto the S0–S7 spine, expanding S3.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` | — | memory overlay (recall); target authorization precheck |
| **S1** Frame (OSINT + scope) | `scout`, `research`, `data-extraction-engineer` | `chrono-recon`, `arxiv_search`, `xai_search`, `perplexity_search`, `codex --search`, `Brave Search`, `Serper`, `Apify`, `Google Search grounding` | `audit-context-prep`, `program-rubric-lookup`, `dedup-prior-art-check` | operator target-engage gate; **prior-art/dedup runs BEFORE effort** (`dedup-prior-art-check` — Solodit + `chrono-dedup`); `Apify` scraping requires authorized-scope + spend gate (no Actor run outside the authorized target); `Google Search grounding` = advisory/disclosure source-fact grounding, not a substitute for the vuln analysis |
| **S2** Design (threat-model) | `threat-modeler`, `security-analyst`, `experimental-attacker` | `chrono-vault` | `systematic-attacking`, `attack-coverage-map` | governing method: this card is the smart-contract/DeFi domain branch of `systematic-attacking` (Phase 2 attack-surface + impact model); **impact-class first** — pre-register HIGH/CRIT termini in the payout classes; **dedicated novel-attack ideation pass every engagement** (Phase 2b) — `experimental-attacker` (codex) generates broad/novel hypotheses (leads only) that fan out to heavy-hitter (Sol / Opus 5) validation; push past known + known-advisory classes, full-arsenal distance is the FLOOR; leads re-enter the verification spine, never ship unproven |
| **S3** Produce (analyze → PoC) | `smart-contract-engineer`, `exploit-developer` | `forge`, `cast`, `anvil`, `chisel`, `slither`, `myth`, `halmos`, `echidna`, `medusa`, `codex --sandbox`, `claude --worktree` | `erc1271-revert-data-check`, `signature-validation-audit`, `uniswap-v4-hook-access-control`, `read-only-reentrancy-check`, `durable-nonce-exploitation`, `cross-chain-dvn-audit`, `cross-chain-bridge-audit`, `solana-anchor-audit-checklist`, `cosmos-sdk-audit-checklist`, `known-advisory-backport-check`, `gas-optimization-pattern` | heightened-risk; financial; no destructive testing / out-of-scope probing; **exhaustive-arsenal every engagement** — dual-symbolic (`myth`+`halmos`) + dual-fuzzer (`echidna`+`medusa`) + `forge` auth/invariant fuzz; a macOS-only-blocked engine (e.g. ItyFuzz, `needs_tool`) runs in a Linux container (colima/docker present), never skipped |
| **S4** Verify (impact + PoC-repro) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `forge`, `anvil` | `systematic-attacking`, `multi-agent-evidence-gating`, `chain-impact-rescore` | impact G1–G4 overlay; **evidence-gate to ≥0.85 confidence** (`multi-agent-evidence-gating`) before a candidate reaches the operator / heavy-hitter lane; cross-family PoC-reproduction (≥2 model families); PoC reproduced against a REAL mainnet fork (`anvil --fork`), never a blind mock harness; runs `systematic-attacking`'s Phase 4 chaining (chain-strike v2) → Phase 6 impact-bar spine |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); staging allowed — **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` | `citation-audit` | public disclosure gate; the report **opens with the triage-evidence capsule** and carries the **five triager preemptions** (`shared/modes/bounty.md` Phase 6): a `200` is not a state change (show state before/after); a balance difference is not theft (show victim debit AND attacker-destination credit, both accounts); differentiate on root cause in BROAD words, for a triager who searched two; state the attacker's starting privilege up front (unprivileged → privileged); argue severity from the code against the program's quoted Critical definition, never assert a label |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | `evidence-chain-preservation` | memory overlay (record; `restricted` sensitivity) |

**Notes.** Safety-refusal invariant applies: a genuine refusal on any lane surfaces and is never
cross-family re-dispatched. The G1–G4 gate (`impact-validator` owns it) and the PoC-reproduction gate are
mandatory before the operator-gated final Submit. The ``/`` audit-checklist skills exist as
draft references but are not invokable dependencies until typed + authored (registry ground truth).

**Depth standard (operator).** Full-arsenal distance is the FLOOR, not the ceiling. Every engagement runs the
real exhaustive arsenal — stated as **technique classes**, because this card governs EVM, Solana/Anchor and
Cosmos, and a named-tool mandate is unsatisfiable on two of the three. The floor is **symbolic execution** AND
**multiple independent property/coverage fuzzers**, plus auth/invariant fuzzing against **REAL forked state**,
never a blind mock harness (mocks are blind to valuation/oracle bugs) —

> **On an EVM target the floor is named and there is no excuse:** `myth` + `halmos`,
> `echidna` + `medusa`, and `forge` fuzzing against `anvil --fork`.
>
> **On a non-EVM target, the class still binds and the tool changes.** Satisfy it with whatever the registry
> holds for that `target_class` (`shared/registries/skill-tool-registry.tsv` — `hunting_type` × `target_class`).
> Where we hold nothing, the row is **`INAPPLICABLE`** and must name the target fact and the absent capability
> — *"no symbolic engine in the registry targets this platform"* — never "not useful", which is `DEFERRED`.
> Known gaps are not permission to skip the class quietly: an
> `INAPPLICABLE` row backed by a fact is a coverage record, and **`DEFERRED`, `UNAVAILABLE` and `UNEXAMINED`
> cannot support an absence claim.**

Also mandatory on every engagement:
and a **dedicated novel/innovative-attack ideation pass** that pushes past known and known-advisory classes (its
leads re-enter `systematic-attacking`'s verification spine and stay leads until independently reproduced). A tool
that will not run natively on macOS (e.g. ItyFuzz — `needs_tool`, no registry/host row) is run as a Linux build in
a container (colima + docker are present on the host), never marked "couldn't run". Go **beyond commodity
tools+chaining** (AI+SAST is table stakes): custom detector queries, purpose-built symbolic/fuzz harnesses,
patch-diff N-day backport analysis, and dynamic weaponization. Impact-bar discipline holds — only intrinsic-impact
deterministic findings convert; reachability/disclosure never pays; never resubmit a
non-reproducible finding.

**Impact-class targeting (operator).** S2 pre-registers termini in the payout classes only — **funds
theft/drain · auth-bypass · privilege-escalation/ATO · private-data/PII · RCE**. Reachability/disclosure
does not pay and is at most a lead. The six 2025-26 exploit-derived audit skills wired at S3
(`erc1271-revert-data-check`, `signature-validation-audit`, `uniswap-v4-hook-access-control`,
`read-only-reentrancy-check`, `durable-nonce-exploitation`, `cross-chain-dvn-audit`) each map to a
funds-theft/auth-bypass class with a real-world loss precedent.

**Experimental fan-out (operator).** The novel-attack ideation pass is run as a real swarm step:
`experimental-attacker` (codex, `offensive_execution` hold) emits broad/novel
hypotheses as **leads only** at S2/S3; those fan out to heavy-hitter validation (Sol / Opus 5) and are
gated to ≥0.85 confidence by `multi-agent-evidence-gating` at S4 before anything reaches the operator.
Experimental leads earn **no** laxer verification than known-class ones (`systematic-attacking` Phase 3b).

**Elite tooling — prose/`needs_tool` (not live tuples).** Symbolic/fuzzing parity is already live
. Corpus B
Tier-1 additions are **not** promoted into the enforced `skill-tool-registry.tsv`, so they carry no live
tuple: **Solodit-MCP** (prior-art corpus — the tool backing `dedup-prior-art-check`) and
**Halmos-as-MCP** are `needs_tool`; a macOS-only-blocked engine (e.g. ItyFuzz) still runs as a Linux
build in a container (colima+docker present), never skipped.
