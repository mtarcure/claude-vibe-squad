retired: 2026-08-19 — audited "adds nothing / no identified consumer"; see departments/sysmgmt/skill-audit-batch-*.md. Moved, not deleted.
---
name: responsive-design
status: authored
---

# Responsive Design

Build a layout that works across viewports and inputs — fluid, breakpoint-aware, and content-driven — not a fixed desktop shrunk down.

## Steps
1. Design content-out: define the content priority and let breakpoints follow where the layout actually breaks, not fixed device widths.
2. Use fluid units and modern layout (flex/grid, clamp/min-max) so the design scales between breakpoints, not just at them.
3. Handle input and capability differences (touch targets, hover-optional, reduced-motion, safe-area insets).
4. Test the real content extremes (longest string, largest image, empty state) at each breakpoint.
5. Verify accessibility at each size (reflow to 320px/400% zoom without loss) via `wcag-conformance-audit`.

## Acceptance
- Breakpoints are driven by where the layout breaks, not arbitrary device widths.
- Layout scales fluidly between breakpoints and handles touch/hover/reduced-motion.
- Reflow/zoom accessibility holds; real content extremes are tested, not just ideal mocks.
