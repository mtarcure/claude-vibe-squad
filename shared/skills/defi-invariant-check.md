---
name: defi-invariant-check
status: authored
---

<!-- inspired by trailofbits/skills (concept); repointed to native CLIs for Chrono -->

# defi-invariant-check

DeFi-specific invariant authoring and testing discipline. Use this as a sub-skill during
`evm-audit-flow` when the target is a DeFi protocol (AMM, lending, yield, bridge, stablecoin,
perps). Generic Echidna/Medusa campaigns miss DeFi-specific invariants — this skill provides
the property checklist. All tools are the **native host CLIs** (`echidna`, `medusa`, `forge`,
`halmos`) run in the target project directory; there is no wrapper layer.

## Invariant categories

**Token accounting invariants (always required):**
- `totalSupply == sum(balanceOf(all_holders))` — no spurious minting or burning.
- `reserve0 * reserve1 >= k` (for constant-product AMMs) — k-invariant never decreases except via fee accrual.
- `totalBorrow <= totalDeposit` for all lending pools — protocol cannot lend out more than deposited.
- `sum(userShares) == totalShares` for yield vaults — share accounting is consistent.

**Access-control invariants:**
- Only authorized roles can set oracle addresses, fee parameters, or pause state.
- `onlyOwner`/`onlyGovernance` functions cannot be called by arbitrary external accounts.
- Upgradeable proxy implementation slots cannot be modified except through the upgrade pathway.

**Economic/oracle invariants:**
- Spot price derived from the AMM cannot deviate from TWAP by more than N% in a single block.
- Flash loan callbacks cannot leave the protocol in a net-loss state after the loan repayment.
- Liquidation proceeds must cover the borrowed amount plus protocol fee — no bad-debt accrual from liquidations.

**Reentrancy invariants:**
- Protocol state (balances, reserves, shares) after any external call must equal the state written before the call (CEI pattern verification).
- No re-entrant call can increase the caller's balance beyond their pre-call entitlement.

## Order of ops

1. **Identify the protocol class.** AMM, lending, vault, bridge, stablecoin, or perps. Each class has a canonical invariant set (use the category checklist above).

2. **Author Echidna properties.** Write properties as Solidity functions with prefix `echidna_` that return `bool`. Properties must be pure invariants (no state mutations inside the property). Place in `test/invariants/EchidnaTest.sol`.

3. **Run Echidna** — minimum 30 minutes for DeFi protocols:
   ```bash
   echidna . --contract EchidnaTest --config echidna.yaml --test-limit 500000
   ```
   Use `testMode: assertion` in `echidna.yaml` for complex multi-step violations.

4. **Run Medusa** as a second pass if Echidna does not find violations — Medusa's
   coverage-guided corpus often finds violations Echidna's random mutation misses:
   ```bash
   medusa fuzz --config medusa.json
   ```

5. **Flash-loan attack simulation.** Manually construct a flash-loan attack call sequence in a
   Forge test that instantiates a `FlashLoanAttacker` contract, then run `forge test --match-contract FlashLoanAttacker -vvvv`. Verify the k-invariant or balance-conservation invariant holds after the attack sequence.

6. **Price-oracle manipulation check.** For protocols with on-chain price oracles: write a
   Forge test that simulates large single-block trades and checks whether the oracle-derived
   price would enable profitable liquidations or under-collateralized borrows
   (`forge test --match-test testOracleManip -vvvv`).

## When to pivot

- **Echidna cannot construct valid state transitions:** the protocol requires complex setup (governance votes, time-locks, external oracle seeding). Author a setup harness in a `CryticSetup` contract that initializes the protocol to a valid post-deployment state.
- **Invariant is too weak:** Echidna falsifies it immediately with trivial inputs. Tighten the property — e.g., add a precondition (`require(totalSupply > 0)`) to avoid vacuous falsification.
- **Protocol uses proxy pattern:** Echidna tests the proxy ABI; ensure the proxy's `fallback` routes correctly to the implementation in the test environment.

## Anti-patterns

- Do NOT author invariants that pass by construction — e.g., an `echidna_` property that trivially returns `true` because the function under test is never called.
- Do NOT treat a single Echidna `passed` result as proof of correctness — Echidna is a fuzzer, not a prover. Use `halmos` for bounded formal guarantees on critical properties (`halmos --function check_ --loop 4`).
- Do NOT skip flash-loan simulation for lending/AMM protocols — flash loans invalidate many invariants that hold under normal call conditions.

## Example

Writing and running an Echidna token conservation invariant:

```solidity
// test/invariants/EchidnaTest.sol
contract EchidnaTest {
    Token token;

    function echidna_total_supply_equals_sum() public view returns (bool) {
        // totalSupply must equal sum of all holder balances
        return token.totalSupply() == token.balanceOf(address(this))
                                     + token.balanceOf(address(0xdead));
    }
}
```

```bash
echidna . --contract EchidnaTest --config echidna.yaml --test-limit 500000
```

## Recording (chrono-vault)

After the DeFi invariant check, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="attempt", fields={"title": "defi-invariant-check on <protocol>", "body": "protocol_class=<class>; invariants_tested=<n>; violations_found=<n>; flash_loan_tested=<bool>; oracle_manip_tested=<bool>", "target": "<protocol>", "attack_class": "defi-invariant", "source_task": "<task-id>"})`.
Record a violation as `note_type="finding"` with the specific `attack_class`. A memory error
is logged in one line and never blocks the audit.
