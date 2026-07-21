---
id: project/platform-release
mode: project
title: Platform / release (CI · IaC · release rails · reliability)
capability_state: live
state_reason: CI, IaC, and release rails are code (workflows, Terraform, Dockerfiles, scripts) needing no catalog-absent tool; `plugin:github:github` (claude·lane-live) and `context7` support it. External deploy/cloud connectors are `needs_tool` target profiles (Vercel `local·partial`, Firebase `claude·partial` connected/login-gated, Cloudflare/Sentry OAuth-available/catalog-absent) — out of the core live path.
state_evidence: registry rows — plugin:github:github = `claude·lane-live`, context7 = `claude·lane-live`, chrono-vault = `all·yes`; Vercel = `local·partial·subscription`, Firebase = `claude·partial·subscription` (MCP connected/login-gated); Cloudflare/Sentry connectors = `catalog-absent`/OAuth-available (→ deploy target profiles are `needs_tool`, FINAL-PLAN Tier-2/3).
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change, public_release, delete]
cost_note: subscription for the github plugin + coordination; the IaC/CI build toolchain is local. No metered provider required. Deploy providers are not billed here: Vercel/Firebase are `partial·subscription` (account-plan confirmed at deploy time), and the Cloudflare/Sentry connectors are `catalog-absent`/OAuth-available.
---

**When to use:** CI/CD pipelines, infrastructure-as-code, release rails, and production reliability work.
Merges DevOps and SRE ownership (they stay distinct: `devops-engineer` owns provisioning/delivery,
`site-reliability-engineer` owns reliability objectives + recovery).

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (release/reliability objectives) | `product-manager`, `site-reliability-engineer` | — | `requirements-elicitation` (stub) | — |
| **S2** Design (pipeline / IaC architecture) | `architect`, `devops-engineer`, `site-reliability-engineer` | `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub), `secret-rotation-discipline` (stub) | `credential_change` (secrets design) |
| **S3** Produce (CI / IaC / rails) | `devops-engineer` | `context7` (claude · lane-live · subscription) | `rollback-test-coverage` (stub) | — |
| **S4** Verify | `test-engineer`, `site-reliability-engineer` | — | `rollback-test-coverage` (stub), `representative-workload-design` (stub) | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (mandatory cross-family — high-safety infra; review tools MECHANICS ONLY — never replace the independent cross-family reviewer); `production_mutation`, `credential_change`, `delete` |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | `secret-rotation-discipline` (stub) | deploy = `needs_tool:auth` profile — target selector: Vercel primary (`local·partial·subscription`) / Firebase fallback (`claude·partial·subscription`, connected/login-gated) / Cloudflare edge / Codex Sites (deferred); `credential_change` for login; `public_release` + `production_mutation` per deploy; domain/DNS separately approved; stays `needs_tool` until an authenticated smoke + preview→rollback rehearsal produce evidence |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** The generic CI / IaC / release-rails path is live; the DEPLOY step is a `needs_tool` target-selector
profile (explicit operator choice per release, never auto-failover between providers): **Vercel**
(`local·partial·subscription`, installed/auth-pending — default web release target), **Firebase**
(`claude·partial·subscription`, MCP connected/login-gated — explicit fallback), **Cloudflare** Workers/Pages
(OAuth-available/auth-pending — specialized edge), **Codex Sites** (session-live/empty-inventory — explicit
opt-in, all deploy URLs production). Record a provider-neutral release record before S6 (`deploy_target` /
`environment` / `source_commit` / `artifact_digest` / `account_project` / `cost_plan` / `rollback_target` /
`approvals`); no production deploy proceeds without S4 acceptance, S5 independent review, a tested rollback
target, and a fresh operator approval naming provider/project/environment. A provider auth failure must stop —
never auto-deploy to another provider. All production mutations, credential changes, and deletes are
operator-gated. (See `_state/audit-2026-07-17/deploy-rec/`.)
