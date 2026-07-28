---
name: erc1271-revert-data-check
status: authored
---

# ERC-1271 Revert-Data Confusion Check

Audit smart-contract-wallet signature validation for the "revert-data trick": a low-level
`staticcall`/`call` to `isValidSignature(hash,sig)` whose EVM success flag is ignored, so an
attacker-deployed verifier that *reverts* with the ERC-1271 magic value (`0x1626ba7e`) in its
revert reason is misread as a valid signature — authorizing a drain.

**Source:** corpus A §I.3 — ChainSecurity / Zodiac Roles Modifier / Gnosis Pay, June 2026 (~$1.5M).
**Impact class:** funds theft / full wallet drain (intrinsic — clears the impact bar).
**Governing method:** a Phase-3a hypothesis lane of `systematic-attacking`; emits a **lead** only —
it re-enters the Phase 4–8 verification spine (runnable PoC on a mainnet fork, negative control,
G1–G4, cross-family repro) before it is ever a finding.

## Method
1. Grep the target for every ERC-1271 consumer: `isValidSignature`, the `0x1626ba7e` magic value,
   and low-level `staticcall`/`call` into a signer address (`slither`, `semgrep` custom rule,
   `cast` for on-chain bytecode).
2. For each call site, confirm the code checks the call's **success boolean** BEFORE decoding
   `returnData`. The bug pattern is `(, bytes memory ret) = signer.staticcall(...)` followed by
   `ret[:4] == MAGIC` with the success flag discarded, or an `assembly { returndatacopy }` that
   never checks `success`.
3. Build the differential PoC in Foundry: deploy a malicious verifier that `revert`s with
   `abi.encode(0x1626ba7e)` (or raw bytes) in its reason; call the target's auth path with it as
   the declared signer.
4. `forge` test on an `anvil --fork` of the real deployment: assert the drain succeeds against the
   live contract state, then assert a success-checked reference implementation rejects it
   (link-level negative control).
5. Add a `halmos`/`forge` invariant: "no auth path accepts a signature whose verifier call
   returned `success == false`."

## Acceptance
- Every ERC-1271 / low-level-signer call site is enumerated with its success-flag handling classified.
- The PoC drains against a real mainnet fork, not a mock, and the negative control (success-checked
  variant) rejects the same input.
- Finding names the exact call site, the ignored success flag, and the realized fund impact; it is
  deduped against prior Zodiac/ERC-1271 disclosures before submission.
