# Capability Manifest: performance-optimizer

Status: draft, preserve before cleanup
Owner: coding namespace
Canonical current specialist: `departments/coding/specialists/performance-optimizer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-performance-optimizer/0.1.0/`

## Role Contract

`performance-optimizer` owns benchmarking, profiling, flamegraph triage, regression confirmation, thread-count sweeps, NUMA/cache performance diagnosis, and quantified optimization recommendations. It identifies bottlenecks and validates deltas; it does not own feature implementation.

## Preserved Current Behavior

- Baselines before profiling.
- Selects profiler by runtime.
- Reads flamegraphs and source context before recommending fixes.
- Records every benchmark and confirmed finding.
- Hands implementation to the owning engineer.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `hyperfine_bench`
- `py_spy_record`, `py_spy_top`
- `pprof_profile`
- `samply_record`, `samply_load`
- `perf_stat_linux`, `perf_top_linux`
- `chrome_trace_export`
- `bench_compare`

Old shared tools:

- `docker_run`, `docker_compose_up`
- `gh_api`
- `http_get`, `httpx_probe`
- `hwloc_info`, `hwloc_lstopo`

Preservation rule: wrappers may be consolidated, but the role must retain reliable benchmark, profile, compare, and topology-probe paths.

## Required Tools

- `hyperfine` or equivalent benchmark runner with JSON output.
- Runtime-specific profiler path for Python, Go, native/Rust, and browser/Node trace cases.
- Benchmark comparison path with regression flag.
- Hardware topology path for NUMA/thread decisions.

## Optional Tools

- Linux `perf`, graceful-degrade on macOS.
- Firefox Profiler/Samply integration.
- Chrome trace summarizer.

## MCPs

- `chrono-kg`: previous baseline recall and finding records.
- `chrono-catalog`: tool/skill discovery.
- `chrono-vault` / `chrono-obsidian`: benchmark artifact references.
- `sequential-thinking`: hypothesis-chain reasoning for ambiguous regressions.

## Skills

Current or old skills to keep represented:

- `flamegraph-triage-flow`
- `thread-sweet-spot-profiling`
- `cross-arch-compute-routing`
- `regression-bisect-flow`
- `representative-workload-design`
- `bitnet-inference-perf-profiling` / `1bit-inference-perf-profiling`
- `inference-throughput-sweep`
- `numa-locality-diagnosis`
- `web-perf-core-vitals`
- `chain-construct`
- `fp-check`
- `adversarial-review`
- `hwloc-info-pattern`
- `dcbt-prefetch-discipline`

## Adaptive Operating Mode

Recall prior baselines, run a representative baseline, stop if no measured issue exists, choose the profiler by runtime when a regression exists, inspect the widest self-time frame against source, validate before/after with comparable benchmarks, adversarially review methodology, then hand implementation to the owning role.

## Output Contract

Expected return shape:

- `baseline_ms`
- `optimized_ms` when available
- `speedup_ratio`
- `regression_flag`
- `flamegraph_hotspot`
- `recommendations`
- `kg_finding_id`
- `suggested_next_stage`

## KG And Memory Behavior

- Recall baselines before rerunning sweeps.
- Record benchmark command, warmups/runs, hardware context, JSON artifact path, and result.
- Record confirmed findings only with empirical evidence.

## Safety Boundaries

- No unverified performance claims.
- No feature implementation or broad refactor.
- No NUMA or prefetch recommendations without topology/profiling evidence.
- No active web scanner use; security tooling belongs to security namespace.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a profiling/regression task to coding namespace.
2. coding namespace dispatches `performance-optimizer`.
3. Specialist uses catalog and KG recall.
4. Specialist runs a harmless benchmark/tool probe or records a missing-tool blocker.
5. Outbox includes benchmark evidence or missing-tool disposition.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship manifests, prompts, skills, validator rules, and setup checks. Private benchmark data, customer traces, and local profiler artifacts stay local unless sanitized.

## Cleanup Disposition

Do not delete old `chrono-plugin-performance-optimizer` assets until the current role preserves or explicitly dispositions every required tool and skill.
