---
name: visual-regression-baseline
status: authored
---

# Visual Regression Baseline

Capture stable, comparable visual references so a UI/render change can be judged as intended design movement
vs. accidental drift — a deterministic diff, not a screenshot glance.

## Steps
1. **Define the capture set.** Enumerate the states that must be verified: routes/screens, key components,
   breakpoints (mobile/tablet/desktop), theme variants (light/dark), and salient interaction states
   (hover/focus/error/empty/loading). Each entry is one named, reproducible capture.
2. **Establish the baseline.** On the known-good build, capture each entry to an immutable, named reference
   (via `chrome-devtools`/`playwright` `take_screenshot`/`browser_take_screenshot`, fresh Chrome). Record the
   capture conditions with it: viewport size, device-scale factor, color scheme, locale, and the app
   build/commit. A baseline without its conditions is not a baseline.
3. **Neutralize non-determinism BEFORE diffing.** Freeze or mask sources of pixel noise that are not the
   change under test: fixed clock/seeded RNG, disabled animations/transitions, stable fonts (wait for
   webfont load), and masked dynamic regions (timestamps, avatars, ads, carousels, generated IDs). Masks are
   declared per-entry and versioned with the baseline — an unmasked dynamic region is a false FAIL.
4. **Re-capture deterministically.** On the candidate build, re-capture the SAME set under the SAME recorded
   conditions. Any condition mismatch (viewport, scale, theme, locale) invalidates the comparison — re-capture,
   do not diff across conditions.
5. **Diff and compare.** Compare candidate vs. baseline per entry. Use a pixel/perceptual diff with a declared
   tolerance (anti-aliasing/sub-pixel threshold) and the entry's masks applied. Produce a diff artifact
   (highlighted delta image) for every non-identical entry.
6. **Human/`view_image` review of diffs.** A non-zero diff is a SIGNAL, not a verdict. Review each diff image
   (`view_image` on the codex lane, or a lane image-read) and classify: **intended** (accept → promote to the
   new baseline, with a note on what changed and why), or **regression** (reject). Never auto-accept a diff to
   silence it.

## What counts as a regression FAIL
- A visual delta outside tolerance in an UNmasked region that was NOT an intended, reviewed change.
- A capture that could not be produced under the recorded conditions (broken render, crash, missing state).
- A diff accepted without human/`view_image` classification (an unreviewed baseline promotion is itself a FAIL).

## Acceptance
- Every verified state has a named baseline WITH its recorded capture conditions and declared masks.
- Candidate captures are produced under identical conditions; cross-condition diffs are rejected, not tolerated.
- Every non-identical entry has a diff artifact AND a human/`view_image` classification (intended vs regression).
- Baseline promotion is explicit and attributed; dynamic-region masking is versioned with the baseline.
- The tool's numeric diff is never the sole verdict — an out-of-tolerance unmasked delta blocks acceptance
  until reviewed, and a masked/tolerated delta is documented, not hidden.
