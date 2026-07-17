---
id: project/data-pipeline
mode: project
title: Data pipeline (ETL / analytics / ML-wiring)
capability_state: live
state_reason: Pipeline WIRING (extraction, ETL, analytics plumbing, evaluation) is code and needs no catalog-absent tool; the cited tools are all live. ⚠ Roster gap — no ML-training / data-science specialist exists, so model *training* is out of scope (routes as needs_specialist); this capability covers pipeline wiring + evaluation, not training.
state_evidence: registry rows — context7 = `claude·lane-live`, chrono-vault = `all·yes`; no catalog-absent core tool. Roster has no ML-training/data-science role (pack-design §1A ⚠).
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change, delete]
cost_note: subscription only — coordination tools are lane-native. No metered provider is required.
---

**When to use:** build an ETL / analytics / data-plumbing pipeline, or wire data into an ML/serving system.
**Not** model training (no specialist for it — returns `needs_specialist`).

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (data contract) | `product-manager`, `data-extraction-engineer` | — | `requirements-elicitation` (stub), `schema-inference` (stub) | privacy overlay if PII |
| **S2** Design (pipeline architecture) | `architect`, `backend-engineer`, `database-engineer` | `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub) | — |
| **S3** Produce (build ETL / wiring) | `data-extraction-engineer`, `ai-engineer`, `backend-engineer` | `context7` (claude · lane-live · subscription) | `data-cleaning-pipeline` (stub), `structured-data-authoring` (authored) | — |
| **S4** Verify | `test-engineer`, `performance-optimizer` | — | `eval-harness-pattern` (stub), `representative-workload-design` (stub) | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | — | — | review overlay; privacy if PII |
| **S6** Ship/Deliver | `devops-engineer` | `plugin:github:github` (claude · lane-live · subscription) | `rollback-test-coverage` (stub) | `production_mutation`, `credential_change`, `delete` (destructive overwrite / retention cutoff) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** ⚠ **No ML-training / data-science specialist exists** — this capability covers pipeline wiring +
evaluation only; model-training work returns `needs_specialist` (do not publish "ML training" under this
label). PII in the pipeline fires the privacy overlay (`privacy-steward`). Any destructive path — truncate/
overwrite of an existing dataset, or a retention-cutoff purge — is operator-gated (`delete`); non-destructive
incremental/append pipelines do not fire it.
