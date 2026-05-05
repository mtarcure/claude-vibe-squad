---
updated: 2026-05-04
---

# Squad Roadmap

Planning queue for current and next work. Runtime truth lives in `_state/active-tasks.json`, `chrono/current.md`, and `departments/*/current.md`. Completed specs, handoffs, and draft plans are not kept here after their decisions are folded into canonical docs.

## Active

(none)

## Queued

1. **Bounty mode dry-run** — first real bounty using the new 12-phase substrate. Phase 0 discovery via Chrono + operator, Phase 1 OSINT via Research, Phase 2 program scope via Security. Operator-driven; validates the restructure end-to-end on real work.
2. **Per-namespace SSE chrono MCPs** (only if needed) — currently all 4 chrono MCPs (vault/kg/obsidian/catalog) connect to the same SSE endpoint, so CLIs may list duplicate tools. If noise becomes a problem, split into separate ports.

## Recently Folded

May 4 cleanup decisions now live in current docs:

- Brain/source-of-truth model: `docs/brain-map.md`
- Runtime truth and public/private boundary: `docs/state-model.md`, `docs/private-config.md`
- Release and command surface: `docs/production-readiness.md`, `README.md`
- Lifecycle cleanup rule: `shared/lifecycle.md`

## Conventions

- Active plans may live in `docs/roadmap.md` or a current file while work is live.
- When work finishes, fold durable decisions into canonical docs and delete completed scaffolding.
- Drafts in `_state/*draft*`, `_state/*research*`, `docs/specs/`, `docs/plans/`, and `docs/handoffs/` are temporary unless explicitly curated as examples.
- Roadmap is the planning queue. If it conflicts with `_state/active-tasks.json` or current files, fix the stale document before acting.

## Update protocol

- Chrono updates this file when:
  - A new spec is created
  - A spec moves between Active / Queued / Done
  - A queued item gets bumped in priority
- `current.md` references the roadmap; doesn't duplicate it.
- Single edit per state change, atomic write.
