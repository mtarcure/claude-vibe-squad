# Vibe Squad Architecture

Vibe Squad is a **markdown-first, board-native** multi-model harness. A coordinator (Chrono) runs in a tmux window; every specialist runs as a **fresh, capability-scoped CLI spawned per task in its own git worktree**. Work moves as markdown task packets in per-namespace mailbox folders. There is no TUI app, no PTY supervisor, and no daemon on the dispatch path.

> Historical note: an earlier redesign proposed an Ink (Node/React) TUI backed by a FastAPI daemon as the dispatch spine. That design was **not built** — see "Planned (not built)" at the end. A later stage of the system did run four long-lived per-model tmux "lane" windows; that model was **retired at the Phase-3 board cutover** and no persistent model lanes exist today. This document describes the system that actually ships.

## Runtime shape

```
tmux session `squad`
  ├─ window 0: chrono            — coordinator, Claude Code (+ live dashboard sidebar)
  └─ window 5: watchers/status   — watcher fleet + status readouts
        │
        │  dispatch = markdown packets on the filesystem
        ▼
  departments/<namespace>/inbox/   ← Chrono writes packets here
  departments/<namespace>/outbox/  ← specialists write responses here
        │
        │  bin/send-task.sh → detached bin/board-supervisor.sh
        ▼
  one git worktree per attempt (_state/board-worktrees/<attempt-id>/)
        │
        │  a fresh specialist CLI is spawned into that worktree,
        │  bound to the model its runtime-map row selects
        ▼
  artifact written first → validated outside the worktree
        │
        ▼
  outbox response envelope → bin/registry-reconciler.sh settles the task

  MCP servers (per-CLI registration, no proxy)
        ├─ chrono-vault (+ chrono-kg / chrono-obsidian legacy namespace aliases)
        ├─ chrono-research-arsenal
        ├─ chrono-media-studio
        └─ chrono-recon
  Persistent Chrome (CDP :9222) — kept alive outside the squad lifecycle
```

The launcher creates exactly **two** windows — `chrono` (window 0) and `watchers/status` (window 5). Specialist CLIs are not windows at all; they are detached, per-task child processes.

## Entry point & launcher

- `bin/vibe-squad` — thin passthrough to `bin/squad` (backward-compat name).
- `bin/squad` — lifecycle CLI: `up` (default), `stop`, `status`, `doctor`, `attach`, `detach`.
- `bin/launch-squad.sh` — creates the tmux session `squad` (the `chrono` coordinator window plus the `watchers/status` window), applies PATH/auth prefixes, and starts the coordinator and watcher fleet. It does **not** start any specialist CLI: those are spawned per task by the board. Re-running re-attaches an existing session (idempotent).

`stop` / `status` / `doctor` route to `bin/squad-stop.sh`, `bin/where-are-we.sh`, and `bin/doctor.sh` respectively.

## Components

### Chrono (coordinator)
Window 0 runs Claude Code, auto-loading `chrono/CLAUDE.md`. Chrono is the only controller and the only operator-facing voice: it chooses mode, specialist, write scope, model, and review gate, then dispatches packets. Specialists never talk to the operator directly.

### Specialists (board-spawned, per task)
There are **no persistent per-model lanes**. Each dispatched packet is executed by a **freshly spawned, capability-scoped CLI running in its own git worktree**, and that process exits when the task ends. Model binding is **per specialist, not per lane**: each specialist's runtime-map row names the CLI that runs it and the profile that fixes the exact model, effort, and flags. The CLI is a vehicle, not a lane.

| CLI | Provider | Role in routing |
|---|---|---|
| `codex` | OpenAI | Primary for 12 specialists; the standard cross-family reviewer for Claude-authored work |
| `claude` | Anthropic | Primary for 43 specialists |
| `gemini` | Google | Primary for 14 specialists; grounded research and media routes |
| `kimi` | Moonshot | Deny-by-default as a primary — 4 operator-ratified exceptions; otherwise gated throughput only |

Counts are the current `primary_lane` distribution in `shared/specialist-runtime-map.tsv` (73 rows: claude 43 · gemini 14 · codex 12 · kimi 4). Exact per-specialist model + effort resolve from `shared/registries/profiles.tsv`; see `shared/routing.md` for the routing model. A specialist reads its dispatched packet plus the named specialist markdown, executes in its worktree, and writes its response to the outbox.

### Markdown mailbox (dispatch board)
The dispatch board is the filesystem, not a service:
- `departments/<compatibility_namespace>/inbox/TASK-*.md` — packets Chrono dispatches.
- `departments/<compatibility_namespace>/outbox/TASK-*-response.md` — specialist responses.

Mailbox namespaces are `coding`, `security`, `content`, `sysmgmt`, `research`; `shared` specialists route through one of these mailboxes chosen by Chrono. `source_namespace` selects the specialist markdown; `compatibility_namespace` selects the mailbox folder.

### MCP servers
Each CLI registers its own MCP servers directly — there is no proxy layer:

| CLI | MCP registration |
|---|---|
| claude | `~/.claude/settings.json` (`enabledPlugins`, via the local `chrono` plugin marketplace) |
| codex | `~/.codex/config.toml` |
| kimi | `~/.kimi/mcp.json` |
| gemini | `~/.gemini/settings.json` |

Servers: `chrono-vault` (private, off-repo **markdown source of truth** with a disposable FTS5/BM25 recall index — record/recall/usage plus an Obsidian read/write bridge; it retains `chrono-kg` and `chrono-obsidian` legacy namespace aliases over the same binary for archive-role compatibility. The retired `chrono-catalog` alias and the old in-repo SQLite knowledge graph are gone), `chrono-research-arsenal` (arxiv, xai, perplexity), `chrono-media-studio` (image/video/audio generation), and `chrono-recon` (OSINT). Availability differs per CLI; `shared/api-catalog.md` records the verified state each specialist binds to.

### Optional daemon (secondary)
`daemon/main.py` is an optional observability API with bearer auth except for its public health check: health, read-only task status, summarize, and event-stream routes, plus MCP/catalog support. Its file watcher runs only when this optional daemon runs; the separate failover control plane remains opt-in and dormant. The daemon is **not** started by `bin/launch-squad.sh`, does not expose task/project submission routes, and is **not a dispatch path**. When it is running, status readouts poll `GET /tasks` (`bin/vs-lane-status.sh`) and the weekly review runner posts to `/summarize` (`scripts/python/weekly_review_runner.py`). Markdown packets under `departments/<namespace>/inbox/` remain the only live dispatch spine.

### Persistent Chrome
A long-lived Chrome instance is kept alive outside the squad lifecycle (`bin/chrome-bootstrap.sh`, `bin/browser-keep-alive.sh`) and exposed over the Chrome DevTools Protocol on `:9222`. Lanes that need a browser attach over CDP to this persistent Chrome rather than spawning a fresh profile, reusing your signed-in working browser session rather than losing state. See `shared/lifecycle.md` for browser attach rules.

### Watchers / status
Window 5 hosts the watcher fleet and status readouts: `bin/inbox-watcher.sh` and `bin/outbox-watcher.sh` surface mailbox activity, and `bin/registry-reconciler.sh` settles landed responses against the active-task registry.

## Task lifecycle

1. Operator types a request to Chrono (window 0).
2. Chrono selects mode, specialist(s), write scope, model, and review gate.
3. Chrono writes a task body and calls `scripts/send-task.sh <source-namespace> <body-file> <specialist> [to-model]`.
4. `scripts/send-task.sh` fills packet frontmatter from `shared/specialist-runtime-map.tsv` (review model, safety → `mandatory_review`, source namespace) and hands off to `bin/send-task.sh`.
5. `bin/send-task.sh` runs the safety path (write-scope checks, toolkit injection, dispatch logging), pins a SHA-256 **verification contract** to the packet, atomically writes it to `departments/<compatibility_namespace>/inbox/TASK-*.md`, and hands delivery to a detached `bin/board-supervisor.sh`.
6. The supervisor creates a git worktree for the attempt and spawns a fresh, capability-scoped CLI into it, bound to the specialist's model.
7. The specialist reads the packet + named specialist markdown, executes, and writes its **return artifact first**, then the response envelope at `departments/<compatibility_namespace>/outbox/TASK-*-response.md`.
8. The rail validates the artifact from **outside** the worktree, promotes it, and `bin/registry-reconciler.sh` settles the registry entry.
9. Chrono reads the response, runs any required review, and surfaces the result to the operator.

Dispatch is asynchronous: senders do not block on specialist work (see `shared/protocol.md` § Async Rule). `SQUAD_DISPATCH_MODE` defaults to `board`; the legacy `pane` transport still exists behind that variable but is not the shipped path.

**Admission control at step 5.** `bin/send-task.sh` refuses to launch onto a saturated machine, because a lane that lands on an overloaded host does not fail — it runs slowly and gets killed at the 61-minute cap with no artifact. Defaults: 6 concurrent lanes globally, 2 per model for `claude`/`codex`, 1 for `gemini`/`kimi`. Override with `SEND_TASK_MAX_LANES`, `SEND_TASK_MAX_PER_LANE` (`model=N,model=N`), or bypass with `SEND_TASK_SKIP_CAPACITY=1`. The check **fails open**: an unreadable or corrupt registry admits the dispatch rather than blocking the board.

**Promotion is `return_artifact` only.** Every other `write_scope` path stays in the attempt worktree, and because `_state/**` is gitignored the omission is silent — the file simply never appears where it was expected. `bin/send-task.sh` warns at dispatch time naming the paths that will need a manual sweep. Writing harnesses into a gitignored tree is legitimate; assuming they come back is the defect.

**Terminal receipts carry a failure class.** When a lane ends without a promoted response, `bin/registry-reconciler.sh` settles from `_state/board-dispatch/<task>.<attempt>.receipt.json`. The receipt's `failure_class` (`launch`, `request_validation`, `worktree`, `memory_proof`, `integration`, `launch_canary`, `missing_envelope`, `cancelled`, `other`), `reason` and `returncode` are lifted onto the entry as `terminal_receipt_*` and named in `closure_reason`, so a toolchain gate is distinguishable from a policy denial without opening the receipt JSON.

## Review gates
`mandatory_review: true` is a dispatch-time contract, not auto-firing automation (`shared/protocol.md` § Mandatory Review Behavior). High-safety specialists must carry a `review_model`; same-family reviews run inside the specialist's own attempt before it declares done, and cross-family reviews are dispatched by Chrono as a separate attempt after the response lands. Reviewers are read-only unless Chrono serializes a later write packet.

## Routing & namespaces
Routing is **quality-fit**: Chrono picks the model per specialist by capability, recorded explicitly in `shared/specialist-runtime-map.tsv`. **`source_namespace` is a mailbox/storage label only — it never chooses the model.** Two specialists in the same namespace can run on different CLIs. The TSV is the canonical routing source of truth; `shared/routing.md` is the narrative source of truth; `model-lanes/ROSTER.md` is a generated per-CLI view.

- `source_namespace`: where the specialist markdown + local memory live (coding, content, research, security, sysmgmt, shared).
- `compatibility_namespace`: which mailbox folder a packet lands in (chosen by Chrono for the active workflow).

The map is a **29-column** schema (up from the earlier 8). Each specialist row carries a full routing chain — `primary_lane` + a **cross-family `backup_lane`** (a genuine second-best from a different model family) + an `escalate` profile + a separate `review_lane` — plus `capability_class`, `safety_level`, `tool_profile` (for tool-gated media roles), `operator_gate`, and `operator_model_consult`. Rather than duplicate raw model IDs, each routing slot references a **profile** that resolves in `shared/registries/profiles.tsv` to an exact model + effort + flags; failover/escalation/throughput behaviour are **versioned policy IDs** in `shared/registries/policies.tsv`. **Kimi is deny-by-default as a primary**, with four operator-ratified exceptions declared in `shared/lane-policy.tsv` (`experimental-attacker`, `large-context-analyst`, `summarizer`, `web-builder`); outside those it is a gated throughput lane for bulk/mechanical passes. `bin/validate-specialists.sh` fail-closes on schema, foreign-key, and rule violations (current roster: 73/73 passing).

There are **73 specialists** across the six source namespaces: **coding 20 · content 20 · security 11 · sysmgmt 8 · shared 8 · research 6**. The current `primary_lane` distribution is **claude 43 · gemini 14 · codex 12 · kimi 4**.

## Safety model
Capability is separated from authorization.

- **Global safety-refusal invariant.** A genuine safety refusal on *any* lane surfaces to the operator and is **never cross-family re-dispatched in either direction** — a refused request is never shopped to a more permissive model. Operational failures (overload, lane down, timeout) may fail over; safety refusals may not. Refusals are classified by structured provider/wrapper policy event first, then a typed terminal status, with a content heuristic used only to *downgrade* certainty and surface — never as a positive classifier. A schema-valid response is terminal; a short response is never treated as an operational failure.
- **Operator gates (Hard Rule 6).** A closed enum of actions requires explicit operator approval before execution: `delete · cleanup · credential_change · public_release · paid_media · live_outreach · production_mutation` (`production_mutation` — mutating a live production system that is not itself a public release — was operator-ratified 2026-07-13). A brief's `requires_approval` field is limited to actual harness tool names, so domain approvals cannot hide there.
- **Pre-publication gates.** Two specialists are machine-checkable gates before anything ships: `content-verifier` (fact/citation truth gate, Rule 8) and `asset-provenance-and-rights-auditor` (license/consent/rights gate, Rule 6). Each emits a hash-bound `PASS|HOLD|FAIL` gate record; a non-PASS result or a stale subject hash blocks publication.
- **`safety_level` is a quality floor**, not a complexity detector: `high` (and `heightened_risk`) force the strongest profile, stricter review, and never a throughput downshift.

## Failover control plane (built, cross-family reviewed — opt-in and currently dormant)
The redesign specifies a full resilience layer: per-specialist **cross-family backups**, Claude's native in-lane `--fallback-model` chain, a **conservative-first** auto-failover policy (act only on hard signals — dispatch-ack failure, confirmed process-exit, or a typed provider error — and otherwise surface, never guess), a minimal **attempt ledger** with generation fencing, and a **lease/lock** so the native and Chrono-coordinated paths cannot double-dispatch one packet.

**Honest status (Rule 8):** this control plane is *built and cross-family reviewed but opt-in and currently gated OFF (dormant)*. It ships inert because `_state/**` is ignored and a public checkout has no enable sentinel. Dispatch today is Chrono-coordinated and automatic failover is **not** live. It is documented here as an architecture the operator can explicitly enable, not a feature that runs by default.

## Key files & references

| Path | Purpose |
|---|---|
| `bin/squad`, `bin/launch-squad.sh` | Lifecycle CLI + tmux launcher |
| `scripts/send-task.sh`, `bin/send-task.sh` | Dispatch (frontmatter generation + hardened writer) |
| `bin/board-supervisor.sh` | Per-attempt worktree creation + fresh specialist CLI spawn |
| `bin/registry-reconciler.sh` | Settles landed responses against the active-task registry |
| `shared/protocol.md` | Task-packet frontmatter, lifecycle, review behavior |
| `shared/specialist-runtime-map.tsv` | Canonical routing: 73 rows × 29 columns (primary/backup/escalate/review lanes + profiles, capability_class, safety, operator_gate) |
| `shared/registries/profiles.tsv`, `shared/registries/policies.tsv` | Profile → (model + effort + flags); versioned failover/escalation/throughput policies |
| `shared/routing.md` | Narrative routing source of truth (quality-fit model, safety model, failover) |
| `model-lanes/ROSTER.md` | Generated per-lane roster view |
| `shared/api-catalog.md` | Capability catalog specialists bind to (verified states) |
| `shared/lifecycle.md`, `shared/memory-discipline.md` | Session and pane rules, ephemeral specialist subprocesses, browser attach, memory hygiene |
| `departments/*/specialists/`, `shared/specialists/` | Specialist markdown briefs |
| `departments/*/inbox/`, `departments/*/outbox/` | Dispatch board (packets + responses) |
| `daemon/` | Optional observability API (health/status/summarize/events), support routes, and dormant failover — never a dispatch path |

## Curated design history

Two portfolio design narratives are retained under `docs/design/`: the [2026-07-11 redesign proposal](design/2026-07-11-vibe-squad-redesign-design.md) and the [2026-07-12 lane-panel status design](design/2026-07-12-lane-panel-live-status-design.md). They preserve the decision process and are explicitly historical; this architecture document and the canonical routing/runtime files above describe what ships.

## See also
- Protocol: `shared/protocol.md` (packet schema, lifecycle, review behavior)
- Routing: `shared/specialist-runtime-map.tsv` (canonical) + `model-lanes/ROSTER.md`
- Adding a specialist: `docs/adding-a-specialist.md`
- Lifecycle: `shared/lifecycle.md` (session rules, ephemeral specialist subprocesses, browser attach, memory discipline)

## Planned (not built)

The historical redesign proposed an Ink/React TUI backed by a FastAPI daemon that would supervise PTYs and dispatch work. That application and daemon dispatch spine were not built as the live system. Current dispatch remains the markdown mailbox workflow described above; the optional daemon is limited to observability and support endpoints.
