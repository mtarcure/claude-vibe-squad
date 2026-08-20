---
name: diff-aware-semgrep-scan
audience: specialist
description: "Use when reviewing a particular code change against a large pre-existing Semgrep baseline: fix the base commit, choose rules by language and change shape, surface new or newly exposed source-to-sink paths, and report parse or coverage gaps. Route recurring false positives to semgrep-rule-author."
---

# Diff-Aware Semgrep Scan

Scan only what changed, with the rules that matter for the change, so static-analysis signal survives contact with a large legacy baseline.

## Steps
1. Fix the comparison range (`git diff --name-only <base>...HEAD`) and collect changed files plus their language mix.
2. Select rule packs by language and by change shape — auth, deserialization, templating, SQL, subprocess, crypto — rather than running one generic pack over everything.
3. Run `semgrep --config <packs> --baseline-commit <base>` so pre-existing findings are suppressed and only newly-introduced ones surface.
4. Re-run without the baseline flag on the changed files alone when a finding's history matters; a pre-existing issue in a file the change now exposes to untrusted input is a new risk even though the line is old.
5. Triage every hit against `findings-filter`: reachability from an untrusted source, attacker-controlled input, and real consequence.
6. For each true positive, capture the rule id, the file:line, the data path from source to sink, and the minimal fix.
7. For each false positive, record why the rule misfired; recurring misfires are input to `semgrep-rule-author`, not something to silence per-finding.
8. Report scan coverage honestly: files skipped for parse errors or unsupported languages are gaps, not passes.

## Acceptance
- The scan states its base commit and the rule packs selected, with a reason for the selection.
- Newly-introduced findings are separated from pre-existing ones.
- Every reported finding has a source-to-sink path, not just a rule match.
- False positives are explained, and repeat offenders are routed to rule authoring.
- Unscanned or unparsed files are listed as coverage gaps.
