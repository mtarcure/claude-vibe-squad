---
id: project/systems-low-level
mode: project
title: Systems / low-level (cross-arch · SIMD · runtime)
capability_state: needs_tool
state_reason: The load-bearing cross-arch build/emulation/profiling toolchain (cross-compilers + sysroots, `qemu` emulation, `perf`/`valgrind`, a SIMD scalar-vs-vector correctness harness) is NOT registry-verified — no host compiler / cross-compiler / emulator / profiler row exists. Host-native compilation via Bash is possible in principle but is not a catalogued tool, and the cross-arch + SIMD *verification* this capability is about is unverified → `needs_tool` until that toolchain is cataloged/probed. `chrono-vault`/`context7` are support tools, not the build/verify path.
state_evidence: registry has no gcc/clang/cross-compiler/qemu/perf/valgrind/objdump row (checked 2026-07-17); the only live rows here — chrono-vault = `all·yes`, context7 = `claude·lane-live` — are memory/docs support, not the load-bearing build/verify toolchain. No registry-verified build or verify tool sits on this card's path.
overlays: [review, memory]
gates: [production_mutation]
cost_note: unknown — the load-bearing cross-arch/SIMD build+verify toolchain is not cataloged (`needs_tool`), so its cost tier is unresolved; chrono MCPs are subscription. No metered provider is involved.
---

**When to use:** cross-architecture builds, SIMD/vectorization, runtime behaviour, and other low-level
systems work. `systems-engineer` + `performance-optimizer` own correctness and hot-path performance.
**Currently `needs_tool`** — the concrete build/emulation/profiling toolchain is not cataloged (see Notes);
admit only once the probe-target tools below are registry-verified.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (target / arch spec) | `product-manager`, `systems-engineer` | — | `requirements-elicitation` (stub), `scope-decomposition` (stub) | — |
| **S2** Design (arch / ABI / SIMD plan) | `architect`, `systems-engineer` | `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub) | — |
| **S3** Produce (implement) | `systems-engineer`, `performance-optimizer` | `cross-compiler-toolchain` (unknown · catalog-absent · unknown), `qemu` (unknown · catalog-absent · unknown) | `cross-arch-test-discipline` (stub) | — |
| **S4** Verify (cross-arch + SIMD correctness) | `test-engineer`, `performance-optimizer` | `perf` (unknown · catalog-absent · unknown), `valgrind` (unknown · catalog-absent · unknown) | `simd-correctness-validation` (stub), `cross-arch-test-discipline` (stub), `behavior-preservation-test` (stub) | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | — | — | review overlay |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | `regression-bisect-flow` (stub) | `production_mutation` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** This capability is `needs_tool`: the concrete cross-arch build/emulation/profiling toolchain —
cross-compilers + sysroots, `qemu` emulation, `perf`/`valgrind`, and a SIMD scalar-vs-vector correctness
harness — must be cataloged/probed and registry-verified before it can go live. Those are named as the
`catalog-absent` probe targets at S3/S4 (they are not claimed live). Host-native (same-arch) build may be
possible in principle but is not a registry-verified tool, so it does not raise the derived state on its own.
`performance-optimizer` owns hot-path validation; SIMD correctness is validated against a scalar reference
(`simd-correctness-validation`) once the toolchain is available.
