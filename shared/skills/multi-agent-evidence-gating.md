---
name: multi-agent-evidence-gating
status: authored
---

# Multi-Agent Evidence-Gating

Never surface a candidate to the operator (or to the heavy-hitter validation lane) until a sandboxed
PoC has confirmed it with a negative control to high confidence. This encodes the elite recon→
detection→validation→reporting pipeline discipline: a potential finding is alerted only after an
isolated execution demonstrates a negative-controlled exploit under **all four observable
predicates** — oracle match, control separation, repeat stability from a clean snapshot, and harness
fidelity to production — which
collapses triage fatigue and stops low-confidence noise from reaching scarce reviewer/operator
attention.

**Source:** corpus A §II + §IV.1 (multi-agent evidence-gated automation; the source frames this as a
numeric confidence gate — we deliberately use **observable predicates instead of a score**, because a
number assigned by the lane that wants the finding is conviction wearing a measurement's clothes). Complements `systematic-attacking` Phases 5–7 by making the confidence bar explicit for
the broad experimental fan-out.
**Governing method:** the verification-spine discipline of `systematic-attacking` (Phases 5–7); this
skill is how the broad hypothesis fan-out (incl. the `experimental-attacker` lead stream) is gated
down to what a heavy-hitter lane and the operator actually see.

## Method
1. For each candidate, define the confidence signal BEFORE running: what a sandboxed PoC + negative
   control must show to count as confirmed (the real oracle responds as predicted; the negative
   control does not).
2. Execute the PoC in isolation (sandbox / read-only fork / disposable replica). Score confidence
   from concrete evidence — oracle match, negative-control separation, stability across repeats,
   harness-fidelity to prod — not vibes.
3. Gate: only candidates satisfying **all four predicates** pass to heavy-hitter (Sol / Opus 5)
   validation and the cross-family reproduction step. A candidate that fails any predicate is
   **demoted to a lead and stays in the ledger** — name the failing predicate. Demotion blocks
   promotion, never banking: an unpromoted lead remains available to composition.
4. Route the broad/novel hypothesis stream (including `experimental-attacker` output) through this
   same gate — experimental leads earn no laxer bar than known-class ones.
5. Preserve the evidence bundle (PoC, negative control, confidence rationale) so Phase 6/7 and the
   operator inherit it instead of re-deriving it.

## Acceptance
- Every alerted candidate carries a sandboxed PoC + negative control and a written rationale naming
  **which of the four predicates hold**, from concrete signals rather than conviction.
- Candidates failing a predicate are demoted to leads with the failing predicate named, and remain in the ledger — none reach the
  operator or the heavy-hitter lane un-gated.
- The experimental fan-out passes the identical gate; the evidence bundle is preserved for downstream
  verification.
