---
name: figma-implement-design
status: authored
---

# Figma Implement Design

Translate a Figma design into production UI code faithfully — tokens, components, states, and responsive behavior — not a pixel-approximation.

## Steps
1. Read the design's structure and design tokens (color, type, spacing, radius) from the source, not from a screenshot guess.
2. Map Figma components to existing code components; reuse the design system rather than re-implementing primitives.
3. Implement layout with the real layout model (auto-layout → fl/grid), not absolute pixel offsets.
4. Cover all states and variants (hover/focus/active/disabled/empty/error) and responsive breakpoints the design specifies.
5. Verify against the source for fidelity and against `wcag-conformance-audit` for accessibility; flag any design gap (missing state/token) back rather than inventing it.

## Acceptance
- Tokens and components map to the design system; no re-implemented primitives.
- All specified states, variants, and breakpoints are implemented.
- Output is verified for fidelity and accessibility; design gaps are flagged, not guessed.
