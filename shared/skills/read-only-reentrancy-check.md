---
name: read-only-reentrancy-check
status: authored
---

# Read-Only Reentrancy Check

Audit composable DeFi integrations for read-only reentrancy: while a protocol is mid-operation (its
state temporarily inconsistent and its non-reentrant *write* guard held), an attacker re-enters
through an ERC-721/1155/777 receiver hook or a native-transfer callback and reads a **view** function
(price, share value, collateral ratio) that returns a skewed value, which a *second* consuming
protocol trusts to over-borrow, mint, or liquidate.

**Source:** corpus A §III.3 (OWASP SC08 read-only reentrancy) — strategy-to-vault state mismatches in
composable lending/AMM stacks.
**Impact class:** funds theft / vault drain via mispriced valuation (intrinsic).
**Governing method:** Phase-3a hypothesis lane of `systematic-attacking`; **leads** only into the
verification spine.

## Method
1. Identify every externally-callable **view** function used by *other* protocols for pricing/valuation
   (`get_virtual_price`, `getReserves`-derived quotes, share-to-asset conversions). `slither` +
   manual mapping of cross-protocol consumers.
2. For each, check whether it can be read while the *owning* protocol holds only a write-side
   `nonReentrant` guard (no read guard) during an operation that hands control to the caller
   (token callbacks, ETH transfers, `remove_liquidity`).
3. Map the consumer: a second protocol that reads that view mid-callback and acts on it (borrow,
   mint, liquidate).
4. PoC on `anvil --fork`: trigger the owning op, re-enter via the receiver hook, read the skewed
   view, and execute the over-borrow/mint on the consumer in the same transaction. Link-level
   negative control = the same read outside the reentrant window returns the correct value and the
   consumer action reverts/nets zero.
5. Add a `medusa`/`echidna` property spanning both protocols: "consumer valuation reads are never
   served from an inconsistent mid-operation state."

## Acceptance
- Cross-protocol valuation views are enumerated with their reentrancy-window exposure classified.
- The PoC realizes a fund loss on a real fork by reading a skewed view mid-callback; the
  outside-window negative control does not.
- Finding names the view, the reentrancy window, and the consuming protocol; deduped before submission.
