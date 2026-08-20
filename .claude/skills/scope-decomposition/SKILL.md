---
name: scope-decomposition
audience: specialist
description: "Use after the goal is understood but the work spans multiple modules, owners, or verification seams: cut it into dependency-ordered, independently shippable units with explicit write sets, exclusions, and one-sentence pass or fail checks."
---

# Scope Decomposition

Break a broad goal into shippable slices, each with its own pass/fail check, its own write set, and named exclusions, so that no unit's "done" depends on work that hasn't happened yet.

## When to use
- An ask is too large to verify in one pass, or its edges are fuzzy ("improve X", "add support for Y").
- A task will be split across specialists or dispatches and each piece needs an enforceable write scope.
- A packet's success criteria read as activities ("investigate", "refactor") rather than observable outcomes.

## Inputs
- The operator's stated goal and any constraints (deadline, dependencies, stack).
- The current state of what the ask touches: files, systems, interfaces — inventoried, not assumed.

## Steps
1. Restate the goal as an observable end-state ("requests to /api authenticate via tokens; unauthenticated requests get 401"), never as activity ("work on auth"). If you cannot, the goal is under-specified — elicit before decomposing (`requirements-elicitation`).
2. Inventory the touched surface: list the files, modules, interfaces, and external systems the goal implicates. Mark unknowns explicitly; an unknown surface is a discovery unit, not a silent risk.
3. Slice along existing seams — module, interface, data boundary — not by activity phase. "All design, then all code, then all tests" ships nothing until the end; a seam-aligned slice lands whole and verifiable.
4. Make each unit independently verifiable: it has a pass/fail check runnable without the other units existing. A unit whose verification needs a later unit is mis-cut — re-slice or merge.
5. Bind each unit to an explicit write set: the files whose changes may be integrated. Overlapping write sets between units are a hidden ordering dependency — serialize them, merge them, or re-cut the boundary so the overlap disappears. A packet's `write_scope` is enforced mechanically at controller integration, not as an action-time worker filesystem boundary.
6. Name exclusions per unit (OUT: ...). An exclusion left unstated becomes scope creep in whichever unit runs longest. Naming what a unit does NOT do is cheaper than arbitrating drift later.
7. Order by dependency, then by assumption risk: run first the unit whose failure would invalidate the most downstream slices, so a wrong assumption dies cheaply.
8. Cap unit size by the one-sentence test: if a unit's verification cannot be stated in one sentence, split it again.

## Outputs
- An ordered unit list; per unit: goal end-state, write set, IN/OUT boundary, acceptance check, dependencies.
- A stated overall done-definition: which units must pass, and what integration check proves the whole.

## Failure modes
- **Horizontal slicing** — phases instead of seams; nothing is shippable until everything is.
- **The "misc/cleanup" bucket** — an unbounded unit that absorbs all drift; dissolve it into named exclusions.
- **Activity-shaped units** — "investigate X" with no observable output; every unit ships an artifact or a decision.
- **Hidden coupling via shared files** — two "independent" units editing the same file; caught by comparing write sets, not by intuition.
- **Verification deferred to integration** — every unit "done", nothing proven until the end; each unit needs its own check.

## Worked example
Ask: "add auth to the API." End-state: every endpoint rejects unauthenticated requests; valid users get tokens. Units: (1) token issue/verify module + unit tests — writes `auth/`, OUT: any endpoint change; (2) middleware rejecting unauthenticated requests, applied to one pilot endpoint + integration test — writes `middleware/`, one route file; (3) rollout to remaining endpoints + e2e pass — writes route files only; (4) migration for existing API consumers — OUT of all prior units, explicitly. Unit 1 runs first: it holds the riskiest assumption (token scheme fits the existing session model), and units 2–3 are invalid without it. Write sets are disjoint, so 2 and 4 could parallelize after 1.

## Acceptance
- The overall goal is stated as an observable end-state, and so is every unit.
- Every unit has a pass/fail check runnable without later units.
- Write sets are explicit and pairwise-disjoint, or the overlap is declared as an ordering edge.
- Exclusions are named per unit; there is no catch-all unit.
- Unit order puts the riskiest assumption first.
