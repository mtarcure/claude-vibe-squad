---
id: project/backend-service-api
mode: project
title: Backend service / API (server, persistence, data flows)
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change, delete]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** build a headless server / API / data-flow system — protocol contract, persistence,
concurrency, observability. Any browser UI belongs to `project/web-app`; the two share a `backend-engineer`
+ `database-engineer` "service core".

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall); capability_state precheck |
| **S1** Frame (requirements) | `product-manager`, `architect` | — | `requirements-elicitation`, `scope-decomposition` | — |
| **S2** Design (API + schema contract) | `architect`, `backend-engineer`, `database-engineer` | `context7` | `dependency-cycle-audit` | privacy overlay if PII |
| **S3** Produce (build) | `backend-engineer`, `database-engineer` | `context7` | `structured-data-authoring` | — |
| **S4** Verify | `test-engineer`, `performance-optimizer` | — | `behavior-preservation-test`, `representative-workload-design` | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review`, `claude --from-pr` | — | review overlay (mandatory cross-family — persistence/high-safety; review tools MECHANICS ONLY — never replace the independent cross-family reviewer); +privacy if PII |
| **S6** Ship/Deliver | `devops-engineer`, `site-reliability-engineer`, `technical-writer` | `plugin:github:github` | `rollback-test-coverage` | `production_mutation` (deploy), `credential_change`, `delete` (migration) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** Acceptance = API/protocol contract, migration correctness, concurrency, observability, and
rollback/recovery (database-engineer + site-reliability-engineer own the high-safety persistence and
production contract). Frontend/UI, responsive behaviour, and visual review are `project/web-app`, not here. `systems-engineer`
joins only for an explicit low-level / performance-critical subcase — not the generic service build.
