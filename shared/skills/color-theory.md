---
name: color-theory
status: authored
---

# Color Theory

Choose and justify a color system for a design by mechanism — harmony, contrast, and meaning — not by taste alone.

## Steps
1. State the job the palette must do: hierarchy, mood, brand fit, and any accessibility target.
2. Build the palette from a defined relationship (complementary, analogous, triadic, mono) plus neutrals; give each role a name (primary/accent/surface/text), not just a hex.
3. Check contrast for every text/background pair against the WCAG target (hand off measurement to `wcag-conformance-audit`); never ship a pair on vibes.
4. Account for color meaning/culture and color-vision deficiency; ensure no state is encoded by hue alone.
5. Define the palette as tokens with light/dark values so the system, not a one-off, carries the color.

## Acceptance
- Each color has a named role and a stated relationship to the others.
- Every text/background pair meets the declared contrast target; no hue-only signaling.
- The palette is expressed as reusable tokens, not scattered hex values.
