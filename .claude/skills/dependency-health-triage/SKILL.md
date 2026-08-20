---
name: dependency-health-triage
audience: specialist
description: "Use when a lockfile or vulnerability-scanner dump contains many dependency alerts and you must decide what actually needs action: derive the resolved transitive graph, merge advisories, prove vulnerable-symbol reachability and preconditions, rank intrinsic impact, assess maintenance risk, and name fixes or accepted-risk revisit conditions. Not for one vendored codebase's patch-parity review."
---

# Dependency Health Triage

Turn a raw vulnerability-scanner dump into a short, ranked list of dependencies that actually need action.

## Steps
1. Produce the true dependency graph, direct and transitive, from the lockfile rather than the manifest; the manifest understates what ships.
2. Run the scanners available on the host (`osv-scanner`, `trivy`, `npm audit`, `pip-audit`) and merge results by package and version, deduplicating advisories that describe the same defect.
3. For each advisory, determine reachability: is the vulnerable symbol called, on which path, and with what input? An unreached CVE is inventory, not risk.
4. Check exploitation preconditions the advisory assumes — a specific configuration, a parser mode, an exposed listener — against how this project actually uses the package.
5. Rank surviving items with `review-severity-ladder`, using intrinsic impact, not CVSS alone; CVSS is context-free and systematically overstates.
6. Assess maintenance health separately from vulnerabilities: release cadence, single-maintainer risk, unmaintained transitive pins, and packages whose upstream has been renamed or transferred.
7. For each actionable item, name the fix — version bump, pin, patch, replace, or accept — and the compatibility risk of that fix.
8. Record accepted risks explicitly with the reason and a revisit condition, so acceptance is a decision rather than a silence.

## Acceptance
- Findings come from the lockfile graph, with transitive dependencies included.
- Every retained finding states its reachability and the calling path.
- Unreachable and precondition-unmet advisories are listed as suppressed, with the reason.
- Ranking uses intrinsic impact; raw CVSS is not the sole justification.
- Each action names the fix and its compatibility risk; accepted risks state a revisit condition.
