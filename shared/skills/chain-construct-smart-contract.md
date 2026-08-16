---
name: chain-construct-smart-contract
status: authored
---

<!-- attack-chain-builder pattern, recreated against native CLIs; no upstream code copied -->

# chain-construct-smart-contract

Smart-contract specialization of `chain-construct` for **exploit-developer**: build multi-step
attack call sequences for on-chain vulnerabilities and prove them with a passing Forge (EVM) or
LiteSVM/Trident (Solana) reproduction. Follow the generic `chain-construct` method (objective as
end-state, chain head, state-feeds ordering, prove-don't-assert); this skill adds the
EVM/Solana chain primitives. Where the two conflict, the contract-level guidance here wins for
smart-contract targets. All tools are native host CLIs (`forge`, `cargo test`/`litesvm`,
`trident`, `cargo-fuzz`, `anchor`) — no wrapper layer.

## Chain primitives — EVM

**Reentrancy chain:** deploy an attacker contract whose `receive()`/`fallback()` re-enters the
target; call the withdrawable function; re-enter before the balance is decremented; repeat
until drained. Scaffold: `test/attack/AttackerReentrant.sol` + a Forge test.

**Flash-loan chain:** borrow asset X (Aave/Uniswap V3 callback); in the callback manipulate
target state (price oracle, reserve ratio, collateral); extract profit; repay loan + fee.
Scaffold: `FlashLoanAttacker.sol` implementing `IERC3156FlashBorrower` or a Uniswap V3
flash callback.

**Delegatecall-overwrite chain:** find an unprotected `delegatecall` to a caller-controlled
address; supply a malicious implementation that overwrites slot 0 (owner/admin); call a
privileged function. Scaffold: a Forge fuzz test supplying arbitrary `impl_addr`.

**Proxy-upgrade chain:** find a UUPS/Transparent proxy with a bypassable upgrade guard (missing
`onlyOwner`, missing `_authorizeUpgrade` override); `upgradeTo(malicious_impl)`; drain from the
new implementation. Scaffold: a Forge test with a `MaliciousImpl`.

## Chain primitives — Solana

**CPI privilege-escalation chain:** find an instruction that makes a CPI with caller-controlled
`signer_seeds`; derive a PDA whose seeds match a privileged authority; call with the crafted
seeds so the program signs on that authority's behalf. Scaffold: a Trident `FuzzInstruction`
supplying crafted seed arrays, or a LiteSVM test.

**Account-substitution chain:** find an instruction accepting a generic `AccountInfo` for a
privileged account type; pass a different account that passes owner/discriminator checks due to
missing validation. Scaffold: a LiteSVM test passing a crafted account buffer.

**SPL-arithmetic-overflow chain:** find token arithmetic without a `checked_*` guard; supply an
amount that overflows to a small number; withdraw more than deposited. Scaffold: a LiteSVM test
with `amount = u64::MAX`.

## Order of ops

1. **Map the chain head** — the first externally-callable function/instruction the attacker
   controls.
2. **Select the primitive** from the categories above and its scaffold.
3. **Author the attack contract/test** in `test/attack/` (Forge) or a `programs/attacker/` /
   fuzz target (Solana). Validate with `forge test --match-contract <Attacker> -vvvv`, or
   `cargo test` / `trident fuzz run <target>` / `cargo fuzz run <target>` for Solana.
4. **Gate on state confirmation** — the chain is valid only if the final state demonstrates the
   intended impact (balance drain, ownership change, unauthorized state write). Add explicit
   assertions on the expected final state; a passing test with unclear impact is not a finding.
5. **Document the chain** — entry point → numbered intermediate steps → final impact →
   preconditions (flash loan available, specific contract state, fork block). This becomes the
   PoC evidence handed to `impact-validator`.

## When to pivot

- **Chain needs live mainnet state:** use `forge test --fork-url <rpc> --fork-block-number <n>`;
  never submit a finding that only reproduces on a live fork without documenting the fork block
  and contract state.
- **Chain spans multiple blocks:** use `vm.warp()` / `vm.roll()` (EVM) or advance slots on a
  local validator (Solana); document the required delta.

## Anti-patterns

- Do NOT author chains that require compromised admin keys or any attacker-unestablishable
  precondition — out of scope for smart-contract auditing.
- Do NOT submit a chain that only works against a specific past chain state without noting the
  block-height constraint.
- Do NOT conflate a theoretical chain with a demonstrated one — the Forge/LiteSVM/Trident test
  must actually pass.
- Do NOT invoke dead `tool_wrappers` names (`forge_test`, `litesvm_test`, `trident_fuzz`); use
  the native CLIs above.

## Example

```solidity
// test/attack/ReentrancyAttacker.sol
contract ReentrancyAttacker {
    VulnerableVault vault;
    constructor(address _vault) { vault = VulnerableVault(_vault); }
    function attack() external payable {
        vault.deposit{value: msg.value}();
        vault.withdraw();
    }
    receive() external payable {
        if (address(vault).balance > 0) vault.withdraw(); // re-enter before balance update
    }
}
```

```bash
forge test --match-contract ReentrancyAttacker -vvvv
```

## Recording (chrono-vault)

After building a chain, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="attempt", fields={"title": "attack-chain: <primitive> on <target>", "body": "chain_primitive=<name>; entry_point=<...>; steps=<numbered>; impact=<...>; preconditions=<...>; test_file=<path>; reproduced=<bool>", "target": "<target>", "attack_class": "<primitive>", "source_task": "<task-id>"})`.
Record a reproduced chain as `note_type="finding"` and hand the PoC to `impact-validator`. A
memory error is logged in one line and never blocks the work.
