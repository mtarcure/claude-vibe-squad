---
name: signature-validation-audit
status: authored
---

# Signature-Validation Audit (ECDSA fallback · precompile shadowing)

Audit signature-verification code for two 2025-26 auth-bypass classes that let an attacker forge a
"valid" signer: (a) **ECDSA-fallback impersonation** — a failed `ecrecover`/`tryRecover` (zero
address) silently falls back to an ERC-1271 contract check whose signer address is
attacker-influenced; and (b) **precompile shadowing** — using `code.length == 0` as sole proof of an
EOA, so the `0x1`–`0x9` precompiles (zero code length, non-reverting) are treated as EOAs and shadow
the verification.

**Source:** corpus A §I.4 (Verichains / Sodium, July 2026, ~$270k — ECDSA fallback) and §I.5
(Verichains / Odos, Jan 2025, ~$50k — precompile shadowing).
**Impact class:** funds theft / auth bypass (intrinsic).
**Governing method:** Phase-3a hypothesis lane of `systematic-attacking`; emits **leads** only, held
to the identical verification spine.

## Method
1. Enumerate every signature entrypoint (`validateUserOp`, permit paths, meta-tx relays, order
   settlement) with `slither` + a custom `semgrep` rule; map each to its recovery primitive.
2. **ECDSA fallback:** flag any path where `ecrecover`/`ECDSA.tryRecover` returning `address(0)` (or
   a malformed-sig branch) does NOT hard-revert but instead routes to an ERC-1271 check. Verify the
   ERC-1271 signer is bound to an **immutable, preconfigured owner**, never a user-supplied payload
   field.
3. **Precompile shadowing:** flag any EOA/contract discrimination that relies on `extcodesize`/
   `code.length`. Build a `forge` boundary test that supplies precompile addresses `0x01`–`0x09` as
   the signer and asserts they are rejected.
4. PoC on `anvil --fork`: supply an attacker contract (fallback case) or a precompile (shadowing
   case) as signer and drive an unauthorized approval/withdrawal; link-level negative control =
   a correctly-bound verifier rejects it.
5. Add `echidna`/`medusa` properties: "zero-address recovery never authorizes" and "signer code
   length is never the sole EOA proof."

## Acceptance
- Every signature entrypoint's recovery + fallback logic is classified.
- Zero-address recovery hard-reverts; ERC-1271 fallback signer is immutable; precompile addresses are
  rejected — each proven by a passing boundary test.
- The PoC forges auth against a real fork with a negative control; finding is deduped against the
  Sodium/Odos advisories before submission.
