---
id: project/systems-low-level
mode: project
title: Systems / low-level (cross-arch · SIMD · runtime)
overlays: [review, memory]
gates: [production_mutation]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

## Availability in a fresh clone

A zero-key checkout gets this protocol and its validation metadata as documentation; automated dispatch is `needs_tool`. To make it runnable, install and authenticate the selected model CLI, configure every MCP declared by the dispatched specialists, bind the private vault (`CHRONO_VAULT_ROOT`; Kimi also requires its exact vault context), install any required host-local binaries, and provide approved credentials plus a bounded budget for any metered provider named below. After setup, re-run the production role planner and validators on that host; availability remains subject to the narrower gaps and operator gates documented in this card.

**When to use:** cross-architecture builds, SIMD/vectorization, runtime behaviour, and other low-level
systems work. `systems-engineer` + `performance-optimizer` own correctness and hot-path performance.
**Currently `needs_tool`** — the concrete build/emulation/profiling toolchain is not cataloged (see Notes);
admit only once the probe-target tools below are registry-verified.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (target / arch spec) | `product-manager`, `systems-engineer` | — | `requirements-elicitation`, `scope-decomposition` | — |
| **S2** Design (arch / ABI / SIMD plan) | `architect`, `systems-engineer` | `context7` | `dependency-cycle-audit` | — |
| **S3** Produce (implement) | `systems-engineer`, `performance-optimizer` | `cross-compiler-toolchain`, `qemu`, `codex --sandbox`, `claude --worktree` | `cross-arch-test-discipline` | — |
| **S4** Verify (cross-arch + SIMD correctness) | `test-engineer`, `performance-optimizer` | `perf`, `valgrind` | `simd-correctness-validation`, `cross-arch-test-discipline`, `behavior-preservation-test` | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer) |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` | `regression-bisect-flow` | `production_mutation` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** This capability is `needs_tool`: the concrete cross-arch build/emulation/profiling toolchain —
cross-compilers + sysroots, `qemu` emulation, `perf`/`valgrind`, and a SIMD scalar-vs-vector correctness
harness — must be cataloged/probed and registry-verified before it can go live. Those are named as the
`catalog-absent` probe targets at S3/S4 (they are not claimed live). Host-native (same-arch) build may be
possible in principle but is not a registry-verified tool, so it does not raise the derived state on its own.
`performance-optimizer` owns hot-path validation; SIMD correctness is validated against a scalar reference
(`simd-correctness-validation`) once the toolchain is available.
