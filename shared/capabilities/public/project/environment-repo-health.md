---
id: project/environment-repo-health
mode: project
title: Environment / repo health (hygiene · cleanup · upgrades · refactors)
overlays: [review, memory]
gates: [production_mutation, credential_change, public_release, delete, cleanup]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** repo and environment hygiene — dependency upgrades, dead-code/artifact cleanup, refactors,
and health audits. Maintenance lifecycle: planned inventory → risk grouping → approval → batch execution →
regression/changelog. Any live-system mutation, delete, cleanup, credential change, or public release is
operator-gated.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall); inventory precheck |
| **S1** Frame (audit scope + cost) | `product-manager`, `mac-ops`, `finance-analyst` | — | `scope-decomposition` | — |
| **S2** Design (risk grouping + plan) | `architect`, `refactor-cleaner`, `agentops` | — | `refactor-scope-bounding`, `dependency-cycle-audit` | — |
| **S3** Produce (upgrade / cleanup / refactor) | `refactor-cleaner`, `software-supply-chain-engineer`, `mac-ops` | `plugin:github:github`, `osv-scanner`, `gitleaks`, `trufflehog`, `trivy`, `semgrep` | `refactor-scope-bounding`, `known-advisory-backport-check` | `credential_change`; `cleanup`; `delete` |
| **S4** Verify (regression + changelog) | `test-engineer`, `skeptic` | — | `rollback-test-coverage`, `regression-bisect-flow` | — |
| **S5** Review/Gate (approval) | `code-reviewer`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); `production_mutation`, `delete`, `cleanup`, `credential_change`, `public_release` |
| **S6** Ship/Deliver (batch execute + changelog) | `mac-ops`, `agentops`, `technical-writer` | `plugin:github:github` | — | `production_mutation` (live-system mutation); `public_release` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** Batch execution and changelog close the maintenance loop. Every destructive or mutating action is
operator-gated (Hard Rule 6): `delete`/`cleanup` for artifact/dead-code removal, `credential_change` for
secret/token rotation, `production_mutation` for any change to a live (non-release) system, `public_release`
for anything shipped publicly. `finance-analyst` weighs subscription-cost impact of upgrades. Incident/repair
of a suspected compromise is `incident` mode, not here.
