---
name: blockchain-l1
extends: bounty
status: active
---

# Bounty Profile: Blockchain L1 / Appchain / Cross-Chain Bridge

For auditing an L1/L2 node, appchain, or cross-chain interoperability protocol — Cosmos-SDK/CometBFT chains, Go/Rust node implementations, EVM/SVM gateways, TSS/MPC bridges, universal executors. (Push Chain, Osmosis-style appchains, bridge protocols.) This is NOT a Solidity-contract audit (`smart-contract.md`) nor a crypto-library review (`crypto-protocol.md`) — it's the node/protocol/interop layer.

## Auto-detection signals
- Scope repos are a node implementation (`x/` Cosmos modules, `app/app.go`, `go.mod` with cosmos-sdk/cometbft, a Substrate runtime, a Go/Rust L1)
- Mentions: L1, validator, consensus, cross-chain, bridge, gateway, TSS, universal, appchain, observe/attest/execute
- "L1 vulnerabilities" / "consensus disruption" / "node crash" in the impact definition

## Mandatory skills (read on task start — apply, don't rediscover)
- **`cross-chain-bridge-audit`** — the observe→attest→execute pipeline; inbound-forge, outbound-forge/double-spend, the finality-name trap (`GetFinalizedNonce`→`nil`=latest), quorum-defeating shared-predicate errors, TSS freeze/fail-open.
- **`cosmos-sdk-audit-checklist`** — non-determinism→fork, Begin/EndBlock panics→halt, unmetered/unbounded→DoS, ante/authz bypass, decimal precision.
- **`known-advisory-backport-check`** — pinned/forked cosmos-sdk/cometbft/cosmos-evm versions vs published advisories; fork-vs-upstream diff for dropped fixes.
- **`chain-impact-rescore`** — offensive chaining + the reachability/terminus discipline (a primitive isn't a critical until funds move at no privilege; model reorg/mempool dynamics before claiming a double-spend).

## Phase customizations
- **P1 OSINT:** prior audits of THIS protocol (Hacken/Trail of Bits/etc.) + their public findings (incomplete-fix hunt); the exact pinned commit; the consensus engine + SDK versions.
- **P2 Scope:** enumerate EVERY in-scope repo/path from the program page (they list multiple github links — get all); note it's Critical-only + the exact impact definition.
- **P4 Threat model:** map the trust/value pipeline (attestation quorum, TSS authorization, where value mints/releases). `threat-modeler` + `security-analyst`.
- **P5 Focused analysis:** run the audit skills above module-by-module; **file-complete coverage** (a coverage ledger — not just hot paths).
- **P6 PoC:** dynamic testing is mandatory for logic/nonce/reorg bugs — extract logic into a hermetic harness (mock RPC + latest/safe/finalized heads), `go test -race`, negative controls. Static isolation-review misses shared-predicate + concurrency bugs.
- **P8 Chain validation:** `impact-validator` on reachability + G3 dedup (known deps rarely pay) + G4 scope.

## Specialists most active
- `security-analyst` (Claude/Fable) — threat model, module analysis, confirm/kill
- `exploit-developer` (Codex/Sol) — PoC mechanics, hostile meta-review, dynamic harness
- `smart-contract-engineer` (Codex/Sol) — the EVM/SVM gateway + precompile + fork-diff layer
- `threat-modeler` (Claude/Fable) — the value/trust pipeline + economic surface
- **Swarm it:** run a claude panel (security-analyst + threat-modeler) in parallel with codex (smart-contract-engineer) — different surfaces, different families, concurrently.

## Tools (all installed locally; specialists shell out)
- **Go:** `gosec -severity=medium ./...`, `staticcheck ./...`, `golangci-lint`, `semgrep --config=p/gosec --config=p/golang`, `osv-scanner --lockfile go.mod`, `go test -race`, native `go test -fuzz`. (`govulncheck` needs a buildable module — often blocked by vendored crypto; use `osv-scanner`.)
- **EVM (gateway/fork):** `slither`, `myth` (Mythril), `forge`/`cast`/`anvil` (Foundry fork-and-replay + fuzz), `echidna`, `halmos`, `aderyn`.
- **Rust/Solana (gateway/vault):** `cargo-audit`, `clippy`, `cargo-geiger`, `cargo-fuzz`, `anchor`, `solana`.
- **General:** `trivy`, `grype`, `gitleaks`/`trufflehog` (secret scan — operator-gated for target orgs).
