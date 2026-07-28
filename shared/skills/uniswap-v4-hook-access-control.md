---
name: uniswap-v4-hook-access-control
status: authored
---

# Uniswap v4 Hook Callback Access-Control Audit

Audit Uniswap v4 (and v4-style singleton/hook) integrations for the missing-caller-check class: a
custom hook callback (`beforeSwap`/`afterSwap`/`beforeAddLiquidity`/donate/etc.) that does not verify
`msg.sender == address(poolManager)` and does not validate the supplied `PoolKey`, letting an
attacker call the hook directly with forged accounting parameters to mint unbacked tokens or drain
the pool.

**Source:** corpus A §I.6 — Dedaub / Cyfrin / Cork Protocol, May 2025 ($11M pool drain).
**Impact class:** funds theft / pool drain (intrinsic).
**Governing method:** Phase-3a hypothesis lane of `systematic-attacking`; **leads** only into the
full verification spine.

## Method
1. Enumerate every hook callback the target exposes (`slither`, and read the `Hooks` permission
   bitmap on the deployed hook via `cast`).
2. For each callback, confirm BOTH guards: (a) a strict `require(msg.sender == address(poolManager))`
   (or the framework's equivalent authority check), and (b) validation that the `PoolKey` /
   currency / fee parameters correspond to a pool the hook is actually authorized for — not
   attacker-chosen.
3. Trace the hook's internal accounting: identify any state (redemption balances, reserve counters,
   minted supply) mutated inside a callback from parameters the caller controls.
4. PoC on `anvil --fork`: call the unguarded callback directly (bypassing the PoolManager) with
   inflated deposit/redemption values; assert unbacked mint or drain. Link-level negative control =
   the same call through the real PoolManager reverts or nets to zero.
5. Add a `forge`/`halmos` invariant: "hook accounting only advances via PoolManager-originated calls
   with a registered PoolKey."

## Acceptance
- Every hook callback is classified for the caller check AND PoolKey validation.
- The direct-call PoC drains/mints against a real fork; the PoolManager-routed negative control does
  not.
- Finding names the exact unguarded callback and the accounting field it corrupts; deduped against
  the Cork / v4-hook advisory corpus before submission.
