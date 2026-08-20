retired: 2026-08-19 — audited "adds nothing / no identified consumer"; see departments/sysmgmt/skill-audit-batch-*.md. Moved, not deleted.
---
name: web-performance-optimization
status: authored
---

# Web Performance Optimization

Improve real web performance by mechanism — Core Web Vitals, critical path, and payload — measured, not guessed.

## Steps
1. Measure first: capture the current metrics (LCP, INP, CLS, TTFB) and a trace; identify the actual bottleneck before changing anything.
2. Optimize the critical rendering path: reduce/blocking resources, prioritize the LCP element, defer non-critical work.
3. Cut payload and requests: image formats/sizing, code-splitting, tree-shaking, compression, caching headers.
4. Fix interactivity (INP) and layout stability (CLS): break long tasks, reserve space for async content.
5. Re-measure after each change and attribute the gain to a mechanism; report metrics as measured, never as estimated wins.

## Acceptance
- Every change targets a measured bottleneck, not a guess.
- Core Web Vitals are captured before and after; gains are attributed to a mechanism.
- Reported improvements are measured on a real trace, not estimated.
