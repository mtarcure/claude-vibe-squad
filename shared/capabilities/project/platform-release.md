---
id: project/platform-release
mode: project
title: Platform / release (CI · IaC · release rails · reliability)
capability_state: live
state_reason: CI, IaC, and release rails are code (workflows, Terraform, Dockerfiles, scripts) needing no catalog-absent tool; `plugin:github:github` (claude·lane-live) and `context7` support it. External cloud-provider connectors (Cloudflare/Firebase/Sentry) are catalog-absent — those specific integrations are `needs_tool`, out of the core live path.
state_evidence: registry rows — plugin:github:github = `claude·lane-live`, context7 = `claude·lane-live`, chrono-vault = `all·yes`; Cloudflare/Firebase/Sentry = `catalog-absent` (FINAL-PLAN Tier-2/3).
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change, public_release, delete]
cost_note: subscription for the github plugin + coordination; the IaC/CI build toolchain is local. No metered provider required; cloud-provider connectors are catalog-absent (not billed here).
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
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay (mandatory cross-family — high-safety infra); `production_mutation`, `credential_change`, `delete` |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | `secret-rotation-discipline` (stub) | `public_release`, `production_mutation` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Integrating a specific cloud provider (Cloudflare / Firebase / Sentry) is `needs_tool` until its
connector is cataloged (FINAL-PLAN Tier-2/3) — the generic CI/IaC/release-rails path is live. All
production mutations, credential changes, and deletes are operator-gated.
