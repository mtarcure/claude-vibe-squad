# Capability Manifest: Impact Validator

Status: draft
Owner: security namespace
Canonical specialist: `departments/security/specialists/impact-validator.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-impact-validator/0.2.0/`

## Role Contract

Impact Validator is the final technical submission gate for bounty findings. It owns CVSS v4.0 scoring, program fit checks, duplicate detection, NVD/OSV calibration, self-inflicted assessment, chain-impact rescore, and submit/reject routing. It does not find vulnerabilities, write PoCs, perform recon, or submit without operator approval.

## Preserved From Current Specialist

- Mandatory multi-model validation.
- CVSS v4.0 and program rubric ownership.
- Duplicate/self-inflicted/drop decision paths.
- Explicit `routing-decision.md` output.
- Escalation to `skeptic` for contested high-severity calls.

## Preserve From Old Plugin

### Required Tool Surface

- `cvss_score`
- `cvss_parse`
- `assess_impact`
- `program_fit`
- `vuln_intel_report`
- `h1_fetch_program`
- `h1_submit_report`
- `h1_check_duplicate`
- `bugcrowd_fetch_program`
- `bugcrowd_submit_report`

### Skills

- `chain-impact-rescore`
- `cvss-v4-gate`
- `nvd-osv-calibration`
- `program-fit-check`
- `self-inflicted-detector`
- shared `program-rubric-lookup`
- shared bounty preflight / approval gate

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> CVSS score -> program fit -> duplicate check -> self-inflicted assessment -> chain rescore if needed -> operator preflight gate -> routing decision
```

Required behavior:

- Reject early when score or program fit clearly fails.
- Degrade gracefully when platform API keys are missing; do not block local scoring unless live platform check is required.
- Do not silently change vectors from providing agents; request revision with rationale.
- Invoke chain-impact-rescore for multi-step chains.
- Require bounty preflight approval before any submission action.

## Output Contract

Return a structured report with:

- `ok`
- `decision`
- `gate`
- `cvss_score`
- `cvss_vector`
- `program_fit`
- `duplicate_check`
- `self_inflicted_check`
- `rationale`
- `kg_finding_id`
- `suggested_next_stage`
- missing-capability list when tools/API keys are unavailable

## KG And Memory Behavior

- Recall prior submission history before scoring.
- Record scoring attempt before gate sequence.
- Record final decision, score, program fit, duplicate status, and rationale after completion.
- Never self-promote findings or submit without operator action.

## Safety Boundaries

- No vulnerability discovery.
- No exploit/PoC authoring.
- No recon or live probing.
- No silent CVSS vector mutation.
- No platform submission without explicit operator approval.
- No storing platform credentials in tracked files.

## Live Dispatch Proof

Minimum production proof:

1. Chrono dispatches a sanitized sample finding to security namespace.
2. security namespace selects `impact-validator`.
3. Specialist runs CVSS/program-fit/self-inflicted path or returns structured missing-tool/API output.
4. Response includes routing decision and preflight requirement.
5. Active registry closes.
6. Chrono summarizes whether the finding is submit/review/reject.

## Public/Private Disposition

- Public: scoring flow, sample sanitized finding, output schema, no-auto-submit rule.
- Private/local: actual bounty reports, platform API keys, private duplicates, target evidence, submission drafts.

## Cleanup Disposition

Do not delete old plugin source until:

- this manifest is complete
- current specialist is updated from it
- sample finding live dispatch proof passes
- platform-key handling is documented in private config
