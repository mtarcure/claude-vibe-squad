---
name: vibecheck
audience: specialist
description: "Use immediately before declaring a task or session done—run the discipline checks that catch scope creep, leftover artifacts, unsolicited refactoring, and inflated prose, and block the completion claim on any failure unless the operator supplies a recorded override reason."
---

# Vibecheck

A last sweep before `done`. It exists because the defects that survive to the end of a task are not
usually logic errors — those get caught by tests. They are **discipline** defects: scratch files nobody
removed, work done outside what was asked, a refactor nobody requested, a summary that oversells. Each
is individually small and each erodes the trust that makes the next completion claim believable.

Run it when the work is finished and *before* the completion message is written.

## Relationship to claim-evidence work
Vibecheck does **not** re-do claim verification. Run every falsifying check after the last edit and pair
its evidence to the corresponding claim; `claim-verification` owns decomposing load-bearing claims and
mapping each to exact evidence. Check C1 below confirms that work *happened*; it does not repeat it.

The checks unique to this skill are the behavioural ones — C2 through C9. That is where its value is.

## The checks

**C1 — no false done.** The summary must not claim verification that did not occur. If it says tests
pass, a validator is green, or something works, the corresponding output must have been run and read this
session, after the last edit. Confirm the falsifying checks ran after the last edit and their evidence is
paired to those claims; do not repeat the checks here.

**C2 — leftover artifacts are detected and reported, not silently removed.** Scan for scratch files,
temp scripts, debug output, commented-out experiments, and one-off helpers left in the tree, and
**list them in your response**. Two specific traps: a throwaway script written for a one-time job is
not a deliverable and should not persist as though it were reusable; and a test spawn, mock, or
fixture left behind will later read as real state and mislead whoever finds it.

**Do not delete them.** Cleanup and deletion require explicit operator approval under Hard Rule 6, and
neither authorship nor write scope waives that gate — "I made it, so I may remove it" is exactly the
reasoning the rule exists to stop. Report the inventory and let Chrono obtain approval. This check may
still block "done" while cleanup is pending: an unreported leftover is a defect, an unapproved
deletion is a rule violation, and reporting is the only move that is neither.

**C3 — state is where it needs to be.** Work that must reach a remote, a shared location, or an outbox
has actually gone there. A completed change sitting only in a local tree is not delivered, and "done"
claimed against an unpushed branch is a false claim about the world.

**C4 — no runaway loop.** No sign of the same call repeated against the same arguments with the same
result. A retry loop that eventually succeeded still indicates something worth reporting, and one that
never succeeded but was worked around silently is a finding being suppressed.

**C5 — no compatibility cruft.** No `_v2`/`_old`/`_new`/`_bak` names, no parallel implementations left
side by side, no walls of commented-out prior code, no `TODO: remove` added this session. These are
decisions deferred into the tree, where they become someone else's problem.

**C6 — no unsourced metrics.** Every number characterising performance, size, coverage, or improvement
traces to a measurement. A percentage, a multiplier, or a "reduced by" figure with no run behind it is
fabricated, however plausible. Estimates are permitted when labelled as estimates.

**C7 — honest register.** No "robust", "seamless", "production-ready", "comprehensive", "blazing fast",
"enterprise-grade". These words carry no information and are used precisely where evidence is thin.
Describe what was built and what was verified.

**C8 — scope discipline.** The work matches what was asked. Anything touched beyond the stated scope is
named explicitly rather than folded into the summary. Where the task declared a write scope, no **out-of-scope change was delivered for integration** - a
trusted worker may use scratch paths, but integrated residue stays in scope (write_scope is an
integration contract, not an action-time filesystem boundary; `shared/protocol.md` §
read_scope/write_scope). A task that genuinely needed a wider integrated scope should have surfaced
that need rather than quietly widening. If **this** packet expressly imposes action-time confinement,
apply that stricter rule instead.

**C9 — no unsolicited abstraction.** No "while I was in there", no opportunistic refactor, no base class
extracted, no helper generalised, unless it was asked for. Unrequested restructuring inflates the diff,
obscures the actual change, and transfers review cost to someone who did not agree to it.

## Steps
1. Gather what the checks read: the summary about to be sent, the working-tree status, the diff, and the
   original task statement with its declared scope.
2. Run all nine checks in order and record a verdict for each: pass, fail, or skip.
3. **Skip honestly.** A check with no input to read is *skipped*, not passed — an empty tree status makes
   C2, C3, and C5 unevaluated, and recording those as passes manufactures assurance the sweep never
   established. Skips are reported.
4. On any failure, do not send the completion message. Report each failure with the specific evidence
   that triggered it and the concrete fix.
5. On a clean sweep, proceed — and state which checks were skipped, so the reader knows the sweep's
   actual coverage.

## Override
The operator may override a failure with an explicit, non-empty reason. The reason is recorded alongside
the result and the status becomes a warning rather than a block.

There is no silent override. An override without a stated reason is not an override — it is the check
being ignored, which is the exact failure this skill exists to make visible. Only the operator overrides;
a worker facing a genuine blocker surfaces it and stops.

## Failure modes
- **Self-certification** — running the sweep against the summary you wish you were sending.
- **Skip-as-pass** — unevaluated checks reported as clean, inflating apparent coverage.
- **Scope laundering** — extra work described in language broad enough to sound in-scope.
- **Override by habit** — a standing reason reused until the check is effectively disabled.
- **Post-hoc sweep** — running it after the completion message rather than before, when the only
  remaining option is retraction.

## Acceptance
- All nine checks were evaluated and each carries pass, fail, or skip; skips are reported as skips.
- No completion message was sent while a check was failing and un-overridden.
- Each failure is reported with its triggering evidence and a concrete fix.
- Any override carries a non-empty operator-supplied reason, recorded with the result.
- Out-of-scope work and unrequested refactoring are named explicitly rather than absorbed into the summary.
