---
name: detection-tuning
status: authored
---

# Detection Tuning

Reduce a rule's false-positive/false-negative surface with evidence, not guesswork.

## Steps
1. Measure current FP/FN against representative data; capture the noisy conditions.
2. Identify the cause of each false positive (benign pattern, missing context, over-broad match).
3. Adjust thresholds/allowlists/conditions — each change backed by a concrete example.
4. Re-measure FP/FN; confirm true positives still fire (fixtures still pass).
5. Document the precision/recall trade-off and the residual risk accepted.

## Acceptance
- Before/after FP/FN are measured, not asserted.
- Each change is tied to a concrete example; positive fixtures still pass.
- Residual risk is stated explicitly.
