---
id: project/data-pipeline
mode: project
title: Data pipeline (ETL / analytics / ML-wiring)
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

**When to use:** build an ETL / analytics / data-plumbing pipeline, or wire data into an ML/serving system.
**Not** model training (no specialist for it — returns `needs_specialist`).

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (data contract) | `product-manager`, `data-extraction-engineer` | — | `requirements-elicitation`, `schema-inference` | privacy overlay if PII |
| **S2** Design (pipeline architecture) | `architect`, `backend-engineer`, `database-engineer` | `context7` | `dependency-cycle-audit` | — |
| **S3** Produce (build ETL / wiring) | `data-extraction-engineer`, `ai-engineer`, `backend-engineer` | `context7` | `data-cleaning-pipeline`, `structured-data-authoring` | — |
| **S4** Verify | `test-engineer`, `performance-optimizer` | — | `eval-harness-pattern`, `representative-workload-design` | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); privacy if PII |
| **S6** Ship/Deliver | `devops-engineer` | `plugin:github:github` | `rollback-test-coverage` | `production_mutation`, `credential_change`, `delete` (destructive overwrite / retention cutoff) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** ⚠ **No ML-training / data-science specialist exists** — this capability covers pipeline wiring +
evaluation only; model-training work returns `needs_specialist` (do not publish "ML training" under this
label). PII in the pipeline fires the privacy overlay (`privacy-steward`). Any destructive path — truncate/
overwrite of an existing dataset, or a retention-cutoff purge — is operator-gated (`delete`); non-destructive
incremental/append pipelines do not fire it.
