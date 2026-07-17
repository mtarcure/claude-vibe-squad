---
id: project/backend-service-api
mode: project
title: Backend service / API (server, persistence, data flows)
capability_state: live
state_reason: The core is server/API/persistence code implementation, which needs no catalog-absent or gated tool; the cited coordination tools are all live (`context7`/`plugin:github:github` lane-live on claude, `chrono-vault` yes on all lanes). Frontend/UI is out of scope (→ project/web-app).
state_evidence: registry rows — context7 + plugin:github:github = `claude·lane-live`, chrono-vault = `all·yes`; no catalog-absent tool sits on the build path. High-safety persistence handled by database-engineer / site-reliability-engineer (roster).
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change, delete]
cost_note: subscription only — coordination tools are lane-native (context7, github plugin, chrono-vault). No metered provider is required.
---

**When to use:** build a headless server / API / data-flow system — protocol contract, persistence,
concurrency, observability. Any browser UI belongs to `project/web-app`; the two share a `backend-engineer`
+ `database-engineer` "service core".

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); capability_state precheck |
| **S1** Frame (requirements) | `product-manager`, `architect` | — | `requirements-elicitation` (stub), `scope-decomposition` (stub) | — |
| **S2** Design (API + schema contract) | `architect`, `backend-engineer`, `database-engineer` | `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub) | privacy overlay if PII |
| **S3** Produce (build) | `backend-engineer`, `database-engineer` | `context7` (claude · lane-live · subscription) | `structured-data-authoring` (authored) | — |
| **S4** Verify | `test-engineer`, `performance-optimizer` | — | `behavior-preservation-test` (stub), `representative-workload-design` (stub) | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (mandatory cross-family — persistence/high-safety; review tools MECHANICS ONLY — never replace the independent cross-family reviewer); +privacy if PII |
| **S6** Ship/Deliver | `devops-engineer`, `site-reliability-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | `rollback-test-coverage` (stub) | `production_mutation` (deploy), `credential_change`, `delete` (migration) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Acceptance = API/protocol contract, migration correctness, concurrency, observability, and
rollback/recovery (database-engineer + site-reliability-engineer own the high-safety persistence and
production contract). Frontend/UI, responsive behaviour, and visual review are `project/web-app`, not here. `systems-engineer`
joins only for an explicit low-level / performance-critical subcase — not the generic service build.
