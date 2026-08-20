---
name: visual-verify
audience: specialist
description: Use when a rendered UI has been built or changed and is about to be accepted — at the S4 Verify gate of a web, game, or other visual capability, before any ship step. Drives the "seen, driven, and measured" acceptance pass; the pixel-diff half belongs to `visual-regression-baseline`.
---

# Visual Verify

Run the acceptance pass that makes a rendered UI *accepted* rather than merely *built*. A UI is not
accepted because its tests pass or its code reads correctly — it is accepted when it has been **seen**
(captured and looked at), **driven** (a real user journey exercised against it), and **measured**
(accessibility and performance scored against declared thresholds).

This is the written-down form of a standard the squad already applies: `shared/capabilities/project/web-app.md`
and `shared/capabilities/project/game-production.md` both declare S4 as a **required** acceptance gate whose
FAIL blocks the S6 ship step. This skill is the procedure for that gate.

## When to use
- At **S4 Verify** in the S0–S7 project lifecycle (`shared/modes/project.md`) for any capability whose
  deliverable renders: web app, game production, or a visual surface inside another card.
- A UI change is being handed to review or ship and no one has looked at it.
- A packet asks for "visual verification", screenshots, or a Lighthouse/a11y score.

Skip it — as an explicit, recorded no-op — for backend, CLI, library, and other non-rendering
deliverables. Record the skip and its reason; do not silently omit the gate.

## Division of labour with `visual-regression-baseline`
These are not duplicates and must not be merged.

- **`visual-regression-baseline`** owns the *diff*: defining the capture set, freezing non-determinism,
  masking dynamic regions, comparing candidate against baseline under identical recorded conditions, and
  classifying each delta as intended or regression.
- **This skill** owns the *gate*: deciding the gate applies, obtaining a reachable target, running the
  capture / journey / audit passes, invoking the diff skill when a baseline exists, and producing a single
  accept-or-block verdict for S4.

When a baseline exists, step 4 below hands off to `visual-regression-baseline` rather than restating it.

## Inputs
- A reachable target: a dev-server URL, a local build, or a running app instance. The packet or the S3
  build handoff supplies it; this repo has no shared pipeline-state object to read it from, so if the
  target is absent the gate is **blocked**, not passed.
- The declared thresholds for the run. Defaults below are a starting point, not a standard — confirm
  against the packet or the capability card before treating a number as a gate.
- The baseline, if one exists, plus its recorded capture conditions.

## Steps
1. **Confirm the gate applies and the target is reachable.** Establish the deliverable renders, then load
   the target once and confirm it serves. An unreachable target is a blocked gate — never a pass, and
   never a "capture what we can" partial.
2. **Drive the key user journeys.** Exercise the primary journeys end to end against the running app
   (`playwright` or `chrome-devtools`), not against a mock. A UI that renders but cannot be used has
   failed the gate. Record which journeys ran and their outcomes; a journey that was not run is reported
   as not run, never inferred from a passing unit test.
3. **Capture the viewport matrix.** Capture each canonical viewport, waiting for the page to settle
   before each capture:

   | Viewport | Size | Stands in for |
   |---|---|---|
   | Mobile portrait | 320 × 568 | Smallest realistic phone; where overflow appears first |
   | Tablet portrait | 768 × 1024 | The breakpoint most often skipped |
   | Laptop | 1280 × 800 | The default development viewport |
   | Desktop | 1920 × 1080 | Where fixed-width layouts strand content |

   Adjust the matrix when the product's real breakpoints differ — but state the matrix you used.
4. **Look at the captures, and diff if a baseline exists.** Read every capture back through an image-read
   (`view_image` on the codex lane, or the lane's native image read). *Capturing a screenshot is not
   seeing it* — an unreviewed PNG is an artifact, not evidence, and this is the single most common way
   this gate is faked. Where a baseline exists, run `visual-regression-baseline` for the comparison and
   classification; where none exists, this run is capture-only — record the captures as candidates and
   state plainly that no diff was performed.
5. **Run the accessibility and performance audit.** Score the target and compare against the declared
   thresholds. Common defaults, to be confirmed rather than assumed: accessibility ≥ 90, performance ≥ 80.
   Pair the numeric score with `wcag-conformance-audit` — a passing aggregate score routinely hides
   specific conformance failures, because the score is an average and conformance is a conjunction.
6. **Classify each failure before reporting it.** Separate (a) a local fix the builder can make — contrast,
   a missing label, an unoptimized asset; (b) a design gap needing a decision; (c) a capability gap where
   a tool was unavailable. These route differently, and collapsing them into one "visual verify failed"
   line destroys the routing information.
7. **Emit one verdict with its evidence.** Accept only when the journeys pass, the captures were reviewed,
   the diff (if any) is classified, and the thresholds are met. Name what was not checked.

## Tool surface — and what is actually verified about it
This skill names tools it needs; it does **not** assert they are live for you.

- `playwright` and `chrome-devtools` carry registry rows `yes · subscription` with lanes
  `claude|codex|gemini`. **Kimi is absent from that lane list** — this gate cannot be run unaided on
  every lane, and a lane without browser tools must report a capability gap rather than approximate the
  pass.
- **Browser contract — `shared/lifecycle.md` rule 11 governs, and is the only place it is written.**
  Settled 2026-08-03 by operator decision. Read rule 11 before any browser step of this gate: it
  carries the attach procedure, the persistent-profile path, the never-spawn prohibitions, and the
  one permitted exception (hermetic, unauthenticated acceptance testing may use a fresh isolated
  profile with its own `user-data-dir`, labelled as such in the report).

  Local to this gate, and stated nowhere else: `playwright` and `chrome-devtools` observably spawn a
  fresh, isolated Chrome. The registry and `shared/api-catalog.md` describe that behaviour
  accurately — treat the description as a **hazard to route around, not a sanctioned mode**. A fresh
  profile has none of the operator's session, so a "pass" produced through one is a pass for a
  logged-out stranger, not for the operator's journey.
- The Lighthouse audit is a tool *inside* the `chrome-devtools` MCP, not a registry row of its own.
  Confirm it appears in your runtime's tool list before planning around it.
- No `computer-use` capture path is wired here. If the browser MCPs are unavailable, the honest outcome
  is a reported capability gap — not a degraded pass.

Per Hard Rule 9, a tool is available when a live call succeeds, never because a registry row or this
document says so. Probe first; report `capability_gap` and use the packet's fallback if the probe fails.

## Failure modes
- **Screenshot-as-evidence** — captures produced but never read back. The most common fake pass.
- **Silent skip** — the gate omitted for a rendering deliverable with no recorded reason.
- **First-run diffing** — reporting drift against a baseline that does not exist. First run is
  capture-only; say so.
- **Score-only accessibility** — an aggregate number treated as conformance.
- **Threshold drift** — the defaults above quoted as if they were the project's declared gate.
- **Journey inference** — "the tests pass, so the journeys work". The gate exists because that inference
  is what fails in practice.

## Acceptance
- The gate was run or explicitly, reasonedly skipped; an unreachable target blocked it rather than passing it.
- Key user journeys were driven against the running app, and the ones that ran are named.
- Every viewport in the stated matrix was captured **and read back** through an image-read.
- Diffing either ran through `visual-regression-baseline` with each delta classified, or is reported
  absent because no baseline existed.
- Accessibility and performance were scored against thresholds sourced from the packet or capability
  card, and paired with a conformance check rather than standing alone.
- Every failure carries its classification; every unavailable tool is reported as a capability gap
  rather than silently dropped.
