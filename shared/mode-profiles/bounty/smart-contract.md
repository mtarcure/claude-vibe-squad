---
name: smart-contract
extends: bounty
status: active
---

# Bounty Profile: Smart Contract

For Solidity / Vyper / Rust smart contract audits (Code4rena, Immunefi, etc.).

## Mandatory skills (read on task start)
- **`solana-anchor-audit-checklist`** — for Solana/Anchor/Rust programs (account/owner/signer validation, PDA seeds+bump, CPI, rent/close, vault-invariant + parity/fee math). Use this for Peg Stability Vaults, DEXes, lending.
- **`known-advisory-backport-check`** — for any forked/pinned dependency (OZ, solmate, cosmos-evm) vs published advisories.
- **`chain-impact-rescore`** — offensive chaining + reachability/terminus discipline.
Tools: `slither`, `myth`, Foundry (`forge`/`cast`/`anvil`), `echidna`, `halmos`, `aderyn` (EVM); `cargo-audit`, `clippy`, `cargo-geiger`, `cargo-fuzz`, `anchor`, `solana` (Rust/Solana). Build a runnable PoC (`forge test` / `anchor test` on a localnet fork).

## Auto-detection signals

- URL on code4rena.com OR immunefi.com
- Files ending in .sol, .vy, .rs (with Anchor / Solana / contract patterns)
- Mention of "audit contest", "DeFi protocol", "EVM", "Solana"
- Repository structure with `contracts/`, `programs/`, `src/lib.rs`

## Phase customizations

### Phase 2: Program Scope (smart-contract additions)

Additional specialists:
- smart-contract-engineer (primary) — reads protocol architecture
- pre-audit-threat-model — chrono skill, x-ray of permission graph + protocol classification

Additional outputs:
- `contracts.md` — deployments, addresses, source links, chain
- `protocol-architecture.md` — control flow, key functions, accepted vuln classes per program scope
- `oracle-integrations.md` (if relevant)
- `bridge-architecture.md` (if relevant)

Tools added:
- chain-explorer MCPs (Etherscan, Solscan, etc.)
- contract address parser
- ABI reader

### Phase 3: Recon (smart-contract additions)

Specialists:
- smart-contract-engineer
- security namespace invokes `exploit-developer` via `Task` tool with `subagent_type: exploit-developer` (multi-model)

Tools:
- Slither (Solidity static analysis)
- Mythril (symbolic execution)
- Aderyn (Rust-based Solidity static analysis)
- Local fork (foundry / hardhat)

Multi-model: yes — chrono's `multi-stance-audit-fanout` (8 specialist stances)

### Phase 4: Threat Modeling (smart-contract additions)

Focus areas:
- Access control (msg.sender, ownable, roles)
- Reentrancy (CEI pattern violations)
- Oracle manipulation (price feeds, single-source dependencies)
- Integer over/underflow (still relevant in unchecked blocks)
- Economic invariants (slippage, fee accumulation, MEV)
- Cross-contract assumptions

### Phase 6/7/8: Exploitation (smart-contract additions)

Test infrastructure:
- foundry test scripts as PoCs (Solidity)
- hardhat scenarios (TypeScript)
- LiteSVM unit tests for Solana
- Anchor scenarios

Each PoC IS a foundry/hardhat/anchor test — reproduces deterministically.

### Phase 8: Chain Construction (smart-contract specific)

Specialists:
- chain-construct-smart-contract (chrono skill)
- security namespace invokes `skeptic` via `Task` tool with `subagent_type: skeptic` with chain-atomicity-verify instructions

Output:
- `chain-attack.sol` — multi-call exploit
- `chain-impact.md` — TVL at risk, attacker profit calculation

### Phase 10: Validation (smart-contract additions)

Specialists:
- defi-invariant-check (chrono skill)
- security namespace invokes `impact-validator` via `Task` tool with `subagent_type: impact-validator` with chain-impact-rescore instructions

Tools:
- SI/SLI mapping
- Money-flow analysis (where do funds end up after exploit)
- TVL calculation at exploit time

Output:
- `financial-impact.md` — quantified attacker profit, victim loss
- `severity-justification.md` — Code4rena severity (High/Medium/Low) per their rubric

### Phase 11: Report (smart-contract additions)

Specialists:
- technical-writer
- smart-contract-engineer (final review)

Submission format:
- Code4rena: severity / attack scenario / impact / proof of concept / recommended mitigation
- Immunefi: severity / vulnerability type / target / steps to reproduce / impact / proposed solution

Output: per-platform submission package, populated via persistent browser session

## KG writes (smart-contract specific)

```yaml
- vault/security/findings/F-NN-<title>.md (with Solidity/protocol context)
- vault/security/protocols/<protocol-name>.md (architecture intel for re-targeting)
- vault/security/sc-techniques/<technique>.md (e.g., "oracle manipulation via price-pump")
```

## Specialists active in this profile

- smart-contract-engineer (primary, coding namespace — but security namespace orchestrates)
- security namespace invokes `exploit-developer` via `Task` tool with `subagent_type: exploit-developer` (Codex + Claude multi-model)
- security namespace invokes `skeptic` via `Task` tool with `subagent_type: skeptic` (cross-cutting, multi-model)
- security namespace invokes `impact-validator` via `Task` tool with `subagent_type: impact-validator` (cross-cutting, multi-model)
- security namespace invokes `threat-modeler` via `Task` tool with `subagent_type: threat-modeler`
- defensive-pattern-discovery (chrono skill — what defenses ARE in place?)
- gptscan-prompt-templates (chrono skill — vuln-class-aware LLM scaffolding)
