---
name: multi-agent-evidence-gating
status: authored
---

# Multi-Agent Evidence-Gating

Never surface a candidate to the operator (or to the heavy-hitter validation lane) until a sandboxed
PoC has confirmed it with a negative control to high confidence. This encodes the elite recon→
detection→validation→reporting pipeline discipline: a potential finding is alerted only after an
isolated execution demonstrates a negative-controlled exploit at **≥ 0.85 confidence**, which
collapses triage fatigue and stops low-confidence noise from reaching scarce reviewer/operator
attention.

**Source:** corpus A §II + §IV.1 (multi-agent evidence-gated automation; 0.85+ confidence gate before
human alert). Complements `systematic-attacking` Phases 5–7 by making the confidence bar explicit for
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
3. Gate: only candidates at ≥ 0.85 confidence pass to heavy-hitter (Sol / Opus 5) validation and the
   cross-family reproduction step. Below-threshold candidates are demoted to leads or dropped, with
   the failing signal recorded.
4. Route the broad/novel hypothesis stream (including `experimental-attacker` output) through this
   same gate — experimental leads earn no laxer bar than known-class ones.
5. Preserve the evidence bundle (PoC, negative control, confidence rationale) so Phase 6/7 and the
   operator inherit it instead of re-deriving it.

## Acceptance
- Every alerted candidate carries a sandboxed PoC + negative control and a written ≥ 0.85 confidence
  rationale from concrete signals.
- Below-threshold candidates are demoted/dropped with the failing signal named — none reach the
  operator or the heavy-hitter lane un-gated.
- The experimental fan-out passes the identical gate; the evidence bundle is preserved for downstream
  verification.
