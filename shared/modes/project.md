---
name: project
version: 1.0
primary_lead: coding
status: active
phases: 9
---

# Mode: Project

For building, refactoring, or shipping code. Primary Lead is Coding (Codex).

## Phase ownership at a glance

| Phase | Name | Lead | Specialists / dispatch |
|---|---|---|---|
| 0 | Discovery + Scope Audit | Chrono direct + operator | none |
| 1 | Intake / Definition | Coding / Codex | `product-manager`, `architect` for repo orientation when needed |
| 2 | Design | Coding / Codex | `architect`; Security `security-analyst` if security-touching |
| 3 | Implementation Plan | Coding / Codex | `planner` |
| 4 | Build | Coding / Codex | `backend-engineer`, `frontend-engineer`, `ui-engineer`, etc. |
| 5 | Review | Coding / Codex | `code-reviewer` |
| 6 | Test / Verification | Coding / Codex | `test-engineer` |
| 7 | Validation | Coding + Security if needed | `skeptic`; Security `impact-validator` if relevant |
| 8 | Release / Handoff | Coding + Content | Content `technical-writer` if needed |

## Triggers

```yaml
intent_phrases: ["let's build", "implement", "let's go on this", "ship this", "refactor"]
url_patterns: []  # github.com/<repo> can suggest, but operator confirms
file_types: [".py", ".ts", ".tsx", ".js", ".rs", ".go", ".swift"]  # weak signal — confirm
negative_triggers: ["just curious", "explain", "what is"]
```

Engagement requires explicit operator yes (or `/project` slash command).

## Lead ownership

- primary_lead: coding
- backup_lead: none
- allowed_cross_leads: [security, research, content, sysmgmt]

## Phases (8 total + Phase 0 audit)

### Phase 0: Discovery + Scope Audit

Owner: Chrono direct + operator
Specialists: none — Chrono clarifies whether Project Mode is the right mode before Coding receives a build task
Input: operator's initial ask, linked repo/PR/issue if any, current mode context
Output: `project-scope-card.md` with goal, target repo, success criteria draft, constraints, approval-sensitive areas, and whether this should instead be Content / Research / Maintenance / Incident / Bounty
Multi-model: no
Operator gate: SOFT (operator confirms this is a project and names priority)
Advance when: mode fit is confirmed, target workspace is known, and Chrono has enough scope to dispatch Coding without guessing.

### Phase 1: Intake / Definition

Owner: coding namespace
Specialists: product-manager, architect when repo orientation is needed
Input: operator's stated goal
Output: `requirements.md`, `constraints.md`, `acceptance-tests.md`
Multi-model: no
Operator gate: SOFT (operator can clarify)
Advance when: success criteria, affected files, non-goals, test command all known

### Phase 2: Design

Owner: coding namespace
Specialists: architect (multi-model: Codex + Claude), security-analyst (cross-Lead if security-touching)
Input: Phase 1 outputs
Output: `design.md`, `risk-register.md`
Multi-model: yes (architect always multi-model)
Operator gate: HARD (operator approves spec before plan)
Advance when: design ≤1 page, all interfaces named, operator approves

### Phase 3: Implementation Plan

Owner: coding namespace
Specialists: planner (cross-cutting, multi-model)
Input: Phase 2 design
Output: `plan.md` with file ownership, checkpoints, rollback notes
Multi-model: yes (planner)
Operator gate: HARD for large refactors / migrations / auth changes; SOFT otherwise
Advance when: file-level plan exists, dependencies mapped, operator approves

### Phase 4: Build

Owner: coding namespace
Specialists: backend-engineer / frontend-engineer / ui-engineer / etc. — whichever matches the work
Cross-Lead: Security for auth/crypto, Research for unfamiliar libs, Content for user-facing copy
Input: Phase 3 plan
Output: code changes + `build-log.md`
Multi-model: no (single-model execution)
Operator gate: HARD before destructive commits (rebase --force, schema migrations, etc.)
In-phase checkpoint: skeptic's diff-atomicity-verify if diff > 10 files
Advance when: planned file ownership is satisfied, build artifacts are produced, and any destructive action has an operator approval token.

### Phase 5: Review

Owner: coding namespace
Specialists: code-reviewer (multi-model — Codex+Claude+Gemini, writer family excluded)
Input: Phase 4 code changes
Output: structured review findings
Multi-model: yes
Operator gate: SOFT (operator sees findings, can override)
Advance when: zero blockers in findings (or operator overrides specific blockers)

### Phase 6: Test / Verification

Owner: coding namespace
Specialists: test-engineer (single-model, tool-grounded)
Input: Reviewed code
Output: `test-results.md`
Multi-model: no (tool-grounded execution; multi-model adds nothing)
Sub-streams: unit + property + e2e + visual-regression (if UI) + a11y (if UI) + load (if perf-sensitive) + cross-browser (if web)
Operator gate: SOFT
Advance when: all tests green or failures documented as pre-existing

### Phase 7: Validation

Owner: coding namespace with Security cross-Lead if security touched
Specialists: skeptic (cross-cutting, multi-model), impact-validator (Security cross-cutting if relevant)
Input: Tested code
Output: `validation.md`, `release-risk.md`
Multi-model: yes (skeptic always)
Operator gate: SOFT
Advance when: validation confirms acceptance criteria and release risk is documented.

### Phase 8: Release / Handoff

Owner: coding namespace
Specialists: technical-writer (Content cross-Lead)
Input: Validated code
Output: PR description, changelog, deployment notes, KG writeback
Multi-model: no
Operator gate: HARD (operator approves PR/deploy)
Pre-release: vibecoding-check fires (universal + project-extension)
Advance when: operator approves the PR/deploy/handoff package, durable artifacts are written, and cleanup declarations have been applied.

## Cross-Lane Routing Rules

```
need: security_review_of_auth_change
  to_model: claude
  specialist: security-analyst
  source_namespace: security
  compatibility_namespace: security
  mailbox_path: shared/mailbox/coding-to-security/
  return_artifact: shared/mailbox/security-to-coding/RESP-<id>.md
  async: yes

need: research_unfamiliar_library  
  to_model: kimi
  specialist: research
  source_namespace: research
  compatibility_namespace: research
  mailbox_path: shared/mailbox/coding-to-research/
  return_artifact: shared/mailbox/research-to-coding/RESP-<id>.md
  async: yes
```

## Multi-model overrides per phase

```yaml
phase_2_design: [codex, claude]  # writer ≠ reviewer enforced
phase_5_review: [codex, claude, gemini]  # always 3 reviewers, writer family excluded
phase_7_validation: [claude, codex, gemini]  # skeptic always multi-model
all_others: single-model
```

## Operator checkpoints

```yaml
hard_gates:
  - phase_design_to_plan_gate: "operator approves design (1-page spec)"
  - phase_plan_to_build_gate: "operator approves implementation plan (for large refactors)"
  - phase_build_destructive_action_gate: "operator approves before any rebase/migration/destructive command"
  - phase_review_blocker_override_gate: "operator can override specific blockers"
  - phase_release_gate: "operator approves PR / deploy"

soft_gates:
  - phase_discovery_to_intake_gate: "operator confirms Project Mode fit"
  - phase_intake_scope_clarification_gate: "operator can clarify scope"
```

## Termination

```yaml
completion: "PR merged or operator accepts final local state"
explicit_stop: "operator says stop / /exit"
hard_gate: "pause indefinitely until operator returns"

NOT termination conditions:
  - wall-clock time
  - operator absence
  - dispatch count

after_completion: state = COMPLETED, run stays in runs/ — does NOT auto-archive
```

## KG writes (required)

```yaml
on_completion:
  - vault/projects/<project-name>/decisions.md (architectural decisions)
  - vault/projects/<project-name>/patterns.md (reusable patterns surfaced)
  - vault/instincts/<lead>-insights.jsonl (per-Lead learnings appended)
```

## Cleanup

Durable / ephemeral declarations are inherited from `shared/mode-cleanup.md` Project Mode defaults.

```yaml
durable_artifacts:
  - committed code changes
  - ADRs / design docs
  - tests and verification records
  - deploy configs
  - final PR / handoff notes

ephemeral_artifacts:
  - scratch specs
  - exploratory branches not merged
  - prototype directories
  - draft PRs not opened

operator_decision_artifacts:
  - unshipped feature branches
  - WIP PRs
```

```yaml
on_archive (operator-explicit):
  - move runs/<id>/ to runs/_archive/<date>/<id>/
  - run chrono-handoff-authoring → docs/handoffs/<date>-post-<project>-handoff.md
  - run vibecoding-check final pass
```

## Profiles

See `shared/mode-profiles/project/` for per-target-type variants:
- `web-app.md` — Next.js / React / Vue
- `ios-app.md` — Swift / SwiftUI / Xcode
- `android-app.md` — Kotlin / Play Store
- `backend-service.md` — Python / Rust / Go service
- `cli-tool.md` — argparse / clap / cobra
- `library.md` — public package, semver, docs
- `agent-app.md` — Anthropic / OpenAI SDK
- `static-site.md` — Hugo / Jekyll / Astro
