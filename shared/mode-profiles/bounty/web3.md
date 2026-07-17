---
name: web3
extends: bounty
status: active
---

# Bounty Profile: Web3 Protocol

For DeFi protocols where contracts AND frontend are in scope. Combines smart-contract analysis with web-app testing.

## Auto-detection signals

- URL on an authorized DeFi bug-bounty program
- Mention of "DeFi protocol", "DEX", "lending", "MEV"
- Repository contains both contracts/ AND frontend code

## Phase customizations

Apply the union of `smart-contract.md` profile (for contract layer) AND `web-app.md` profile (for frontend layer). Both lanes run in parallel.

### Specific to web3

- Frontend ↔ contract integration vulns (e.g., approving wrong contract)
- Wallet interaction security (signed-message reuse, EIP-712 issues)
- Oracle manipulation crossing on-chain to off-chain
- MEV (sandwich, front-run, back-run)
- Protocol-level economic attacks (governance, incentive misalignment)

### Tools

Smart-contract side: Slither, Mythril, Foundry, Echidna, Halmos
Frontend side: Burp + wallet sims (Anvil, MetaMask test accounts)
Cross-cutting: Tenderly for chain-state simulation, foundry for fork-and-replay

## Specialists most active

- smart-contract-engineer
- exploit-developer (multi-model — Codex + Claude both)
- security-analyst (frontend audit)
- threat-modeler
- defensive-pattern-discovery (chrono skill)
- impact-validator with chain-impact-rescore + financial-impact analysis
