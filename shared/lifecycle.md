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

Violation symptom: Research and Security specialist invocations both scouted targets from scratch instead of consulting the vault for what was already known about each target's reputation and prior attempts. Repeated effort, missed context.

## 11. Browser attach — never spawn fresh

Every browser-touching specialist task attaches to a persistent, CDP-accessible Chrome (default port 9222) rather than spawning fresh. Chrono does not run browser discovery directly; Chrono dispatches the appropriate specialist and includes this browser rule in the task packet. Never spawn a new Chrome / Playwright / chrome-devtools instance with its own profile.

**Why**: the persistent Chrome holds your signed-in working browser session plus other working state. Spawning fresh = fresh profile = lost session state = useless. Worse, fresh-spawn collides with already-running profiles and produces confusing "profile lock" errors that masquerade as transient failures.

**Primary raw-CDP discovery flow** (specialists during browser-approved work):
1. Run `httpx http://localhost:9222/json/list` or `curl http://localhost:9222/json/list` to enumerate tabs and verify non-blank page titles.
2. If empty / unreachable: stop, write a NOTIFY to chrono pane, surface "the persistent CDP Chrome is not running" — do NOT auto-spawn.
3. To act on a tab: connect to the tab's raw CDP websocket from `/json/list`, then select and inspect only allowlisted tabs for the task.
4. MCP tools such as chrome-devtools-mcp or Playwright are needs-research alternates, not the primary path, because their pane configuration may spawn fresh Chrome profiles instead of attaching to the existing signed-in session.
5. NEVER pass `--user-data-dir` pointing to a fresh profile, NEVER let an MCP launch its own Chrome, NEVER spawn `playwright launch --browser chromium` without `connect_over_cdp`.

**Verification (read-only health check)**: `bin/browser-keep-alive.sh` runs nightly and surfaces missing session tabs in the morning brief. Browser work should use the same raw-CDP `/json/list` check.

Violation symptom: a lane tried to spawn fresh Playwright tabs while Chrome was already running, hit a `chrome-profile` lock collision, lost ~15 minutes to Chrome profile path investigation that resolved nothing.

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
- Kill / close all `external_resources_spawned` (NOT the persistent CDP Chrome at port 9222 — that's durable infrastructure, not mode-spawned)
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
- The persistent CDP Chrome at port 9222 + `--user-data-dir=~/.chrono/chrome-persistent-profile` (the persistent signed-in browser session)
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

## 14. Mode-end verification spine v1

`scripts/python/vibecoding_check.py` is the canonical end-of-run gate for the typed v1 profiles. v1 supports **Project** and **Bounty** only. Content, Research, Incident, Maintenance, Outreach, and Triage are explicit `OPERATOR=3` unsupported-profile stops until v1.1; they must not receive a legacy or vacuous pass.

Admission derives a dispatcher-pinned `verification-contract/v1`, rather than trusting author declarations. Every accepted `verification-run/v1` trace bundle contains ordered, evidenced S0–S7 proof records; nonempty admission-derived verification coverage; current artifact/action/gate hashes; literal local-only delivery; and the required mode evidence.

- **S0** admits the task and pins its immutable contract.
- **S1/S7** are mandatory memory bookends: canonical recall/usage evidence before work and record receipts bound to the final artifact bundle after work.
- **S2/S5** require passing, different-family plan and deliverable reviews bound respectively to the current plan and artifact-bundle hashes.
- The **I-loop** routes review/verification failures to S2 or S3. A plan or artifact change invalidates stale verification, reviews, gates, delivery, and S7 memory evidence; close uses only current-hash bindings.
- **S6 is local-only in v1.** `delivery.external` must be literal `false`; Bounty submission must be literal `false`. External delivery remains a hard operator stop.

The executable retains six universal checks: operator approval; declared artifact presence; citation resolution; TODO/FIXME/XXX detection; phase proof; and unauthorized-deletion detection. Link liveness is advisory only, while missing filesystem or git citations remain blocking. Typed requirements are derived from the dispatcher-pinned verification contract and enforced in `vibecoding_check.py`.

The emitted tiers are exact: **OK=0**, **AUTOFIX=1** only when a meaning-preserving repair actually ran, **RETRY=2** for recoverable work-not-met, and **OPERATOR=3** for governance, structure, trust-anchor, or unsupported-profile failures. A broad override cannot satisfy the typed close contract.

Known temporal limitation: v1 binds S2 review to the current plan hash and invalidates it after later plan changes, but cannot prove in wall-clock time that S2 completed before S3 production when the plan hash never changed. Strict temporal ordering is deferred to v1.1.

Trust residual: within the trusted single-user filesystem boundary documented in `shared/protocol.md`, reviewer-family claims, memory receipts, and verification evidence receive shape, file-hash, identity, and subject-binding validation—not cryptographic provenance. Acceptance canaries must therefore use real independent reviewer and MCP receipts; fixture-shaped bytes are only for hermetic tests. Cryptographic attestation is deferred to v1.1.

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
