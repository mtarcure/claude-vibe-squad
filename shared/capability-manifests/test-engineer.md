# Capability Manifest: Test Engineer

Status: draft
Owner: coding namespace
Canonical specialist: `departments/coding/specialists/test-engineer.md`
Old plugin sources:

- `~/.claude/plugins/cache/claude-chrono/chrono-plugin-qa-tester/0.1.0/`
- `~/.claude/plugins/cache/claude-chrono/chrono-plugin-e2e-runner/0.1.0/`

## Role Contract

Test Engineer owns the full product testing surface for Project Mode: unit tests, integration tests, property-based tests, mutation campaigns, coverage gates, API contract tests, E2E browser tests, visual regression, cross-browser checks, flake triage, and test artifacts. Current Vibe Squad intentionally merged the old `qa-tester` and `e2e-runner` roles into one specialist. This remains the default unless live dispatch testing proves a separate E2E sub-specialist is needed.

## Preserved From Current Specialist

- Merged unit/property/E2E/flake-triage scope.
- Codex-oriented implementation/testing posture.
- No production-code fixes as default behavior.
- Escalation back to implementers when tests expose production defects.
- Operator gate before skipping, quarantining, or marking failures expected.
- Skills: `property-based-fuzz-harness`, `chrono-property-based-strategy`, `chrono-mutation-campaign`, `test-shrinkage-loop`, `playwright-page-object-model`, `webapp-testing-local`, `e2e-authoring-flow`, `flaky-e2e-hunt`, `staged-integrity-gate`.

## Preserve From Old QA Plugin

### Required Tool Surface

- `pytest_cov_run`
- `pytest_cov`
- `hypothesis_stats`
- `mutmut_run`
- `stryker_run`
- `vitest_cov_run`
- `schemathesis_gen`
- `pact_broker_verify`
- `cargo_tarpaulin`
- `c8_coverage`

### Skills

- `property-based-fuzz-harness`
- `chrono-property-based-strategy`
- `chrono-mutation-campaign`
- `test-shrinkage-loop`
- `staged-integrity-gate`

## Preserve From Old E2E Plugin

### Required Tool Surface

- `playwright_test`
- `playwright_codegen`
- `storybook_test_runner`
- `axe_playwright`
- `cypress_test`
- `ffmpeg_trim`
- `trace_replay`
- `visual_diff`
- `test_shard`
- `webkit_run`
- `firefox_run`

### Skills

- `flaky-e2e-hunt`
- `e2e-video-capture`
- `e2e-authoring-flow`
- `webapp-testing-local`
- `playwright-page-object-model`
- `cross-browser-validation`
- `flakiness-triage`
- `local-webapp-test`
- `bounty-evidence-capture` when operating inside Bounty Mode

## Shared Tool Surface

- `docker_run`
- `docker_compose_up`
- `gh_api`
- `http_get`
- `httpx_probe`
- `npm_install`
- `pnpm_install`
- `sequential-thinking`
- `chrono-kg`
- `chrono-catalog`
- `chrono-vault`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> identify test layer -> baseline run -> deepen with appropriate strategy -> capture artifacts -> classify failures -> record -> handoff
```

Layer-specific behavior:

- Unit/integration: run existing test command first; preserve local conventions before adding frameworks.
- Property-based: identify invariants, seed broad strategies, shrink counterexamples before reporting.
- Mutation: run only after baseline tests are stable; surviving mutants require targeted test additions.
- Coverage: use coverage to find untested behavior, not to chase line count.
- API contracts: prefer OpenAPI/Schemathesis/Pact when contract surfaces exist.
- E2E: run browser tests with trace/screenshot/video evidence when useful.
- Visual: check whether baseline is stale before calling a regression.
- Cross-browser: treat Chromium/WebKit/Firefox divergence as compatibility evidence.
- Flake: use repeat evidence; never rerun until pass and call it green.

## Output Contract

Return a structured report with:

- `ok`
- `test_layer`
- `commands_run`
- `passed`
- `failed`
- `flaky`
- `coverage_pct`
- `mutation_score`
- `visual_regressions`
- `artifacts`
- `failures`
- `kg_attempt_id`
- `suggested_next_stage`
- missing-capability list when tools are unavailable

For E2E work, include artifact paths for traces, videos, screenshots, and visual diffs when produced.

## KG And Memory Behavior

- Recall prior test campaigns before work.
- Record attempt before campaign execution.
- Record findings only after failures are classified and evidence exists.
- Durable memory is appropriate for recurring flakes, project test conventions, non-obvious harness decisions, or accepted baselines.

## Safety Boundaries

- No production-code fixes unless explicitly assigned.
- No hiding, skipping, or quarantining failing tests without operator approval.
- No exploit payloads or active security scanning.
- No CVSS/scoring.
- No unscoped browser actions in Bounty Mode.
- No new heavyweight test framework without explaining why existing project conventions are insufficient.

## Live Dispatch Proof

Minimum production proof:

1. Chrono dispatches a small project fixture to coding namespace.
2. coding namespace selects `test-engineer`.
3. Specialist runs at least one intended test capability:
   - unit/coverage/property/mutation command, or
   - Playwright/E2E/visual command, or
   - structured missing-tool report.
4. Response includes command output summary and evidence artifacts where applicable.
5. Active registry closes.
6. Chrono summarizes next stage: implementer, code-reviewer, refactor-cleaner, performance-optimizer, or suite green.

## E2E Merge Decision

Current decision: keep E2E inside `test-engineer`.

Reason:

- Current specialist already states it merged `qa-tester` and `e2e-runner`.
- One owner reduces routing confusion for Project Mode validation.
- The manifest preserves the old E2E tool/skill surface explicitly.

Revisit if:

- live dispatch tests show E2E work is too large for one specialist context
- browser artifact handling needs a dedicated persistent runner
- bounty evidence capture requires a separate scoped/safe E2E specialist

## Public/Private Disposition

- Public: role contract, test strategy, fixture tests, generic artifact schema.
- Private/local: client test outputs, browser traces from authenticated apps, videos/screenshots containing private data, bounty evidence, CI tokens.

## Cleanup Disposition

Do not delete old `qa-tester` or `e2e-runner` plugin sources until:

- this manifest is complete
- current `test-engineer` specialist is updated from it
- live dispatch proof covers both non-browser and browser paths, or one path has a documented structured missing-tool result
- private browser artifacts and test outputs are ignored/quarantined
