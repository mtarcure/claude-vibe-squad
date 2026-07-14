# cross-chain-bridge-audit

Checklist for auditing a cross-chain bridge / interoperability L1 (observe→attest→execute). Apply on ANY bridge, cross-chain executor, or message-passing protocol. These are the classes that pay; run every one against the code before declaring a surface clean.

## The trust/value pipeline — map it first
Diagram: who **observes** a source event, who **attests** (which quorum/signature), what a node **trusts**, where **value moves** (mint inbound / release outbound), and what authorizes the outbound (TSS / multisig / light client). Name the attacker: *outside* the validator/attestor set, or at most one member. Everything below hangs off this map.

## Inbound (mint) — the "forge an attestation" class
- **Event authenticity:** are source logs filtered to the exact `{gateway, vault}` address AND the exact event signature? An attacker emitting a matching-signature event from an arbitrary contract must be rejected.
- **Full-tuple binding:** does the attestation/ballot key digest EVERY execution-relevant field (amount, recipient, asset, source-tx-hash, log-index, chain-id, payload)? A minority attestor must not be able to substitute one field.
- **Replay/dedup:** is `(source_chain, tx_hash, log_index)` (or equivalent) checked before execution, exactly once?
- **Quorum soundness:** eligible-voter set, `(2N)/3+1` math, repeat-vote rejection.
- **Decimals/scaling:** source↔local decimal conversion — an off-by-10^n inflates a mint.

## Outbound (release) — the "sign an unauthorized payment" + "double-spend" classes
- **Signed-payload binding:** trace the EXACT bytes handed to the signer (TSS/multisig). Does every signer independently rebuild the message from *consensused* state and refuse to sign unless it byte-matches? A coordinator supplying the payload (not just a nonce) = forge.
- **Finality on the outbound decision — THE trap:** any code that decides "this outbound failed/succeeded" must read a **finalized** chain view, not `latest`/`pending`. **Verify the SEMANTIC, not the helper name** — a function called `GetFinalizedNonce`/`getConfirmed` that internally passes `nil`/`latest`/`0` to the RPC reads *latest* and is reorg-exposed. Grep every `NonceAt`, `BlockByNumber`, `getBalance`, `getReceipt` for a `nil`/latest block arg on a security decision.
- **Asymmetric finality gates:** if the "success" path waits N confirmations but the "not-found/failure/refund" path does NOT, a premature refund + later success = double-payment. Both paths need the same finality gate.
- **Replay of the release:** a universal replay guard (executed-marker / subTxId / nonce) on EVERY outbound method (transfer, finalize, revert, rescue) — not just some. Check the destination-side dedup too.
- **Refund reversibility:** once a refund/revert is finalized, can a later "it actually succeeded" observation reverse it? If not, and both can fire, that's the loss.

## TSS / threshold-signing (if present)
- Keygen/reshare quorum: does 100% participation let ONE griefer freeze signing (→ permanent freeze of funds)? Does a stalled reshare halt the active key, or does the old key survive?
- Fail-**open** verification: any path that *accepts/signs* when a check can't run (chain-lookup unavailable, config nil) → hunt whether an attacker can force the skip. Prefer fail-closed.
- Message-to-sign bound to consensused state; nonce reuse (ECDSA k-reuse → key extraction); transport authentication (peer-id bound).

## Quorum-defeating shared-predicate errors — the deepest class
Quorum does NOT protect against a bug where **all honest nodes deterministically compute the same WRONG answer** on the same canonical input (mis-parsed amount, spoofable signature, a `latest`-read predicate, chain-id confusion). Every honest node votes the wrong way → the ballot finalizes the wrong outcome. Hunt these explicitly — they survive "2/3+1 honest" assumptions.

## Reachability discipline (before escalating)
A primitive is not a critical until the **terminus** (funds moved) is reachable at no privilege. For nonce/reorg bugs: only the bridge signs for its address, so a distinct tx at nonce `n` must come from the bridge's OWN recovery/rotation path — and **same-(sender,nonce) mempool replacement evicts the prior tx** (a payment and its refund are often the *same* event, self-defeating the double). Model it dynamically (three heads: latest/safe/finalized + reorg + mempool eviction) before claiming a double-spend. Related: [[chain-impact-rescore]].
