# solana-anchor-audit-checklist

Known critical-bug classes for Solana programs (native or Anchor). Solana's account model breaks most EVM intuition — the attacker fully controls which accounts are passed in, so **every account is untrusted until validated.** Run all of these.

## Account validation (the #1 Solana class)
- **Owner check:** does the program verify `account.owner == expected_program_id` for every account it reads/writes? An attacker can pass a look-alike account owned by a different program. (Anchor's `Account<'info, T>` checks owner + discriminator; raw `AccountInfo` does not.)
- **Signer check:** is every authority/admin/user `Signer` actually required to sign (`is_signer`)? Missing signer = anyone acts as anyone.
- **Type/discriminator confusion:** does deserialization confirm the account is the expected type (Anchor discriminator), not another of the program's accounts of similar layout?
- **Account substitution / missing constraint:** are relationships enforced (`has_one`, `constraint = x.authority == user.key()`, the vault belongs to this config, the mint matches)? An attacker swaps in *their* vault / *their* token account.

## PDA (program-derived address)
- **Seed + bump validation:** are PDAs derived from the *expected* seeds and the canonical bump verified (`seeds`, `bump` in Anchor; `find_program_address` vs `create_program_address`)? A wrong/attacker-chosen bump or unvalidated seeds → spoofed PDA authority.
- Is the PDA used as an authority actually the program's PDA (not a passed-in account claiming to be)?

## CPI (cross-program invocation)
- **Program-id check:** is the invoked program's id verified before CPI (e.g. the real SPL Token program, not an attacker clone)?
- **Signer seeds:** are `invoke_signed` seeds correct + minimal (not leaking PDA authority to unintended CPIs)?
- **Arbitrary CPI:** does user input choose the target program/accounts? Reentrancy-style via CPI callbacks.

## Value / math / vault invariants (esp. a Peg Stability Vault / DEX / lending)
- **Arithmetic:** `checked_add/sub/mul/div`; overflow/underflow; **rounding direction** (round in the protocol's favor, never the user's); fee/bps math (`amount * bps / 10_000` order + truncation); decimals mismatch between mints.
- **Invariant preservation:** the 1:1 backing / collateralization / k-invariant holds across EVERY path incl. fees, refunds, and gas/rent reimbursement. (Historical: gas-reimbursement drawn from the vault broke a bridge's 1:1 backing.)
- **Swap direction / parity:** can direction, price, or fee be manipulated (stale oracle, attacker-set rate, missing slippage `min_out`)?
- **Mint/burn authority:** who can mint/burn; is the authority a validated PDA; can supply be inflated?

## Lifecycle / rent
- **`close`** account: is the closed account's lamports drained AND its data zeroed/reassigned to prevent revival/reinit attacks? Re-initialization of an existing account.
- **Rent-exemption** assumptions; sysvar (clock/rent) spoofing on native programs.
- Duplicate mutable accounts passed as two params (aliasing).

## Tools
`cargo-audit` (dep CVEs), `clippy`, `cargo-geiger` (unsafe census), `cargo-fuzz` (fuzz instruction handlers), `anchor test` / `anchor build` (build + localnet PoC), and manual account-table review. For an invite-only repo, request access first. Related: [[chain-impact-rescore]], [[known-advisory-backport-check]].
