# Squad Lifecycle Rules

Single source of truth for how Chrono, model leads, and specialists manage lifecycle, effort tiers, and context discipline.

## 1. Persistent panes

Chrono + four model-lane windows stay in tmux indefinitely, with watcher/status surfaces for mailboxes. Routing is specialist-to-model, while compatibility namespaces remain stable for storage. Idle = zero token cost. Cost is per-task only.

## 2. Short conversation tail per model lead

Target no more than 3 tasks of conversation history per model lead session. On task pickup, read the task packet, relevant specialist markdown, relevant memory, and current state. Vault files are persistence; CLI conversation is per-task work window.

## 3. Prompt caching prefix discipline

- Cached prefix = model lead prompt + relevant specialist brief + optional memory head
- Per-task user message = inbox task body + minimal context excerpts only
- Anthropic prompt cache TTL is 5 min; covers idle gaps in active work-streaks
- Cache poison rule: never let per-task variables pollute the prefix

## 4. Compaction at phase boundaries

When a mode transitions Phase N to N+1, each model lead involved:

- Writes phase-summary line to memory.md
- Runs Anthropic compact_20260112 OR `/clear` + re-load from memory.md
- Acknowledges to Chrono

## 5. Hard reset on engagement close

Operator says "we're done" -> Chrono signals involved model leads -> each writes final state to memory.md -> full session reset.

## 6. Specialist subprocesses ALWAYS ephemeral

No persistence. Spawn for one task, die after. Output captured by Lead, written to outbox.

## 7. Per-task effort tiering

Specialist subprocess gets explicit effort flag per task tier:

- T1 trivia: `--effort low` / `--reasoning low` / no thinking
- T2 mechanical: `--effort medium` / `--reasoning medium` / thinking optional
- T3 judgment: `--effort xhigh` / `--reasoning high` / thinking on
- T4 multi-model fanout: each model at its scale's max

## 8. Context-budget circuit breaker

Each model lead has a max context window threshold (60% of model max). On hit: compact and alert `finance-analyst`.

## 9. Observability via finance-analyst + harness-optimizer

Per-model daily token/quota pressure is logged when available. Per-engagement spend is archived. Anomaly alerts surface in the next morning brief.

## 10. Knowledge-layer-first

Before any scout / research / discovery work, query the knowledge layer for prior attempts, findings, decisions, and ruled-out options. Native specialist invocation happens AFTER, not instead of, this check.

**Mandatory checks before fresh dispatch**:
- `chrono-vault` MCPs (`recall`, `vault_search`, `list_attempts`) — for prior attempts on the same target/topic and findings already recorded
- Relevant `memory.md` — for distilled knowledge that already answers the question
- `chrono/current.md` and pending Open Loops — for active work that overlaps

**Surface the result inline in the specialist invocation brief**: "Vault check: 2 prior attempts on Aptos (TASK-X, TASK-Y), both ruled out for KYC. Net: skip Aptos." Or: "Vault check: no prior attempts on this target, proceeding." An invocation brief that omits this line is incomplete.

This rule applies to: Bounty discovery, Research scouting, Security target selection, any "find me something new" work. It does NOT apply to: implementation work where the target is already chosen, content generation, mechanical specialist tasks.

Violation symptom (today's bounty work): Research and Security specialist invocations both scouted the 5 platforms from scratch instead of consulting the vault for what was already known about each target's KYC, reputation, and prior attempts. Repeated effort, missed context.

## 11. Browser attach — never spawn fresh

Every browser-touching specialist task attaches to the operator's running Chrome via CDP at `127.0.0.1:9222`. Chrono does not run browser discovery directly; Chrono dispatches the appropriate specialist and includes this browser rule in the task packet. Never spawn a new Chrome / Playwright / chrome-devtools instance with its own profile.

**Why**: the operator keeps Chrome open with 2FA'd, signed-in tabs for all 5 bounty platforms (HackerOne, Bugcrowd, Intigriti, HackenProof, Code4rena) plus other working state. Spawning fresh = fresh profile = no auth = useless. Worse, fresh-spawn collides with already-running profiles and produces confusing "profile lock" errors that masquerade as transient failures.

**Primary raw-CDP discovery flow** (specialists during browser-approved work):
1. Run `httpx http://localhost:9222/json/list` or `curl http://localhost:9222/json/list` to enumerate tabs and verify non-blank page titles.
2. If empty / unreachable: stop, write a NOTIFY to chrono pane, surface "operator's Chrome is not running" — do NOT auto-spawn.
3. To act on a tab: connect to the tab's raw CDP websocket from `/json/list`, then select and inspect only allowlisted tabs for the task.
4. MCP tools such as chrome-devtools-mcp or Playwright are needs-research alternates, not the primary path, because their pane configuration may spawn fresh Chrome profiles instead of attaching to the authenticated session.
5. NEVER pass `--user-data-dir` pointing to a fresh profile, NEVER let an MCP launch its own Chrome, NEVER spawn `playwright launch --browser chromium` without `connect_over_cdp`.

**Verification (read-only health check)**: `bin/browser-keep-alive.sh` runs nightly and surfaces missing platform tabs in the morning brief. Authenticated browser work should use the same raw-CDP `/json/list` check.

Violation symptom (today's bounty failure): Security tried to spawn fresh Playwright tabs while Chrome was already running, hit `chrome-profile` lock collision, lost ~15 minutes to Chrome profile path investigation that resolved nothing.

## 12. Memory discipline

See `shared/memory-discipline.md` for the universal rules every memory in the system obeys (timestamp + source citation, decay rules, purge-in-place, three-layer discipline auto-memory/squad/vault, redaction baseline, conflict resolution).

Namespace `memory.md` files add source-specific overrides on top. The cite at the head of each `memory.md` is mandatory.

## 13. Mode-close cleanup is mandatory

Every mode declares its ephemeral artifacts at Phase 0 (engagement start) and cleans them at mode-close. This rule exists because the squad accumulated 14+ orphan Chrome profiles, runaway tabs, and stale clone repos before this rule was written. Modes leak resources without an explicit cleanup phase.

See `shared/mode-cleanup.md` for the per-mode ephemeral-vs-durable matrix. Universal pattern:

**At Phase 0 (mode declaration)**:
- Mode lists `ephemeral_artifacts` (will be deleted at mode-close)
- Mode lists `durable_artifacts` (will be preserved — vault writes, KG entries, memory.md updates)
- Mode lists `external_resources_spawned` (Chrome profiles, sandbox containers, temp directories) for cleanup

**At mode-close (after vibecoding-check passes)**:
- Verify all `durable_artifacts` exist + are committed to vault
- Delete all `ephemeral_artifacts`
- Kill / close all `external_resources_spawned` (NOT the operator's persistent Chrome at port 9222 — that's durable infrastructure, not mode-spawned)
- Update relevant `current.md` files to clear active tasks for this mode
- Update memory.md with durable learnings (per `shared/memory-discipline.md`)

**Cleanup failure** = mode CANNOT declare done. Tier-3 OPERATOR escalation per vibecoding-check.

**Why this matters operationally**: a single bounty mode run can spawn:
- 1+ Playwright MCP Chrome profiles (each = 5-10 processes)
- 1+ chrome-devtools-mcp Chrome profiles
- Cloned target repos (often 100MB-1GB each)
- Sandbox containers (Docker, ephemeral VMs)
- Temp PoC artifacts (`/tmp/poc-*`, `_state/scratch/<mode-id>/`)

Without cleanup, these accumulate across runs. The 53-Chrome-process / 5.88GB-RSS / 12.5GB-swap state we hit on 2026-05-03 was the symptom; this rule is the fix.

**Always preserved (across all modes)**:
- Operator's main Chrome at port 9222 + `--user-data-dir=~/.config/chrono/chrome-profile` (the persistent bounty platform tab session)
- Vault entries (`vault/security/findings/F-NN-*.md`, `vault/research/topics/*.md`, etc.)
- Memory.md entries with durable learnings
- Dispatch log entries (`_state/dispatch-log.jsonl`)
- Audit trails (per-mode run logs in `_state/runs/`)

**Always cleaned (across all modes unless declared durable)**:
- Mode-spawned browser profiles (anything matching `mcp-chrome-*` or `chrome-devtools-mcp/*` profile patterns)
- Cloned external repos (`scratch/<mode-id>/<repo-name>/`)
- Sandbox containers tagged with the mode's run ID
- Temp directories under `/tmp/<mode-name>-<run-id>/`
- Draft/scratch artifacts (`_state/runs/<run-id>/scratch/`)

## 14. Mode-end vibecoding-check is mandatory

Every Mode (bounty / project / content / outreach / maintenance / incident / research / triage) runs `scripts/python/vibecoding_check.py` as its final phase before the Mode can declare itself done. The check is the canonical "verify before done" gate.

**Universal checks** (apply to every Mode):
1. Operator approval token present
2. Declared artifacts exist on disk
3. Citations resolve (URL 200 / file exists / git ref resolves)
4. No TODO / FIXME / XXX in modified code
5. All declared phase-tags emitted in run log

**Mode-specific extensions** (declared in `checks.yaml` per Mode):
- Project: tests pass, git clean, new code has tests, no destructive ops
- Bounty: scope_gate ran, CVSS recorded, PoC reproduces, no self-inflicted
- Content: voice consistent, asset paths resolve, length bounds, no placeholder text
- (other modes per-spec — see each `shared/modes/<mode>.md`)

**Failure tiers** (per `shared/specialists/vibecoding-check.md`):
- Tier 1 (PASS=0): all checks green, mode can declare done
- Tier 2 (AUTOFIX=1): minor issues fixable inline, fix and recheck
- Tier 3 (RETRY=2): recoverable but needs phase re-run
- Tier 3+ (OPERATOR=3): surface to operator, mode cannot self-declare done

Each `shared/modes/*.md` file must name vibecoding-check as a pre-completion gate. If a mode does not declare its final check, `bin/validate-specialists.sh` and `bin/doctor.sh` treat that as instruction drift.

Violation: a Mode that declares itself "done" without running vibecoding-check is in violation of this rule. Coordinator (Chrono) refuses to surface such a Mode as completed to operator until the check has run.

## 15. Finished plans/specs/handoffs are cleanup debt

Plans, specs, and handoffs are temporary work scaffolding. They are not durable product truth.

When a plan/spec/handoff finishes:

1. Fold durable decisions into canonical markdown:
   - `README.md`
   - `docs/production-readiness.md`
   - `docs/state-model.md`
   - `docs/model-runtime-map.md`
   - `shared/routing.md`
   - `shared/lifecycle.md`
   - `shared/mode-cleanup.md`
   - model lead and specialist markdown
2. Delete the completed plan/spec/handoff.
3. Keep an example only if it is intentionally curated under `examples/`.
4. Never let `docs/handoffs/`, `_state/*draft*`, `_state/*research*`, old `docs/specs/*`, or old `docs/plans/*` become runtime truth.

Cleanup is part of done. A mode, maintenance task, or product-readiness pass cannot declare itself complete while obsolete plans/specs/handoffs remain in the product tree.

Why: stale plans and handoffs look authoritative to future agents. They cause instruction drift, duplicate source-of-truth surfaces, and extra operator file-organizing work.

## Model-lane effort defaults

Set in `bin/launch-squad.sh`.

| Model lane | CLI | Model | Effort tier flag | Rationale |
|------|-----|-------|------------------|-----------|
| chrono | claude | opus | `--effort xhigh` | Coordinator judgment is high-stakes |
| gpt-codex | codex | gpt-5.5 | `-c model_reasoning_effort=high` | implementation depth |
| claude | claude | opus | `--effort xhigh` | judgment and safety depth |
| gemini | gemini | gemini-3.1-pro-preview | model default | grounded content and media |
| kimi | kimi | k2.6 | `--thinking` | long-context synthesis |

## Per-task overrides

A specialist subprocess can scope effort up or down per task:

```bash
# Trivia — scope down
claude -p --effort low "<trivia task>"

# Adversarial review — scope up
claude -p --effort xhigh "<judgment task>"
```

Model lead pane default is the background tier; specialist tier is work-specific.

### Tier guidance per work type

- T1 (trivia): single-call factual lookups, classification, mechanical pattern matching
- T2 (mechanical): implementation work, mechanical specialist routines, fast iteration
- T3 (judgment/review): reviewer roles, high-stakes decisions, deep reasoning, design choices
- T4 (multi-model fanout): security-sensitive, irreversible, contested calls

---

*See also: `shared/api-catalog.md` for per-specialist tool catalog. `chrono/CLAUDE.md` for Coordinator runtime rules.*
