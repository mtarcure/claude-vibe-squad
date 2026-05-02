---
name: project
version: 1.0
primary_lead: coding
status: active
phases: 8
---

# Mode: Project

For building, refactoring, or shipping code. Primary Lead is Coding (Codex).

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

## Phases (8 total)

### Phase 1: Intake / Definition

Owner: Coding Lead
Specialists: product-analyst (cross-cutting), repo-scout
Input: operator's stated goal
Output: `requirements.md`, `constraints.md`, `acceptance-tests.md`
Multi-model: no
Operator gate: SOFT (operator can clarify)
Advance when: success criteria, affected files, non-goals, test command all known

### Phase 2: Design

Owner: Coding Lead
Specialists: architect (multi-model: Codex + Claude), security-analyst (cross-Lead if security-touching)
Input: Phase 1 outputs
Output: `design.md`, `risk-register.md`
Multi-model: yes (architect always multi-model)
Operator gate: HARD (operator approves spec before plan)
Advance when: design ≤1 page, all interfaces named, operator approves

### Phase 3: Implementation Plan

Owner: Coding Lead
Specialists: planner (cross-cutting, multi-model)
Input: Phase 2 design
Output: `plan.md` with file ownership, checkpoints, rollback notes
Multi-model: yes (planner)
Operator gate: HARD for large refactors / migrations / auth changes; SOFT otherwise
Advance when: file-level plan exists, dependencies mapped, operator approves

### Phase 4: Build

Owner: Coding Lead
Specialists: backend-engineer / frontend-engineer / ui-engineer / etc. — whichever matches the work
Cross-Lead: Security for auth/crypto, Research for unfamiliar libs, Content for user-facing copy
Input: Phase 3 plan
Output: code changes + `build-log.md`
Multi-model: no (single-model execution)
Operator gate: HARD before destructive commits (rebase --force, schema migrations, etc.)
In-phase checkpoint: skeptic's diff-atomicity-verify if diff > 10 files

### Phase 5: Review

Owner: Coding Lead
Specialists: code-reviewer (multi-model — Codex+Claude+Gemini, writer family excluded)
Input: Phase 4 code changes
Output: structured review findings
Multi-model: yes
Operator gate: SOFT (operator sees findings, can override)
Advance when: zero blockers in findings (or operator overrides specific blockers)

### Phase 6: Test / Verification

Owner: Coding Lead
Specialists: test-engineer (single-model, tool-grounded)
Input: Reviewed code
Output: `test-results.md`
Multi-model: no (tool-grounded execution; multi-model adds nothing)
Sub-streams: unit + property + e2e + visual-regression (if UI) + a11y (if UI) + load (if perf-sensitive) + cross-browser (if web)
Operator gate: SOFT
Advance when: all tests green or failures documented as pre-existing

### Phase 7: Validation

Owner: Coding Lead with Security cross-Lead if security touched
Specialists: skeptic (cross-cutting, multi-model), impact-validator (Security cross-cutting if relevant)
Input: Tested code
Output: `validation.md`, `release-risk.md`
Multi-model: yes (skeptic always)
Operator gate: SOFT

### Phase 8: Release / Handoff

Owner: Coding Lead
Specialists: technical-writer (Content cross-Lead)
Input: Validated code
Output: PR description, changelog, deployment notes, KG writeback
Multi-model: no
Operator gate: HARD (operator approves PR/deploy)
Pre-release: vibecoding-check fires (universal + project-extension)

## Cross-Lead routing rules

```
need: security_review_of_auth_change
  to_lead: security
  mailbox_path: shared/mailbox/coding-to-security/
  return_artifact: shared/mailbox/security-to-coding/RESP-<id>.md
  async: yes

need: research_unfamiliar_library  
  to_lead: research
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
  - phase_2_to_3: "operator approves design (1-page spec)"
  - phase_3_to_4: "operator approves implementation plan (for large refactors)"
  - phase_4_destructive: "operator approves before any rebase/migration/destructive command"
  - phase_5_blockers: "operator can override specific blockers"
  - phase_8_release: "operator approves PR / deploy"

soft_gates:
  - phase_1_intake: "operator can clarify scope"
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
