# Capability Manifest: systems-engineer

Status: draft, preserve before cleanup
Owner: coding namespace
Canonical current specialist: `departments/coding/specialists/systems-engineer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-systems-engineer/0.1.0/`

## Role Contract

`systems-engineer` owns low-level C/C++/Rust systems work, cross-architecture builds, toolchain bootstrap, binary inspection, SIMD porting, NUMA/cache investigations, and architecture-specific build failures. It does not own benchmarking campaigns, UI, smart contracts, impact scoring, or initial bounty triage.

## Preserved Current Behavior

- Uses validated toolchain/build files before changing flags.
- Applies topology and SIMD skills before tuning architecture-specific behavior.
- Hands benchmark campaigns to `performance-optimizer`.
- Hands CI build matrix implementation to `devops-engineer`.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `cmake_configure`, `cmake_build`
- `ninja_build`
- `cargo_build`, `cargo_test`, `cargo_clippy`, `cargo_fmt`
- `gdb_systems_attach`, `gdb_backtrace`
- `llvm_objdump`
- `nm_symbols`
- `objcopy`
- `readelf`

Old shared tools:

- `docker_run`, `docker_compose_up`
- `gh_api`
- `http_get`
- `hwloc_info`, `hwloc_lstopo`

Preservation rule: cleanup may simplify wrappers, but Vibe Squad must retain a reliable path for cross-arch builds, binary inspection, debugger triage, and topology-aware systems analysis.

## Required Tools

- CMake and Ninja command paths.
- Cargo build/test/fmt/clippy paths for Rust systems repos.
- GDB or LLDB path for native debugging.
- ELF/binary inspection path (`readelf`, `nm`, `objdump`, `objcopy`, or platform equivalent).
- Hardware topology path (`hwloc` preferred; graceful-degrade on unsupported hosts).

## Optional Tools

- Docker-based sysroot/build reproducibility.
- Distributed compile coordinator.
- Platform-specific DCBT/prefetch analysis tools.

## MCPs

- `chrono-kg`: prior build attempts, toolchain fixes, and findings.
- `chrono-catalog`: currently available tool/skill discovery.
- `chrono-vault` / `chrono-obsidian`: durable build notes and artifact paths.
- `sequential-thinking`: complex toolchain or architecture tradeoffs.

## Skills

Current or old skills to keep represented:

- `compiler-bootstrap-flow`
- `cross-arch-build-discipline`
- `hybrid-threading-tuning`
- `simd-porting-layer`
- `cross-arch-test-discipline`
- `simd-correctness-validation`
- `distributed-build-coordinator`
- `dcbt-prefetch-discipline`
- `hwloc-info-pattern`

## Adaptive Operating Mode

Probe the build target and environment, recall prior failures, validate toolchain files, run the smallest useful build/test command, inspect errors with binary/debug tools, then record a reproducible fix or blocker. NUMA, SIMD, and DCBT changes require topology/profiling evidence before code changes.

## Output Contract

Expected return shape:

- `build_result.status`
- `binary_path` when produced
- `arch`
- `toolchain_summary`
- `findings` with type, severity, description, and shell transcript
- `kg_finding_ids`
- `suggested_next_stage`

## KG And Memory Behavior

- Recall prior work before retrying a build.
- Record build attempts, exact flags, target arch, host arch, tool versions, and result.
- Record significant findings with reproducible commands.

## Safety Boundaries

- No speculative prefetch/SIMD changes.
- No benchmark conclusions; hand to `performance-optimizer`.
- No production CI mutation without `devops-engineer`.
- No destructive local cleanup of build artifacts unless scoped and approved.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a cross-arch/build task to coding namespace.
2. coding namespace dispatches `systems-engineer`.
3. Specialist uses catalog and KG recall.
4. Specialist runs a harmless build/tool probe or records a missing-tool blocker.
5. Outbox includes command transcript and next-stage recommendation.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship manifests, prompts, skills, and setup checks. Private local source checkouts, proprietary build logs, and machine-specific sysroots stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-systems-engineer` assets until the current specialist, catalog, and live proof cover each required tool or explicitly mark it optional/deprecated.
