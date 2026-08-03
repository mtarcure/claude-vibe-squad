---
id: project/platform-release
mode: project
title: Platform / release (CI · IaC · release rails · reliability)
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change, public_release, delete]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** CI/CD pipelines, infrastructure-as-code, release rails, and production reliability work.
Merges DevOps and SRE ownership (they stay distinct: `devops-engineer` owns provisioning/delivery,
`site-reliability-engineer` owns reliability objectives + recovery).

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (release/reliability objectives) | `product-manager`, `site-reliability-engineer` | — | `requirements-elicitation` | — |
| **S2** Design (pipeline / IaC architecture) | `architect`, `devops-engineer`, `site-reliability-engineer` | `context7` | `dependency-cycle-audit`, `secret-rotation-discipline` | `credential_change` (secrets design) |
| **S3** Produce (CI / IaC / rails) | `devops-engineer` | `context7` | `rollback-test-coverage` | — |
| **S4** Verify | `test-engineer`, `site-reliability-engineer` | — | `rollback-test-coverage`, `representative-workload-design` | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (mandatory cross-family — high-safety infra; review tools MECHANICS ONLY — never replace the independent cross-family reviewer); `production_mutation`, `credential_change`, `delete` |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` | `secret-rotation-discipline` | deploy = `needs_tool:auth` profile — target selector: Vercel primary / Firebase fallback / Cloudflare edge / Codex Sites (deferred); `credential_change` for login; `public_release` + `production_mutation` per deploy; domain/DNS separately approved; stays `needs_tool` until an authenticated smoke + preview→rollback rehearsal produce evidence |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** The generic CI / IaC / release-rails path is live; the DEPLOY step is a `needs_tool` target-selector
profile (explicit operator choice per release, never auto-failover between providers): **Vercel**
, **Firebase**
, **Cloudflare** Workers/Pages
(OAuth-available/auth-pending — specialized edge), **Codex Sites** (session-live/empty-inventory — explicit
opt-in, all deploy URLs production). Record a provider-neutral release record before S6 (`deploy_target` /
`environment` / `source_commit` / `artifact_digest` / `account_project` / `cost_plan` / `rollback_target` /
`approvals`); no production deploy proceeds without S4 acceptance, S5 independent review, a tested rollback
target, and a fresh operator approval naming provider/project/environment. A provider auth failure must stop —
never auto-deploy to another provider. All production mutations, credential changes, and deletes are
operator-gated. (See `_state/audit-2026-07-17/deploy-rec/`.)
