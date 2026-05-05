# Chrono Current State

Updated: 2026-05-05

## Active Tasks

No tracked active tasks in `_state/active-tasks.json` at the time of this public-release cleanup.

## Current Work

The repo is being simplified from department-led routing to:

```text
Operator -> Chrono -> 4 model leads -> specialists
```

Canonical routing is `shared/specialist-runtime-map.tsv`. Visible runtime windows are `chrono`, `gpt-codex`, `claude`, `gemini`, `kimi`, and `watchers/status`.

## Open Loops

- Finish stale markdown/script cleanup.
- Run validators and dispatch smoke tests.
- Commit, push, and merge only after local checks are clean.
