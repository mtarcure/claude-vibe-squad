# Mode Cleanup — Per-Mode Ephemeral vs Durable

Cited by `shared/lifecycle.md` rule 13 (mode-close cleanup is mandatory).

This file declares per mode what's ephemeral (cleaned at mode-close) vs. durable (preserved). Each mode reads this on engagement start (Phase 0) and applies the cleanup at mode-close.

**Stub status (2026-05-03)**: Universal patterns documented. Per-mode declarations are starter rules — refine each in Phase 5 when the mode-close cleanup discipline is wired into actual mode workflows.

---

## Universal — apply to every mode

**Always preserved (across all modes)**:
- Operator's main Chrome at port 9222 + `--user-data-dir=~/.chrono/chrome-persistent-profile`
- Vault entries (`vault/security/findings/F-NN-*.md`, `vault/research/topics/*.md`, `vault/programs/*.md`, etc.)
- Memory.md entries with durable learnings (per `shared/memory-discipline.md`)
- Dispatch log entries (`_state/dispatch-log.jsonl`)
- Audit trails / per-mode run logs (`_state/runs/<run-id>/run-log.md`)
- Final artifacts surfaced to operator (anything operator approved or published)

**Always cleaned (across all modes unless declared durable)**:
- Mode-spawned browser profiles matching: `~/Library/Caches/ms-playwright/mcp-chrome-*`, `~/.cache/chrome-devtools-mcp/chrome-profile`
- Cloned external repos (`scratch/<mode-id>/<repo-name>/`)
- Sandbox containers tagged with the mode's run ID
- Temp directories under `/tmp/<mode-name>-<run-id>/`
- Draft / scratch artifacts (`_state/runs/<run-id>/scratch/`)
- Browser tabs spawned for testing (NOT the persistent CDP Chrome session at port 9222)
- Completed plans/specs/handoffs after durable decisions are folded into canonical docs

---

## Plan / Spec / Handoff Cleanup

Applies to every mode and maintenance task.

| Artifact | Default action when done |
|---|---|
| `docs/plans/*.md` | Fold durable decisions into canonical docs, then delete. |
| `docs/specs/*.md` | Fold durable architecture/rules into canonical docs, then delete. |
| `docs/handoffs/*.md` | Treat as local session history; delete after live state and canonical docs supersede it. |
| `_state/*draft*` | Delete after accepted content is merged into product files. |
| `_state/*research*` | Fold citations/findings into durable docs or memory, then delete. |

Allowed exception: a deliberately curated sample under `examples/`.

Not allowed: leaving completed plans/specs/handoffs in the product tree because they are "maybe useful later."

Vibecoding-check must fail a mode-close if completed plan/spec/handoff scaffolding remains and is not listed as an explicit operator-approved exception.

## Bounty Mode

| Category | Items | Action at mode-close |
|----------|-------|----------------------|
| **Durable (preserve)** | F-NN findings, program intel, reusable technique notes, submission narratives, payout records | Commit to `vault/security/` as appropriate, promote program records to `vault/security/programs/<program>/`, update `memory.md` |
| **Ephemeral (clean)** | Cloned target repos in `scratch/`, spawned Playwright/chrome-devtools profiles, sandbox containers tagged with `run_id`, PoC scratch artifacts under `/tmp/poc-*`, test exploit outputs | Delete after vibecoding-check passes |
| **Operator-decision** | Disclosed PoCs, public writeups | Surface to operator before deletion |

**Specific to bounty**: PoC code sometimes has long shelf-life value (variant hunting). Default: archive to `vault/security/techniques/<technique>.md` and delete the runtime artifact. Operator can override.

### Colima / Docker container discipline (bounty mode)

Bounty work that uses Docker containers (CTF challenges, target services, sandboxed exploits) follows this lifecycle:

**Phase 0 (mode start)**:
- Check `colima status` — if not running, `colima start`
- Tag every container spawned this run with the mode's `run_id` label: `docker run --label vibesquad.run_id=<run_id> ...`

**Mode-close (after vibecoding-check passes)**:
- `docker ps -q --filter "label=vibesquad.run_id=<run_id>"` → enumerate containers from this run
- `docker stop $(docker ps -q --filter "label=vibesquad.run_id=<run_id>")` — stop them
- Optionally remove if disposable: `docker rm` (only if PoC/test, never if operator might want to resume)
- If no other modes are using colima: `colima stop` to free RAM + CPU

**What NEVER gets cleaned**:
- Docker images (`docker images` — these persist as the tool cache; 57GB+ on this Mac as of 2026-05-03)
- Named volumes (operator's persistent data)
- Containers tagged with `vibesquad.persistent=true` (operator-blessed long-running)

**Why this matters**: idle colima with running containers costs ~1GB RAM + variable CPU continuously. The 2026-05-03 Mac audit found 9 containers from cybench/dexalot work running idle for 6 days, contributing 171% CPU drain and memory pressure that eventually crashed terminal responsiveness. The fix is per-bounty start/stop discipline — not running colima 24/7.

**Resume pattern** (operator returning to a paused bounty):
```bash
colima start
docker start <run-id-containers>
# OR if containers were removed:
# rebuild from images (which persisted on VM disk)
```

---

## Project Mode

| Category | Items | Action at mode-close |
|----------|-------|----------------------|
| **Durable (preserve)** | Committed code changes, ADRs / design docs, tests and verification records, deploy configs, final PR / handoff notes | Already in git; verify committed |
| **Ephemeral (clean)** | Scratch specs, exploratory branches not merged, prototype directories, draft PRs not opened | Delete after merge / explicit decision |
| **Operator-decision** | Unshipped feature branches, WIP PRs | Surface — operator decides retain or drop |

---

## Content Mode

| Category | Items | Action at mode-close |
|----------|-------|----------------------|
| **Durable (preserve)** | Final approved pieces, final approved assets, voice anchors learned, audience-pattern updates, brand-voice refinements | Commit to `vault/content/` and `memory.md` |
| **Ephemeral (clean)** | Draft iterations, dead-end variants, scratch outlines, rough generated assets | Delete after final approved |
| **Operator-decision** | Drafts marked "maybe later" by operator | Move to `vault/content/parked/` |

---

## Maintenance Mode

| Category | Items | Action at mode-close |
|----------|-------|----------------------|
| **Durable (preserve)** | Doctor logs, cleanup proposals, dependency-update records, system-snapshot diffs, `regression-test-results.md`, `changelog.md` | Already in `_state/` |
| **Ephemeral (clean)** | Temp diff files, before/after captures, scratch script tests | Delete |

---

## Incident Mode

| Category | Items | Action at mode-close |
|----------|-------|----------------------|
| **Durable (preserve)** | `postmortem.md`, fix commits, verification notes, runbook updates, learnings under `vault/incidents/` | Commit + propagate |
| **Ephemeral (clean)** | Stack-trace scratch files, ruled-out hypothesis docs, raw trace dumps | Delete after postmortem written |

---

## Research Mode

| Category | Items | Action at mode-close |
|----------|-------|----------------------|
| **Durable (preserve)** | Final synthesis, source-tier learnings, topic-map updates, citation chains, `integrity-report.md` | Commit to `vault/research/` |
| **Ephemeral (clean)** | Raw fetched source dumps, intermediate synthesis drafts, exploration scratch | Delete after final synthesis written |

---

## Triage Mode

| Category | Items | Action at mode-close |
|----------|-------|----------------------|
| **Durable (preserve)** | Triage decision log entry, `routing-decision.md` | Append to `_state/triage-log.jsonl` and preserve run artifact |
| **Ephemeral (clean)** | none | n/a |

---

## How modes invoke this

At Phase 0 (mode declaration), the mode references this file and declares its specific ephemeral list (in case it deviates from the per-mode defaults above). At mode-close (after vibecoding-check passes), the cleanup phase runs:

```bash
# Pseudocode — actual cleanup is per-mode-specific
for path in $EPHEMERAL_PATHS; do
    rm -rf "$path"
done

for profile in $SPAWNED_BROWSER_PROFILES; do
    pkill -f "user-data-dir=${profile}"
done

# Verify durable artifacts exist
for artifact in $DURABLE_ARTIFACTS; do
    [[ -f "$artifact" ]] || fail "Missing durable artifact: $artifact"
done
```

**Per-mode wiring** (Phase 5 follow-up): each `shared/modes/<mode>.md` gets a `## Cleanup (Phase N+1, after vibecoding-check)` section that enumerates its specific ephemeral paths + cleanup commands.

---

## Audit hooks

- `bin/squad-stop.sh` runs the universal cleanup (Chrome orphan profiles) on session close — partial coverage of this rule for the case where modes were left in-flight.
- `vibecoding_check.py` should fail mode-end if `ephemeral_artifacts` listed in mode declaration still exist on disk after cleanup phase (Phase 5 wire-in).
- `bin/doctor.sh` should detect orphan resources (Chrome profiles >24h old, scratch directories >7d old, sandbox containers running >24h with no recent activity) and surface in morning brief.
