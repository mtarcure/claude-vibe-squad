---
name: code-reachability-audit
audience: specialist
description: "Use before classifying a repository file or script as dead or proposing deletion: census static, dynamic, CI, hook, manifest, documentation, and host-scheduler callers; prove the search with positive and negative controls; classify reachability and resolve misleading mentions. Not for restructuring a live module graph."
---

# Code Reachability Audit

Deciding a file is dead is a deletion, and deletions are irreversible. The claim
"nothing calls this" is an **absence** claim, so it needs an exhaustive search
plus a control proving the search can detect presence. A grep miss is not proof.

## The search set — every surface, not just the obvious ones

A repo-only `git grep` is **not** exhaustive. Check all of these:

| Surface | Why it hides callers |
|---|---|
| Shell | `exec`, `source`, `bash "$VAR"`, paths built from `$(dirname …)` |
| Python | `subprocess`, `Path(...)`, names assembled from parts |
| `.github/workflows/**` | CI is a caller with no in-repo reference to it |
| Git hooks (`.githooks/**`) | invoked by git, never by code |
| Plugin manifests, lane adapters | declarative wiring, not calls |
| **`~/Library/LaunchAgents/*.plist`** | **outside the repo entirely** |
| `crontab -l`, systemd units | same class as launchd on other platforms |
| Operator documentation | a script a human runs on purpose is **live** with zero programmatic callers |

**The launchd surface is the one that bites.** On 2026-08-06 an audit classified
`bin/squad-monitor.sh` as dead on correct in-repo evidence — its only references
were two tests. It runs **every 120 seconds** via `com.chrono.squad-monitor`,
registered in `~/Library/LaunchAgents/`, where no `git grep` reaches. Six repo
scripts are bound that way. `bin/doctor.sh` now reports the mapping on every
health run; read it before calling anything dead.

## Matching, without fooling yourself

Both failure directions are real and both happened in one session:

- **Too loose.** A bare basename search reported `capture.py` as having six
  callers. Every hit was inside `autocapture.py`.
- **Too strict.** Anchoring with `[^A-Za-z0-9_/-]` then excluded `/`, hiding
  path-qualified references, so a file with a live caller looked orphaned.

Use `(^|[^A-Za-z0-9_-])<basename>` — allow a path separator before the name,
forbid word characters.

## Two controls, every time

1. **Positive** — search for a file you *know* is live and confirm the census
   returns its callers. If it cannot find a known caller, its silence is
   meaningless.
2. **Negative** — search for an invented filename and confirm zero rows. This is
   what makes empty output evidence rather than an artifact.

## Read the hit before believing it

A reference is not always a call:

- `vs-dashboard-loop.sh` mentions `watch-lane.sh` in a comment — *"Replaces the
  old 4-lane watch-lane.sh render."* **A mention of what something replaced is
  not a call.**
- Prose documenting a removal necessarily names the thing removed. A regex
  counting "stale terminology" will score those as drift; they are the record of
  the change.
- A parser may consume a literal string that *looks* like prose. Seven references
  to `Expected Model Lane Tool Surface` were to a block name still emitted at
  runtime; renaming them would have broken the parser.

## Buckets

`entry-point` (humans or CI invoke it; zero callers is correct) · `live` ·
`reachable-dynamically` (runtime-constructed path; evidence required) ·
`legacy-live` (reachable but built for a retired architecture — say what must
change before retiring it) · `dead`.

## Before deleting

- Prove equivalence where you can. Truncating a file after an unconditional
  `exit` should produce **byte-identical output** — restore the original *inside
  its own directory* so path resolution matches, and diff the two runs. A control
  run from a temp directory measures the environment, not the change.
- Deleting code deletes its dedicated tests too; a test for removed code is also
  dead. A test that covers the removed thing *among others* is not — edit it or
  leave the code alone.
- Sweep for stranded references afterwards: file headers describing what is
  "below", docs pointing at output directories nothing writes any more, and
  glob-based config where **case matters** (`action-log.md` will not match
  `ACTION-LOG.md`).
