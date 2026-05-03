# Coding Department — Durable Memory

This is the Coding Lead's long-term memory. Distilled knowledge, not transcripts.

## Repo Conventions

(Populate as you work on actual repos. Examples to follow:)

- *(per-repo conventions go here once Coding Lead has worked on real repos)*

## Known Sharp Edges

- `bin/vibecoding-check.sh` uses `uv` and may need network/cache access to fetch `httpx`/`pyyaml`; sandboxed runs can fail on `~/.cache/uv` permissions or DNS if dependencies are not already cached.
- Ad hoc mailbox tasks with `run_id: none` do not have `_state/runs/<run-id>/manifest.yaml`, so `vibecoding-check.sh --run-id <task-id>` cannot evaluate them unless a run manifest is created upstream.

## Decisions That Stuck

- *(architectural decisions worth remembering)*

## Tools and Commands

- *(non-obvious commands worth keeping)*

---

*Memory is curated, not appended. When something turns out wrong, REMOVE — don't add a contradicting line.*

## v1.1 update — 2026-05-03

The squad shipped v1.1 with explicit tool catalogs in every specialist file,
per-pane effort/thinking tier defaults, capability inventory, and Topology B
direct-with-CC patterns. When dispatching a specialist now, trust that its
identity.md enumerates available MCPs / native CLI features / skills / APIs
— no need to remind it. Lead-to-Lead direct-with-CC patterns are documented
in this LEAD.md. See shared/lifecycle.md for lifecycle rules.
