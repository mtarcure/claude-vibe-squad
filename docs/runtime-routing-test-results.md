# Runtime Routing Test Results

Status: in progress
Started: 2026-05-04
Owner: Chrono / sysmgmt namespace

## Scope

These tests verify whether the proposed runtime routing overlay is viable before changing dispatch behavior or moving specialist files.

Reference design: `docs/runtime-routing-overlay.md`

## Pass Criteria

- Runtime starts without MCP handshake/startup failures.
- Output follows requested schema.
- Multi-runtime outputs include provenance.
- Parallel/non-owner roles do not edit files.
- Synthesis preserves disagreements instead of averaging them away.
- Active registry closure is tested before rollout.

## Stage A: Single Runtime Startup

| Runtime | Command shape | Result | Notes |
|---|---|---|---|
| Codex | `codex exec -c model_reasoning_effort=low "Reply exactly: ok"` | pass | Finished in ~5s; no old `Method Not Allowed` Chrono MCP startup errors. |
| Gemini | `gemini -p "Reply exactly: ok"` | pass | Returned `ok`; warned about `TERM=dumb`, missing ripgrep fallback, and both Google/Gemini keys being set. No MCP startup failure surfaced. |
| Kimi | `kimi --print --prompt "Reply exactly: ok"` | pass | Returned `ok`; MCP loading connected 7/7 servers with 26 tools. |
| Claude | signed-in `squad:4.0` SysMgmt pane, `Reply exactly: ok` | pass | Pane shows Claude Code v2.1.126, Sonnet 4.6 high effort, Claude Max. Response: `ok`. Prior direct shell test was invalid because API-key env vars forced the wrong auth path. |

Latest MCP audit:

- `bash bin/mcp-audit.sh`
- Result: `issues=0 warnings=0`
- Log: `_state/audit-logs/2026-05-04-mcp-audit.md`

## Stage B: Multi-Runtime Planner Fixture

Prompt:

```text
Runtime test fixture. You are one reviewer in a multi-runtime planner test.
Goal: verify whether Vibe Squad should use capability-first specialist routing with runtime leads.
Return exactly three bullets: 1 risk, 1 benefit, 1 test you require before rollout.
```

Runtimes tested:

- Codex
- Gemini
- Kimi

Claude was not included because the original direct shell test used the wrong auth path. A later pane-based Claude Max smoke passed in `squad:4.0`; rerun the multi-runtime fixture with Claude included before enabling routing behavior.

## Stage B Findings

### Benefits Converged

All available runtimes agreed the overlay improves model-task fit without requiring immediate filesystem reorganization or duplicate specialist files.

### Risks Diverged Usefully

- Codex flagged routing ambiguity and handoff latency.
- Kimi flagged read-only/write-owner enforcement and state drift.
- Gemini flagged split-brain synthesis, where merged outputs could hide incompatible constraints.

### Required Next Test

Before rollout, run a constraint-collision smoke test:

1. Create a harmless planning fixture with two valid-looking but conflicting constraints.
2. Run at least two runtimes independently.
3. Require `skeptic` or `synthesizer` to preserve the conflict explicitly.
4. Verify no non-owner runtime edits files.
5. Verify `_state/active-tasks.json` closes cleanly.

## Stage B Interim Verdict

The runtime routing overlay remains promising, but it is not approved for dispatch behavior changes yet.

At this point, the next required gate was:

- constraint-collision multi-runtime fixture
- then live dispatch proof
- then routing/index/specialist metadata updates

Do not move specialist files, delete department structure, or introduce generated-agent changes from this result alone.

## Stage C: Constraint-Collision Fixture

Prompt:

```text
Constraint-collision routing test. You are <runtime> reviewer.
Fixture: Vibe Squad must (A) preserve local daily-driver runtime state without interrupting active work, and (B) ship a clean public v1 repo with no runtime state, private memory, or completed bounty/client artifacts.
Should runtime routing overlay proceed?
Return JSON with keys runtime, verdict, conflict, required_gate. No file edits.
```

Runtimes tested:

- Codex
- Gemini
- Kimi

Claude was not included because the original direct shell test used the wrong auth path. A later pane-based Claude Max smoke passed in `squad:4.0`; rerun the multi-runtime fixture with Claude included before enabling routing behavior.

## Stage C Findings

All tested runtimes preserved the contradiction instead of flattening it:

- Codex verdict: `do_not_proceed`
  - Required gate: verify a clean public release boundary from a sanitized copy or allowlisted export while preserving active runtime state in place.
- Gemini verdict: `proceed`, but only with a required `state_isolation_test`
  - Required gate: run Chrono from clean public capability paths while redirecting active runtime output/state to an external or ignored `runtime_root`.
- Kimi verdict: `blocked`
  - Required gate: state-separation smoke test proving `_state/`, private config, and completed bounty artifacts can be excluded from public v1 without breaking active dispatch paths.

Stage C passed as a disagreement-preservation test because the runtimes independently surfaced the same blocker: runtime state must be isolated from public product files before routing changes are implemented.

## Updated Verdict

The runtime routing overlay remains a good target design, but dispatch behavior changes are blocked until state separation is proven.

Proceed only to the next gate:

- state-separation smoke test
- then live dispatch proof with registry closure
- then routing/index/specialist metadata updates

Do not move specialist files, delete department structure, introduce generated-agent changes, or enable runtime-based dispatch from this result alone.

## Stage D: State-Separation Smoke Test

Command:

```bash
bash bin/product-hygiene.sh
```

Result: fail, as expected for the current working tree.

The read-only hygiene gate found:

- Runtime paths: 20
- Mailbox task files: 141
- Draft/spec/handoff paths: 18
- Tracked public-release blockers: 5

Tracked blockers that would ship unless curated:

- one local token/spend runtime report
- two historical local handoffs
- one old implementation plan
- one old implementation spec

Prevention fix applied:

- `.gitignore` now ignores `departments/*/archive/*.md`.
- `bin/product-hygiene.sh` now reports tracked public-release blockers separately from local runtime debris.

Updated gate status: state separation is not proven yet. Cleanup/disposition must happen before live dispatch/routing behavior changes.

## Stage D Follow-Up: Public Export Gate

Command:

```bash
bash bin/product-hygiene.sh --public-export
```

Result: pass.

After removing the five dispositioned tracked blockers, the hygiene audit reports:

- Runtime paths: 20
- Mailbox task files: 141
- Draft/spec/handoff paths: 15
- Tracked public-release blockers: 0

Interpretation:

- Public-export tracking is clean for this blocker class.
- Strict local hygiene still fails because runtime/mailbox debris remains in the working tree.
- Local debris is ignored and must be cleaned only after operator-approved runtime cleanup, not as part of public export.

## Stage E: Dispatch Lifecycle Smoke

Location: `/tmp/vibe-squad-current-smoke`

The smoke used a throwaway copy of the current workspace so `bin/send-task.sh` could exercise its auto-snapshot behavior without committing the active cleanup workspace.

Commands exercised:

- `SKIP_NUDGE=1 VAULT_ROOT=/tmp/vibe-squad-current-smoke bash scripts/send-task.sh sysmgmt smoke-task-body.md`
- `VAULT_ROOT=/tmp/vibe-squad-current-smoke bash bin/send-task.sh --close-task <TASK-ID>`

Result: pass for dispatcher and registry lifecycle.

Verified:

- compatibility wrapper routes through hardened dispatcher
- auto-snapshot runs in a Git repo
- inbox file is named `TASK-ID.md`
- toolkit injection runs
- `_state/active-tasks.json` gets an `in-flight` entry
- `_state/dispatch-log.jsonl` gets a dispatch record
- manual `--close-task` marks registry entry `complete`
- preflight reconciliation closes a task when its outbox response exists before the next dispatch

Not tested in this smoke:

- real watcher pane response closure
- real Lead processing of the task body
- tmux nudge path

Next dispatch gate: run a controlled live watcher/Lead smoke after local runtime cleanup or with an explicitly approved live task.

## Stage F: Live Watcher And Lead Smoke

Live task:

- `TASK-2026-05-04-2000-live-smoke`
- Lead: `sysmgmt`
- Runtime: signed-in Claude Max pane

Result: partial pass with one watcher bug found and fixed.

Verified live:

- `sysmgmt` inbox watcher detected the task file.
- tmux nudge reached `squad:sysmgmt`.
- sysmgmt namespace picked up the task in Claude Max.
- Lead wrote `departments/sysmgmt/outbox/TASK-2026-05-04-2000-live-smoke-response.md`.
- Lead archived the original task.
- Outbox watcher nudged Chrono.
- Chrono read and surfaced the response.

Bug found:

- Existing outbox watcher processes nudged Chrono but did not close `_state/active-tasks.json`.
- The live watcher window was also malformed: only some inbox watchers were running correctly, while several watcher commands were left as text in the pane.

Fixes applied:

- `bin/outbox-watcher.sh` now closes the active registry directly with an atomic Python update instead of shelling through `bin/send-task.sh`.
- `bin/launch-squad.sh` now starts all inbox/outbox watchers under one watcher supervisor pane instead of trying to tile ten watcher panes.
- Watcher launch summary now reports 10 fswatch processes: inbox + outbox per Lead.

Cleanup:

- Smoke runtime artifacts were removed with `SQUAD_CLEAN_CONFIRM=1 bash bin/product-hygiene.sh --apply`.
- Final strict hygiene result: `runtime=0 mailbox=0 tracked_blockers=0`.

Follow-up watcher supervisor proof:

- Disposable tmux session `watcher-smoke` started the new watcher command in one pane.
- All 10 watcher startup lines appeared: inbox + outbox for coding, security, content, sysmgmt, and research.
- Disposable session was killed after the proof; live `squad` session was not restarted.

Remaining verification:

- On the next real `squad stop` / `squad up`, confirm the live watcher pane uses the new supervisor command and no stale watcher processes remain.
