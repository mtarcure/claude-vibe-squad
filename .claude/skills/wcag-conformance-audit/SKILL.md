---
name: wcag-conformance-audit
audience: specialist
description: "Use when a UI or media deliverable needs a criterion-by-criterion WCAG conformance decision, including keyboard, focus, accessibility-tree, contrast, reflow, motion, and screen-reader evidence. An automated score or screenshot alone cannot pass."
---

# WCAG Conformance Audit

Audit a UI or media asset against a WCAG target with per-criterion evidence — not a screenshot glance.

## Steps
1. Set the conformance target (WCAG 2.2 A / AA / AAA) and platform.
2. Audit beyond the visible: semantic/accessibility tree, keyboard/focus order and traps, contrast, zoom/reflow, motion, input alternatives, screen-reader behavior.
3. Cite the specific success criterion for every finding; rate severity.
4. Specify an engineer-actionable remediation per finding.
5. Return PASS/HOLD; document automated-tool limitations rather than trusting them.

## Acceptance
- Every finding cites a WCAG success criterion.
- Keyboard and screen-reader behavior are covered; a screenshot/automated pass alone is never PASS.
- Remediations are specific and actionable.
