---
id: maintenance/environment-repo-health
mode: maintenance
title: Environment / repo health (hygiene · cleanup · upgrades · refactors)
capability_state: live
state_reason: Repo/env hygiene, dependency upgrades, cleanup, and refactors run local shell + `plugin:github:github` (claude·lane-live) + the free SCA CLIs (`osv-scanner`/`gitleaks`/`trivy` `local·yes·—`); no catalog-absent tool sits on the path. Mutating a live system, deleting, cleanup, credential changes, and public release are operator-gated (Hard Rule 6).
state_evidence: registry rows — plugin:github:github = `claude·lane-live·subscription`; osv-scanner/gitleaks/trivy/trufflehog/semgrep = `local·yes·—`; chrono-vault = `all·yes·subscription`. No catalog-absent tool on the path.
overlays: [review, memory]
gates: [production_mutation, credential_change, public_release, delete, cleanup]
cost_note: subscription lane-native (github plugin + chrono-vault); the SCA CLIs and the shell repo/env toolchain are free-local (cost `—`). No metered provider is required.
---

**When to use:** repo and environment hygiene — dependency upgrades, dead-code/artifact cleanup, refactors,
and health audits. Maintenance lifecycle: planned inventory → risk grouping → approval → batch execution →
regression/changelog. Any live-system mutation, delete, cleanup, credential change, or public release is
operator-gated.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); inventory precheck |
| **S1** Frame (audit scope + cost) | `product-manager`, `mac-ops`, `finance-analyst` | — | `scope-decomposition` (stub) | — |
| **S2** Design (risk grouping + plan) | `architect`, `refactor-cleaner`, `agentops` | — | `refactor-scope-bounding` (stub), `dependency-cycle-audit` (stub) | — |
| **S3** Produce (upgrade / cleanup / refactor) | `refactor-cleaner`, `software-supply-chain-engineer`, `mac-ops` | `plugin:github:github` (claude · lane-live · subscription), `osv-scanner` (local · yes · —), `gitleaks` (local · yes · —) | `refactor-scope-bounding` (stub), `known-advisory-backport-check` (untyped) | `credential_change`; `cleanup`; `delete` |
| **S4** Verify (regression + changelog) | `test-engineer`, `skeptic` | — | `rollback-test-coverage` (stub), `regression-bisect-flow` (stub) | — |
| **S5** Review/Gate (approval) | `code-reviewer`, `cross-family-reviewer`, `operator` | — | — | review overlay; `production_mutation`, `delete`, `cleanup`, `credential_change`, `public_release` |
| **S6** Ship/Deliver (batch execute + changelog) | `mac-ops`, `agentops`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | — | `production_mutation` (live-system mutation); `public_release` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Batch execution and changelog close the maintenance loop. Every destructive or mutating action is
operator-gated (Hard Rule 6): `delete`/`cleanup` for artifact/dead-code removal, `credential_change` for
secret/token rotation, `production_mutation` for any change to a live (non-release) system, `public_release`
for anything shipped publicly. `finance-analyst` weighs subscription-cost impact of upgrades. Incident/repair
of a suspected compromise is `incident` mode, not here.
