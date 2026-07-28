---
name: review-severity-ladder
status: authored
---

# Review Severity Ladder

Rank findings on one shared ladder so severity means the same thing across reviewers, specialists, and models.

## Steps
1. Place each finding on the ladder by consequence, not by effort to fix and not by how interesting it is:
   - **critical** — data loss, credential exposure, unauthorized state change, or silent corruption reachable on a normal path.
   - **high** — wrong results, broken invariant, or availability loss on a reachable path; correct behavior depends on luck.
   - **medium** — wrong behavior on an edge, boundary, or error path; degraded but recoverable.
   - **low** — quality, clarity, or duplication that will cause a future defect but causes none now.
   - **note** — observation with no defect claim.
2. Justify each placement with the consequence and the path that reaches it. "Could be a problem" is not a placement.
3. Apply the reachability test before assigning critical or high: name the entry point, the actor, and the input that gets there. Unreachable code caps at medium.
4. Apply the intrinsic-impact test: a finding that only reveals information already disclosed, or that requires privileges the attacker would not have, does not clear high.
5. Separate severity from confidence. A high-severity finding you are unsure of is `high / unconfirmed` — never demote severity to express doubt, and never inflate confidence to justify severity.
6. Set a severity floor for the deliverable and report everything at or above it; list the rest as notes rather than discarding them.
7. When the ladder produces repeated critical findings on the same mechanism, the correct move is to remove or bound the mechanism, not to keep escalating the threat model.

## Acceptance
- Every finding carries exactly one rung and a one-line consequence statement.
- Critical and high findings name entry point, actor, and reaching input.
- Severity and confidence are recorded as separate fields.
- The deliverable states its severity floor.
- Placements are defensible without reference to how hard the fix is.
