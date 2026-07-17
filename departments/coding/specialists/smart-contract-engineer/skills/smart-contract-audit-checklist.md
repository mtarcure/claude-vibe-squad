---
name: smart-contract-audit-checklist
description: "Use when auditing Solidity smart contracts — covers vulnerability classes, severity rubric, audit workflow phases, and per-class red flags."
source: "tamjid0x01/SmartContracts-audit-checklist + cryptofinlabs/audit-checklist (REMAKE 2026-05-03 — squad-format port, no upstream code copied)"
version: 1.0.0
applies_to:
  - departments/coding/specialists/smart-contract-engineer
  - departments/security/specialists/security-analyst (when target is Solidity)
---

# Smart Contract Audit Checklist

Distilled walkthrough for auditing Solidity contracts. Drives a concrete read order, vulnerability sweep, severity assignment, and report shape. Use as a checklist — tick items off, don't merely read.

## Pre-audit setup

Before reading any code:

1. **Confirm scope.** Files in scope, commit hash, deployment chain(s), out-of-scope dependencies (e.g., OpenZeppelin contracts at fixed version). Reject "audit the whole protocol" without commit pin.
2. **Capture protocol intent.** Read whitepaper / README / NatSpec. Write a 5-line summary of what the protocol *should* do — drift from this is where bugs live.
3. **Inventory privilege.** List every `onlyOwner` / `onlyRole` / `Ownable` / `AccessControl` function. Owner-controlled invariants must be documented.
4. **Inventory external calls.** Every `call` / `delegatecall` / `transfer` / `send` / `safeTransferFrom` to non-static targets — these are reentrancy seeds.
5. **Inventory math.** Every division, every `unchecked` block, every fixed-point library use, every conversion between token decimals.
6. **Compiler & dependencies.** Solidity version pinned? `pragma solidity ^0.x.y` with floating minor version is a smell. Dependencies at audited versions? Imports grouped and named?
7. **Test baseline.** Does `forge test` / `hardhat test` pass at the audited commit? If not, raise as Q1 to client before continuing.

## Vulnerability class checklist

Each class lists: red flags to grep for, common-bug pattern, recommended check.

### 1. Reentrancy (SWC-107)

Red flags: state mutation *after* an external call; non-`nonReentrant` function with `.call{value:}()`; ERC-777/ERC-1155 hooks called before balance update; cross-function reentrancy via shared storage.

Check: Apply checks-effects-interactions strictly. For every external call, verify all storage writes happen before the call, OR the call is to a known-safe contract (well-audited, immutable, no callback paths). Cross-function reentrancy: list all functions sharing the mutated storage and verify they're either all guarded or none are exploitable.

### 2. Access control & privilege

Red flags: missing modifier on state-changing function; `tx.origin` used for auth (SWC-115); initializer callable twice; constructor logic in proxy without `_disableInitializers`; `transferOwnership` to `address(0)` un-bricked; role grant without role admin.

Check: Every external/public state-changing function has an explicit access decision (open / restricted / role-gated). Initializers have `initializer` modifier and are unreachable post-init. Proxies have `_disableInitializers()` in the implementation constructor.

### 3. Integer overflow / underflow (SWC-101)

Red flags: `unchecked { ... }` blocks containing user-influenced arithmetic; pre-0.8.0 code without SafeMath; downcasts `uint256` → `uint128` without explicit bounds check.

Check: Solidity ≥0.8 has built-in checks — confirm version pin. Every `unchecked` block must be justified inline with a comment proving non-overflow (typically: comparison done above, or values come from a bounded source).

### 4. Unchecked external calls (SWC-104)

Red flags: `(bool ok, ) = target.call(...)` with `ok` ignored; ERC20 `transfer` return value not checked (some non-standard tokens revert silently); low-level call success interpreted as function existed.

Check: Every external `.call` checks the bool return AND the return data. Every ERC20 use goes through `SafeERC20.safeTransfer` / `safeTransferFrom`. Phantom-function risk: a contract-existence check (`extcodesize` or constructor pattern) is required when the target may not be a contract.

### 5. Oracle manipulation

Red flags: `getReserves()` from a single Uniswap V2 pool used directly as price; spot price (no TWAP) feeds a critical decision; Chainlink feed read without staleness check (`updatedAt`, `answeredInRound`).

Check: AMM spot price is never an oracle. Chainlink reads check `updatedAt > block.timestamp - heartbeat` AND `answeredInRound >= roundId`. TWAP windows are protocol-justified (not "we picked 30 minutes" without analysis). Multiple-oracle median where high-value flows depend on price.

### 6. Front-running / MEV (SWC-114)

Red flags: large value flows on public mempool transactions where attacker reordering changes outcome; trade execution without slippage parameters; commit-reveal pattern absent where order matters; on-chain auctions with last-block bidding.

Check: Every user-facing trade accepts `minAmountOut` / `deadline`. Auctions use commit-reveal or sealed-bid. Approval-then-call patterns audited for sandwich potential. Where front-running is unavoidable, document it as a known limitation with operator awareness.

### 7. Governance attacks

Red flags: governance token snapshot at vote-cast time (allows flash-loan); proposal queue without timelock; quorum thresholds set in storage and mutable by the same governance; emergency pause without separate role.

Check: Vote weight uses checkpointed balances at proposal-creation block, not vote-cast block. Timelock between approval and execution ≥48h for high-impact actions. Emergency pause is a separate, narrow-scope role (not full owner).

### 8. Signature replay (SWC-121, SWC-122)

Red flags: `ecrecover` without nonce; signature without `block.chainid`; signature used across upgrades without domain-separator versioning; `s` value not enforced to lower half of curve order.

Check: Every signed message includes a nonce that's incremented on use. Domain separator includes `chainid` and contract address. Use OZ's `ECDSA.recover` (which rejects malleable signatures) rather than raw `ecrecover`. EIP-712 typed data preferred over `abi.encodePacked` for hashing.

### 9. Denial-of-service (SWC-113, SWC-128)

Red flags: unbounded loop over user-controlled array; push-payment to a list of recipients (one revert blocks all); state mutation requiring exact gas amount; external dependency that can be made to revert (e.g., NFT royalty hook).

Check: Pull-payment pattern preferred. Loops over arrays have caller-bounded length OR explicit max-length constants. External calls in loops handle individual failures via try/catch.

### 10. Price manipulation / flash-loan attacks

Red flags: collateral valuation uses a manipulable on-chain spot price; lending protocol with single-block borrow-then-liquidate path; rebase token used as fixed-supply asset; LP token valued at spot reserves rather than k-invariant-derived.

Check: Critical valuations use TWAP or independent oracle. Flash-loan-aware design: simulate "attacker borrows X, manipulates pool, calls victim function, repays" — does it net them value? LP-token pricing follows Alpha Homora's "fair LP token price" formulation where reserves can be manipulated.

### 11. Time manipulation (SWC-116)

Red flags: `block.timestamp` used for short intervals (<15s) where miner can shift; `block.number` used as wall clock (block time varies); `now` keyword (deprecated alias).

Check: `block.timestamp` only for intervals where ±15s drift is acceptable (typically: vesting cliffs in days/weeks). Never as a randomness source. `block.number` only for block-counted operations, not time-counted ones.

### 12. Gas griefing (SWC-126)

Red flags: subcall whose return value matters but caller forwards limited gas (`call{gas: 2300}`); function callable by anyone that consumes large gas with no payback; relayer pattern where relayer is forced to pay.

Check: Bound gas forwarded to callbacks. Self-griefing from owner is fine; griefing of relayers/users by attackers is not.

### 13. Delegatecall risks (SWC-112)

Red flags: `delegatecall` to user-supplied address; storage layout collision between proxy and implementation; uninitialized implementation (Parity wallet bug pattern); `selfdestruct` callable inside delegatecall context.

Check: `delegatecall` targets are whitelisted constants OR proxies whose implementation is admin-controlled. Implementation contracts called in proxy context disable `selfdestruct` at the implementation. Storage layout deltas across upgrades use OZ's storage gap pattern.

### 14. Randomness (SWC-120)

Red flags: `blockhash`, `block.timestamp`, `block.difficulty` / `block.prevrandao` used directly as randomness for value-bearing decisions; pseudo-random based on user-controllable inputs.

Check: Value-bearing randomness uses Chainlink VRF or equivalent committed-randomness scheme. `blockhash` is acceptable only for low-stakes UI tie-breaking, never lottery / NFT-trait selection / liquidation order.

### 15. Storage & layout hazards

Red flags: state variable shadowing (SWC-119); struct packing across multiple `SSTORE` operations when single would suffice; uninitialized storage pointer reads; mapping inside dynamic array (deletion footgun).

Check: Storage reads/writes minimized — repeated reads in a function should be cached to memory. Packing intentional and documented. No `delete` on dynamic arrays containing mappings.

## Severity rubric

Calibrated to Solidity-specific patterns. When a specific program's rubric differs, it overrides this.

| Severity | Examples | Threshold |
|----------|----------|-----------|
| **Critical** | Direct fund theft (any user funds at-risk via single tx); permission bypass to mint / drain; unauthorized upgrade path | Attacker extracts value with no preconditions beyond standard user role |
| **High** | Conditional fund theft (requires specific market state, attacker capital, or partial trust); permanent freezing of >1% TVL; oracle break that causes mispricing | Significant loss likely under realistic conditions |
| **Medium** | Temporary DoS; griefing requiring attacker capital ≥ damage caused; slippage exceeding documented bounds; off-by-one in fee/reward accounting | Function impaired but recoverable; no direct loss |
| **Low** | Edge-case revert; missing event emission for off-chain monitoring; gas waste; documentation drift | No security impact, but degrades quality |
| **Informational** | Style; compiler warning; named-arg consistency; outdated NatSpec | No functional impact |

Rules:
- Centralization risk: an admin-only path that drains funds is High *unless* the program explicitly accepts admin trust (always state the assumption explicitly).
- Self-inflicted: only the victim can trigger → Informational. (Per `chrono.plugin.impact-validator/self-inflicted-detector`.)
- Theoretical without realistic preconditions → demote one tier.
- "Speculative on future code": invalid unless contest scope explicitly includes the future change.

## Tooling chain

Run in this order; each step's output feeds the next.

1. **Slither** (`slither .`) — fast static analysis, catches the obvious 80%. Always first. False-positives are common; review every flag, don't auto-trust.
2. **Solhint / forge fmt** — style + obvious gotchas (visibility, naming).
3. **Foundry / forge test** — confirm baseline tests pass at the audited commit.
4. **Forge invariant tests** (`forge test --match-contract Invariant`) — most-bang-for-buck for finding economic bugs. Prioritize over unit tests for audit work.
5. **Mythril** (`myth analyze <file>`) — symbolic execution. Slow; run on contracts with high external-call density.
6. **Echidna** — property-based fuzzer. Invest where invariant tests reveal a pattern worth fuzzing deeper.
7. **Halmos** — symbolic test execution for Foundry projects. Good for proving small invariants.
8. **Manual stance fanout** (per chrono `multi-stance-audit-fanout` skill) — final sweep with reentrancy / access-control / oracle / economic / cross-contract stances run in parallel.

For Solana / Anchor work, use the `solana-audit-flow` skill instead — different tool chain (Aderyn, LiteSVM, Anchor build).

## Reporting format

Each finding is a self-contained file with these sections:

```
# [SEV] Title — concise (one sentence)

**Severity:** Critical | High | Medium | Low | Informational
**Class:** <vulnerability class from checklist above>
**Affected:** <file:line — exact location of the bug>

## Description
What the bug is. Two paragraphs max. Don't restate the protocol.

## Impact
What an attacker gains. Quantify when possible (TVL at risk, $ profit per attack, who loses).

## Proof of Concept
Foundry test (`function test_*`) that fails at the audited commit and passes after the recommended fix. Include the exact `forge test --match-test test_<name> -vvv` output.

## Recommended Mitigation
The smallest change that closes the bug. If multiple options, list trade-offs.

## References
- SWC-### (if applicable)
- Prior public disclosure of similar bug (link)
- Related findings in this audit (cross-reference)
```

Each report file is independently reviewable. Do not assume the reader has read other findings.

Final deliverable: an `audit-report.md` index that lists all findings by severity with one-line summaries, plus a `defensive-pattern-discovery.md` documenting what the protocol *correctly* defends against (so future auditors don't re-flag mitigated risks).

## Cross-references

- `chrono.plugin.smart-contract-engineer/evm-audit-flow` — full EVM audit workflow.
- `chrono.plugin.smart-contract-engineer/multi-stance-audit-fanout` — parallel multi-stance run for high-stakes audits.
- `chrono.plugin.smart-contract-engineer/defi-invariant-check` — DeFi-specific invariants.
- `chrono.plugin.smart-contract-engineer/defensive-pattern-discovery` — read protocol's defenses before flagging.
- `chrono.plugin.impact-validator/cvss-v4-gate` — for findings going to bounty programs that score CVSS.
