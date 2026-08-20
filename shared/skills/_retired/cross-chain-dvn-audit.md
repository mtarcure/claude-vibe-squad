---
name: cross-chain-dvn-audit
retired: "merged into cross-chain-bridge-audit — DVN single-signer forgery is a subset of its quorum-soundness/forge-attestation classes; LayerZero cast recipe + two-chain anvil PoC + KelpDAO advisory folded into the survivor."
status: authored
---

# Cross-Chain DVN / Bridge-Verifier Audit

Audit cross-chain messaging bridges (LayerZero-style OApp/OFT, and general lock-mint/burn-release
bridges) for weak off-chain verification: a single-signer (1-of-N with N small) or
attacker-compromisable Decentralized Verifier Network (DVN) / oracle-relayer set that can attest a
forged cross-chain message, causing the destination adapter to release assets that were never
actually burned/locked on the source chain.

**Source:** corpus C §3C — Chainalysis / Blockaid / OpenZeppelin, KelpDAO, April 2026 ($292M via a
1-of-1 LayerZero DVN compromise + RPC poisoning). The exploit used no on-chain contract bug — the
weakness was the verification-quorum configuration.
**Impact class:** funds theft / unbacked mint or release (intrinsic).
**Governing method:** Phase-3a hypothesis lane of `systematic-attacking`; **leads** only into the
verification spine.

## Method
1. Read the on-chain bridge configuration with `cast`: the DVN/verifier set, the required threshold
   (quorum), and the send/receive library wiring for each OApp/pathway. Record N and the threshold.
2. Flag any pathway whose effective quorum is 1 (or trivially small / all controlled by one operator),
   or where the message-verifying adapter (`OFTAdapter`/receive endpoint) trusts a single attestation
   without an independent second verifier or a fraud window.
3. Map the release primitive: what a forged "tokens burned on chain A" message causes on chain B
   (release/mint) and the size of the reserve it can drain.
4. PoC in a forked two-chain harness (`anvil --fork` per chain): submit a forged verified message
   through the configured verifier path and assert the destination releases unbacked assets.
   Negative control = a healthy multi-DVN quorum rejects the single forged attestation.
5. Note the off-chain amplifiers from the KelpDAO case (RPC poisoning, backup-node DDoS) as the
   realistic delivery path — but the on-chain quorum weakness is the intrinsic, submittable defect.

## Acceptance
- Every bridge pathway's verifier set, quorum threshold, and release primitive is enumerated.
- The PoC releases unbacked assets on a forked destination via a single forged attestation; a
  proper-quorum negative control rejects it.
- Finding names the pathway, the sub-quorum configuration, and the drainable reserve; deduped against
  the KelpDAO / LayerZero-DVN advisories before submission.
