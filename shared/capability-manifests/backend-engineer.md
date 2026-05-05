# Capability Manifest: Backend Engineer

Status: draft
Owner: coding namespace
Canonical specialist: `departments/coding/specialists/backend-engineer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-backend-engineer/0.1.0/`

## Role Contract

Backend Engineer owns server-side implementation: API design, Python/Rust/Go services, database migrations, async pipelines, HTTP clients, service tests, backend linting, and workflow orchestration. It implements against an agreed contract. Architecture belongs to `architect`, infrastructure to `devops-engineer`, frontend UI to `frontend-engineer`, and post-ship hot-path profiling to `performance-optimizer`.

## Preserved From Current Specialist

- API, database, async pipeline, and server-side business logic scope.
- Codex-oriented implementation posture.
- Test discipline and clarification behavior.
- Fanout to `test-engineer`, `code-reviewer`, and `architect`.
- Bundled scraping/data-extraction behavior for backend-shaped scraping work.
- Skills: `fastapi-service-boot`, `axum-tokio-pattern`, `async-scraper-pipeline`, `mcp-server-cdp-pattern`, `n8n-workflow-orchestration`.

## Preserve From Old Plugin

### Required Tool Surface

- Python: `uv_install`, `uv_run`, `pytest_run`, `ruff_lint`.
- Rust: `cargo_run`, `cargo_check`.
- Go: `go_build`, `go_test`.
- Node: `node_run`.
- API/service: `http_api_probe`, `fastapi_dev`, `migration_run`, `logs_tail`.

### Shared Tool Surface

- `httpx_probe`
- `docker_run`
- `docker_compose_up`
- `gh_api`
- `http_get`
- `npm_install`
- `pnpm_install`
- `chrono-kg`
- `chrono-catalog`
- `chrono-vault`
- `sequential-thinking`

### Skills

- `async-scraper-pipeline`
- `axum-tokio-pattern`
- `fastapi-service-boot`
- `mcp-server-cdp-pattern`
- `n8n-workflow-orchestration`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> read contract/spec -> inspect existing conventions -> implement -> test -> lint/typecheck -> record -> handoff
```

Required behavior:

- Compare prior work from KG before re-implementing a service.
- Use the project’s existing package manager/test runner before adding new tooling.
- Apply `fastapi-service-boot` for FastAPI, `axum-tokio-pattern` for Rust web services, and `async-scraper-pipeline` for async ingestion.
- Fix baseline test/type errors before expanding scope.
- Add `/healthz` by default for newly authored services unless the project has an established alternative.
- Degrade gracefully when migration tooling or n8n runtime is absent: document SQL/workflow JSON and record deferred state.
- For MCP server work, apply `mcp-server-cdp-pattern` and require documented structured return shapes.

## Output Contract

Return a structured report with:

- `ok`
- `service_path`
- `language`
- `commands_run`
- `tests_passed`
- `lint_clean`
- `typecheck_clean`
- `migration_applied`
- `healthz_endpoint`
- `kg_finding_id`
- `suggested_next_stage`
- missing-capability list when tools are unavailable

## KG And Memory Behavior

- Recall prior service/module attempts before work.
- Record attempt before implementation.
- Record durable findings only after tests/lint/typecheck are clean or when a blocker/deferred migration is significant.
- Durable memory is appropriate for API contracts, migration decisions, async retry/rate-limit policy, and service-specific operational constraints.

## Safety Boundaries

- No infrastructure decisions or Terraform/Kubernetes ownership.
- No frontend/UI ownership.
- No production database/destructive migrations without operator approval.
- No active security scanning.
- No out-of-scope external API calls without authorization frame.
- No hardcoded secrets or credentials.
- No new framework unless existing stack cannot reasonably satisfy the task.

## Live Dispatch Proof

Minimum production proof:

1. Chrono dispatches a small backend fixture to coding namespace.
2. coding namespace selects `backend-engineer`.
3. Specialist runs at least one intended backend capability:
   - `pytest`, `ruff`, `uv`, `cargo check`, `go test`, API probe, or structured missing-tool output.
4. Response includes command summary, changed files or blocked reason, and suggested next stage.
5. Active registry closes.
6. Chrono summarizes whether `test-engineer`, `code-reviewer`, `devops-engineer`, or `performance-optimizer` should run next.

## Public/Private Disposition

- Public: role contract, tool expectations, service fixture behavior, output schema.
- Private/local: client service code, production DB URLs, API keys, logs containing private data, n8n credentials, deployment secrets.

## Cleanup Disposition

Do not delete old backend plugin source until:

- this manifest is complete
- current `backend-engineer` specialist is updated from it
- live backend fixture dispatch proof passes
- bundled scraping responsibilities are reconciled with `scraping-engineer`
