---
id: project/learning-study
mode: project
title: Learning + study (study plans · drills · learning paths)
overlays: [review, memory]
gates: []
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** build a study plan, drill set, or learning path for a topic or skill. Judgment-driven; the
research tools are an optional aid for sourcing material, not a core dependency.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (goals + level) | `learning-coach` | — | `scope-decomposition` | — |
| **S3** Produce (plan + drills + path) | `learning-coach`, `summarizer` | `chrono-vault` | `scope-decomposition` | — |
| **S4** Verify (coverage + difficulty fit) | `learning-coach`, `skeptic` | — | — | review overlay if the plan is high-stakes (certification/exam) |
| **S6** Ship/Deliver (study plan) | `learning-coach`, `technical-writer` | `chrono-obsidian` | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record; progress tracking) |

**Notes.** Steps collapse (no S2/S5) — this is light, judgment-driven work. The core needs no catalog-absent
tool; `perplexity_search_web`/`arxiv_search` are optional live aids for sourcing reference material, and
`Google Search grounding` is an optional subscription-tier aid for verifying facts in
sourced study material (metered tools are budget-guarded). No repeated-eval workload applies here, so DeepSeek
caching is not wired. Durable progress notes are recorded to the vault at S7.
