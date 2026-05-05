# Capability Manifest: vibecoding-check

Status: draft, current-system capability
Owner: Shared / all Leads
Canonical current specialist: `shared/specialists/vibecoding-check.md`
Old plugin source: none direct in old `claude-chrono`; related concepts appear in validation and claim-gate skills.

## Role Contract

`vibecoding-check` is the mode-exit contract verifier. It mechanically checks that promises made by a mode were satisfied before a mode declares done, and escalates ambiguous failures to a specialist judgment layer.

## Preserved Current Behavior

- Three-layer shape: hook, deterministic skill/checklist, specialist tier-3 judgment.
- Verifies approvals, artifacts, citations, TODOs, phase-tags, and unauthorized deletions.
- Supports mode-specific checks for project, bounty, and content.
- Writes failure state and requires explicit override token for bypass.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve current system behavior and related validation concepts from shared skills:

- claim validation
- unauthorized deletion detection
- artifact existence checks
- citation resolution
- approval/override audit trail

## Required Tools

- Mode manifest/artifact read path.
- Git diff/snapshot comparison path.
- Citation/file existence check path.
- Approval token state path.
- Failure state write path.

## Optional Tools

- Deterministic shell/Python checker implementation.
- Mode-specific check registry.
- Tier-2 retry dispatcher.

## MCPs

- `chrono-kg`: repeated failure patterns.
- `chrono-catalog`: check/skill availability.
- `chrono-vault` / `chrono-obsidian`: state references.
- `sequential-thinking`: tier-3 ambiguous judgment.

## Skills

- `vibecoding-check`
- `claim-validation-gate`
- `cite-properly`
- `reversible-change-protocol`
- `artifact-contract-validation`

## Adaptive Operating Mode

Run deterministic checks first, auto-fix only trivial safe issues, retry responsible phase at most twice for functional failures, write pending-vibecoding state for ambiguous/exhausted failures, and require explicit operator override for bypass.

## Output Contract

- `check_result`
- `failed_checks`
- `auto_fixes`
- `tier2_retries`
- `tier3_state_path`
- `evidence_paths`
- `override_required`

## KG And Memory Behavior

- Record repeated failure patterns to SysMgmt.
- Do not hide override usage.
- Do not treat summaries or handoffs as proof of artifacts.

## Safety Boundaries

- No silent bypass.
- No unauthorized deletion approval.
- No destructive recovery without approval.
- No claiming done when required artifacts/tests/citations are missing.

## Live Dispatch Proof

1. A sample mode/run emits terminating state.
2. Vibecoding check validates artifacts/citations/approvals.
3. Failure path writes `_state/vibecoding-check/<run-id>.md` or pass path records evidence.
4. Chrono summarizes result and any operator gate.

## Public/Private Disposition

Public repo may ship prompt, manifest, check schemas, and sanitized sample states. Live approvals, private run states, and client artifacts stay local.

## Cleanup Disposition

Keep as current-system capability. Script consolidation may happen only after caller search and check coverage are preserved.
