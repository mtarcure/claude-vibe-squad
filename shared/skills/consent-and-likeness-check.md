---
name: consent-and-likeness-check
status: authored
---

# Consent and Likeness Check

Verify that any asset resembling a real, identifiable person carries the consent its intended use requires.

## Steps
1. Detect real-person likeness — voice, face, or persona — in the asset.
2. Require documented consent scope, OR confirm the asset is synthetic-generic (no identifiable person).
3. Confirm the intended use (channel, territory, duration) falls within the consent granted.
4. Flag any unconsented real-person likeness → `HOLD`; do not clear it.
5. Route PII/biometric processing to `privacy-steward`; likeness work may require both, and neither is legal counsel.

## Acceptance
- Any real-person likeness has consent on file or is HELD.
- Consent scope matches the intended use.
- Privacy/biometric handoff is made where processing is involved.
