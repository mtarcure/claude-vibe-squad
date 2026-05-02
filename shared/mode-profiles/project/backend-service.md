---
name: backend-service
extends: project
status: active
---

# Project Profile: Backend Service

Python / Rust / Go / Node service deployed via Docker, runs as long-lived process. APIs, queues, workers.

## Auto-detection signals

- `Dockerfile` + non-frontend codebase
- `requirements.txt` / `Cargo.toml` / `go.mod` / `package.json` without frontend deps
- File patterns: `app/`, `src/`, `cmd/`, no `public/` or `pages/`

## Phase customizations

### Phase 1 Intake
- Test command varies: `pytest`, `cargo test`, `go test`, `npm test`
- Build: `docker build`
- Deploy target: Cloud Run / fly.io / Railway / AWS / self-hosted Docker

### Phase 2 Design
- API design (REST / GraphQL / gRPC) — needs architect
- Database schema — backend-engineer
- Queue / async pipeline architecture if relevant

### Phase 4 Build
- backend-engineer (primary)
- devops-engineer (Dockerfile, deploy config)
- ai-engineer (if LLM integration)
- systems-engineer (if perf-critical, low-level work)

### Phase 6 Test
- Unit: pytest / cargo test / go test
- Integration: against real or mocked dependencies (operator preference)
- Load testing: k6 / locust (if perf-critical)
- API contract testing if multi-service

### Phase 8 Release
- Docker image push to registry
- Deploy via deploy command per target (gcloud run deploy, flyctl deploy, etc.)
- Smoke test endpoint
- Migration applied if schema changed (separate gate per memory)

## Specialists most active

- backend-engineer
- devops-engineer
- test-engineer
- code-reviewer (multi-model)
- security-analyst (Security cross-Lead) for auth / data-flow review

## Backend-specific concerns

- Database migrations (schema changes need explicit operator approval)
- Secret management (env vars, secret stores, never in code)
- Observability (logging, tracing, metrics from day 1)
- Rate limiting / abuse protection
- Health check endpoint
- Graceful shutdown
