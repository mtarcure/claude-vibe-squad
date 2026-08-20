---
name: requirements-elicitation
audience: specialist
description: "Use when an operator or stakeholder request is too vague or conflicting to convert directly into testable scope: ask a bounded question ladder, label assumptions DEFAULT or BLOCKING, turn adjectives into measurable outcomes, and confirm IN and OUT boundaries plus verification methods before decomposition."
---

# Requirements Elicitation

Turn a vague operator ask into requirements that are observable, testable, and confirmed — surfacing every silent assumption as either a stated default or a blocking question before any scope is cut.

## When to use
- The ask is goal-shaped but fuzzy ("build X", "make Y better", "add support for Z") and would otherwise go straight to design.
- Stakeholder statements conflict, or the "done" condition is unstated.
- Before `scope-decomposition`: decomposition of an unelicited ask bakes the wrong goal into every slice.

## Inputs
- The operator's stated goal, verbatim, plus any constraints already given (deadline, stack, dependencies, budget).
- Existing context: what already exists, what must not change, prior decisions on record.

## Steps
1. Restate the ask as one sentence of observable outcome from the operator's perspective. If you cannot, that gap is your first question — do not paper over it with a plausible guess.
2. Climb the question ladder, one rung per gap: **goal** (what does success look like; what breaks if this doesn't happen), **actors** (who uses it, who operates it), **scope edge** (what is explicitly out), **constraints** (stack, deadline, dependencies, budget), **acceptance** (how will you check it's done). Ask 2–3 targeted questions per round, batched — a drip of single questions stalls the task; an interrogation of twenty exhausts the operator.
3. Surface assumptions instead of silently making them. Write each one down marked **DEFAULT** ("proceeding with this unless corrected") or **BLOCKING** ("cannot proceed without an answer"). Defaults keep momentum; blockers justify a `blocked` status. An assumption that never got written down is the one that sinks the build.
4. Convert every requirement to testable form: an observable behavior plus a measurable threshold. Rewrite each quality adjective — fast, robust, clean, simple, secure — into a number or a checkable condition ("p95 under 200ms on the current dataset", "restart resumes without data loss"). An adjective that survives into the requirements is a future dispute.
5. Hunt the requirement classes operators reliably omit: error paths, empty/zero/first-run states, permissions and roles, concurrent use, migration of existing data, rollback, non-functional bounds (performance, cost), and operational reality (who runs it, where it logs, who gets paged).
6. Frame acceptance criteria as checkable outcomes, each naming its verification method — a test, a command, an observation. "Criterion passes when `<check>` shows `<result>`" is the shape; a criterion no one can run is a wish.
7. State negative scope item by item: OUT means named exclusions, not silence. Every named exclusion is a scope-creep argument that never has to happen.
8. Play the requirements back for confirmation. A requirement the operator has not confirmed is still an assumption — record sign-off, or record the DEFAULT and move on. If two stakeholder statements genuinely conflict, surface the tradeoff with both options and their costs; never average them into something nobody asked for.

## Outputs
- A requirements document: goal (one paragraph, operator's perspective), IN/OUT scope lists, acceptance criteria with verification methods, constraints, done-definition.
- The assumption log: every DEFAULT and every BLOCKING question, with resolutions as they land.

## Failure modes
- **Interrogation stall** — endless clarifying rounds instead of DEFAULT-marked assumptions; elicitation is meant to converge in one to two rounds.
- **Solutioning during elicitation** — recording "use Postgres" when the requirement was durability; capture the need, leave design to the architect.
- **Surviving adjectives** — "should be fast" reaching the criteria list untested and unmeasurable.
- **Averaged conflicts** — merging contradictory stakeholder asks into a middle thing instead of escalating the tradeoff.
- **Positive-only scope** — nothing named OUT, so every later "obviously that was included" succeeds.
- **Phantom confirmation** — treating your own restatement as agreed because nobody objected to what nobody read.

## Worked example
Ask: "make the dashboard faster." Restated outcome: "the ops dashboard becomes responsive enough that the on-call engineer stops opening raw logs instead." Ladder round one: which page and which percentile ("initial load of the incident view; it's the p95 that hurts"), what threshold counts as fixed ("under 2s on the office connection"), what's out ("don't touch the admin views"). Assumptions logged: DEFAULT — current data volume is representative; BLOCKING — none. Adjective conversion: "faster" → "incident view p95 initial load < 2s at current data volume, measured by the existing synthetic check". Omitted-class sweep adds two requirements the operator confirms: the empty state (no incidents) must not regress, and the fix must not raise infra cost. OUT: admin views, historical-data archive page, any visual redesign. Acceptance: synthetic-check p95 < 2s for seven consecutive days; empty-state render test passes; infra cost delta ≤ 0. Played back; operator confirms; decomposition starts from a goal that is now checkable.

## Acceptance
- The goal is restated as an observable outcome and confirmed, or the blocking gap is escalated rather than guessed.
- Every silent assumption is written down as DEFAULT or BLOCKING; no unlogged assumptions.
- No quality adjective survives without a measurable or observable form.
- Every acceptance criterion names its verification method.
- Scope has named exclusions; conflicts were surfaced as tradeoffs, never averaged.
