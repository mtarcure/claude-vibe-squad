---
name: visual-regression-baseline
description: S4 visual-verify method — capture a stable baseline, deterministically re-capture the candidate under identical conditions, diff within tolerance with dynamic regions masked, and require a human/view_image classification of every diff. Use at the S4 acceptance gate of web-app / game-production (any UI/render change that must be judged intended movement vs accidental drift).
type: skill
---

# Visual Regression Baseline

Promoted from the authored pattern-doc `shared/skills/visual-regression-baseline.md`. Produces a deterministic
visual diff — not a screenshot glance — so a UI/render change is judged as intended design movement vs
accidental drift. The numeric diff is never the sole verdict; a human/`view_image` classification is mandatory.

## Procedure
1. **Define the capture set.** Enumerate the states to verify: routes/screens, key components, breakpoints
   (mobile/tablet/desktop), theme variants (light/dark), interaction states (hover/focus/error/empty/loading).
   Each entry is one named, reproducible capture.
2. **Establish the baseline.** On the known-good build, capture each entry to an immutable named reference (via
   `chrome-devtools`/`playwright` `take_screenshot`/`browser_take_screenshot`, fresh Chrome). Record capture
   conditions WITH it: viewport, device-scale factor, color scheme, locale, and the app build/commit. A baseline
   without its conditions is not a baseline.
3. **Neutralize non-determinism BEFORE diffing.** Fixed clock/seeded RNG, disabled animations/transitions,
   webfont-load wait, and masked dynamic regions (timestamps, avatars, ads, carousels, generated IDs). Masks are
   declared per-entry and versioned with the baseline — an unmasked dynamic region is a false FAIL.
4. **Re-capture deterministically.** On the candidate build, re-capture the SAME set under the SAME recorded
   conditions. Any condition mismatch invalidates the comparison — re-capture, never diff across conditions.
5. **Diff + compare.** Pixel/perceptual diff with a declared tolerance (anti-aliasing/sub-pixel threshold) and
   the entry's masks applied. Produce a diff artifact for every non-identical entry.
6. **Human / `view_image` classification (mandatory).** A non-zero diff is a SIGNAL, not a verdict. Review each
   diff (`view_image` on codex, or a lane image-read) and classify: **intended** (accept → promote to the new
   baseline WITH a note on what changed and why) or **regression** (reject). Never auto-accept a diff to silence
   it.

## What counts as a regression FAIL
- An out-of-tolerance delta in an UNmasked region that was not an intended, reviewed change.
- A capture that could not be produced under the recorded conditions (broken render, crash, missing state).
- A diff accepted without human/`view_image` classification (an unreviewed baseline promotion is itself a FAIL).

## When to invoke
- The S4 required visual-verify gate of `project/web-app` and `project/game-production` (and any card that must
  judge a UI/render change).

## When NOT to invoke
- No visual surface under test (headless/backend-only work).
- As a substitute for accessibility (`wcag-conformance-audit`) or functional e2e — it verifies *looks-right*, not
  *works-right* or *accessible*.

## Acceptance
- Every verified state has a named baseline WITH recorded conditions + declared masks; candidate captures use
  identical conditions (cross-condition diffs rejected).
- Every non-identical entry has a diff artifact AND a human/`view_image` classification (intended vs regression);
  baseline promotion is explicit and attributed.
- The tool's numeric diff is never the sole verdict.

## Notes — source + cross-lane discovery (honest)
- **Source:** `shared/skills/visual-regression-baseline.md` (the authored pattern-doc, retained — web-app +
  game-production S4 currently cite it as `(authored)`; that citation stays valid until a discovery-smoke
  promotes the card wiring to `(SKILL.md)`).
- **Discovery is UNVERIFIED.** Filesystem-present under the neutral `.agents/skills/` root that claude / codex /
  kimi layered discovery is expected to read; per-lane discovery has NOT been smoke-verified → registry row is
  `partial`, not `yes`.
- **Gemini** does not read `.agents/skills/`; it needs its own copy via `gemini hooks migrate` / agentskills.io
  (follow-up).
