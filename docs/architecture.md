# Vibe Squad Architecture

Vibe Squad is a **markdown-first, tmux-hosted** multi-model harness. A coordinator (Chrono) and four model-lane CLIs run as long-lived tmux windows; work moves between them as markdown task packets in per-namespace mailbox folders. There is no TUI app, no PTY supervisor, and no daemon on the dispatch path.

> Historical note: an earlier redesign proposed an Ink (Node/React) TUI backed by a FastAPI daemon as the dispatch spine. That design was **not built** — see "Planned (not built)" at the end. This document describes the system that actually ships.

## Runtime shape

```
tmux session `squad`
  ├─ window 0: chrono      — coordinator, Claude Code (`claude --model opus`) — stays on Opus
  ├─ window 1: gpt-codex   — model lane (`codex` → `gpt-5.6-sol`)
  ├─ window 2: claude      — model lane (`claude` → `claude-fable-5` + `--fallback-model opus,sonnet`)
  ├─ window 3: gemini      — model lane (`gemini` → `gemini-3.5-flash`)
  ├─ window 4: kimi        — model lane (`kimi` → `kimi-k2.7-code`)
  └─ window 5: watchers/status
        │
        │  dispatch = markdown packets on the filesystem
        ▼
  departments/<namespace>/inbox/   ← Chrono writes packets here
  departments/<namespace>/outbox/  ← lanes write responses here
        │
        │  each CLI connects to its own MCP servers (no proxy)
        ▼
  MCP servers (per-CLI registration)
        ├─ chrono-vault (+ chrono-kg / chrono-obsidian legacy namespace aliases)
        ├─ chrono-research-arsenal
        ├─ chrono-content-engineer
        └─ chrono-recon
  Persistent Chrome (CDP :9222) — kept alive outside the squad lifecycle
```

## Entry point & launcher

- `bin/vibe-squad` — thin passthrough to `bin/squad` (backward-compat name).
- `bin/squad` — lifecycle CLI: `up` (default), `stop`, `status`, `doctor`, `attach`, `detach`.
- `bin/launch-squad.sh` — creates the tmux session `squad` (six windows), applies PATH/auth prefixes, and starts each lane's CLI in its `model-lanes/<lane>/` directory. Re-running re-attaches an existing session (idempotent).

`stop` / `status` / `doctor` route to `bin/squad-stop.sh`, `bin/where-are-we.sh`, and `bin/doctor.sh` respectively.

## Components

### Chrono (coordinator)
Window 0 runs Claude Code as `claude --permission-mode bypassPermissions --model opus --effort xhigh`, auto-loading `chrono/CLAUDE.md`. Chrono is the only controller and the only operator-facing voice: it chooses mode, specialist, write scope, model lane, and review gate, then dispatches packets. Model leads never talk to the operator directly.

### Model lanes
Four long-lived CLI windows, one per provider, each started by `bin/launch-squad.sh` in its `model-lanes/<lane>/` working directory (loading that lane's instructions). The four **lead lanes** were bumped to frontier models in the roster/model redesign; the **coordinator (Chrono, window 0) deliberately stayed on `claude --model opus`** — only the four execution lanes changed:

| Window | Lane | CLI | Model (pinned) |
|---|---|---|---|
| 1 | gpt-codex | `codex` | `gpt-5.6-sol` |
| 2 | claude | `claude` | `claude-fable-5` (+ `--fallback-model opus,sonnet`) |
| 3 | gemini | `gemini` | `gemini-3.5-flash` |
| 4 | kimi | `kimi` | `kimi-k2.7-code` (throughput-only lane) |

A lane reads a dispatched packet plus the named specialist markdown, executes, and writes its response to the outbox. Exact per-specialist model + effort resolve from `shared/registries/profiles.tsv`; see `shared/routing.md` for the routing model.

### Markdown mailbox (dispatch board)
The dispatch board is the filesystem, not a service:
- `departments/<compatibility_namespace>/inbox/TASK-*.md` — packets Chrono dispatches.
- `departments/<compatibility_namespace>/outbox/TASK-*-response.md` — lane responses.

Mailbox namespaces are `coding`, `security`, `content`, `sysmgmt`, `research`; `content-engineer` and `shared` specialists route through one of these mailboxes chosen by Chrono. `source_namespace` selects the specialist markdown; `compatibility_namespace` selects the mailbox folder.

### MCP servers
Each CLI registers its own MCP servers directly — there is no proxy layer:

| Lane | MCP registration |
|---|---|
| claude | `~/.claude/settings.json` (`enabledPlugins`, via the local `chrono` plugin marketplace) |
| codex | `~/.codex/config.toml` |
| kimi | `~/.kimi/mcp.json` |
| gemini | `~/.gemini/settings.json` |

Servers: `chrono-vault` (private, off-repo **markdown source of truth** with a disposable FTS5/BM25 recall index — record/recall/usage plus an Obsidian read/write bridge; it retains `chrono-kg` and `chrono-obsidian` legacy namespace aliases over the same binary for archive-role compatibility. The retired `chrono-catalog` alias and the old in-repo SQLite knowledge graph are gone), `chrono-research-arsenal` (arxiv, xai, perplexity), `chrono-content-engineer` (image/video/audio generation), and `chrono-recon` (OSINT). Availability differs per lane; `shared/api-catalog.md` records the verified state each specialist binds to.

### Optional daemon (secondary)
`daemon/main.py` is an optional observability API with bearer auth except for its public health check: health, read-only task status, summarize, and event-stream routes, plus MCP/catalog support. Its file watcher runs only when this optional daemon runs; the separate failover control plane remains opt-in and dormant. The daemon is **not** started by `bin/launch-squad.sh`, does not expose task/project submission routes, and is **not a dispatch path**. When it is running, status readouts poll `GET /tasks` (`bin/vs-lane-status.sh`) and the weekly review runner posts to `/summarize` (`scripts/python/weekly_review_runner.py`). Markdown packets under `departments/<namespace>/inbox/` remain the only live dispatch spine.

### Persistent Chrome
A long-lived Chrome instance is kept alive outside the squad lifecycle (`bin/chrome-bootstrap.sh`, `bin/browser-keep-alive.sh`) and exposed over the Chrome DevTools Protocol on `:9222`. Lanes that need a browser attach over CDP to this authenticated session rather than spawning a fresh profile, preserving signed-in cookies/tabs across restarts. See `shared/lifecycle.md` for browser attach rules.

### Watchers / status
Window 5 hosts lane watchers and status readouts. On dispatch, `bin/send-task.sh` nudges the target lane's tmux window with the absolute packet path (`--nudge-pane squad:<window>`); watchers surface inbox/outbox activity and per-lane status.

## Task lifecycle

1. Operator types a request to Chrono (window 0).
2. Chrono selects mode, specialist(s), write scope, model lane, and review gate.
3. Chrono writes a task body and calls `scripts/send-task.sh <source-namespace> <body-file> <specialist> [to-model]`.
4. `scripts/send-task.sh` fills packet frontmatter from `shared/specialist-runtime-map.tsv` (review model, safety → `mandatory_review`, source namespace) and hands off to `bin/send-task.sh`.
5. `bin/send-task.sh` runs the safety path (auto-snapshot, write-scope checks, toolkit injection, dispatch logging), atomically writes the packet to `departments/<compatibility_namespace>/inbox/TASK-*.md`, and nudges the target lane's window.
6. The lane reads the packet + named specialist markdown, executes, and writes `departments/<compatibility_namespace>/outbox/TASK-*-response.md`.
7. Chrono reads the response, runs any required review, and surfaces the result to the operator.

Dispatch is asynchronous: senders do not block on lane-to-lane work (see `shared/protocol.md` § Async Rule).

## Review gates
`mandatory_review: true` is a dispatch-time contract, not auto-firing automation (`shared/protocol.md` § Mandatory Review Behavior). High-safety specialists must carry a `review_model`; same-family reviews run in-lane before the lane declares done, and cross-family reviews are dispatched by Chrono after the response lands. Reviewers are read-only unless Chrono serializes a later write packet.

## Routing & namespaces
Routing is **quality-fit**: Chrono picks the model per specialist by capability, recorded explicitly in `shared/specialist-runtime-map.tsv`. **`source_namespace` is a mailbox/storage label only — it never chooses the model.** Two specialists in the same namespace can run on different lanes. The TSV is the canonical routing source of truth; `shared/routing.md` is the narrative source of truth; `model-lanes/ROSTER.md` is a generated per-lane view.

- `source_namespace`: where the specialist markdown + local memory live (coding, content, content-engineer, research, security, sysmgmt, shared).
- `compatibility_namespace`: which mailbox folder a packet lands in (chosen by Chrono for the active workflow).

The map is a **28-column** schema (up from the earlier 8). Each specialist row carries a full routing chain — `primary_lane` + a **cross-family `backup_lane`** (a genuine second-best from a different model family) + an `escalate` profile + a separate `review_lane` — plus `capability_class`, `safety_level`, `tool_profile` (for tool-gated media roles), and `operator_gate`. Rather than duplicate raw model IDs, each routing slot references a **profile** that resolves in `shared/registries/profiles.tsv` to an exact model + effort + flags; failover/escalation/throughput behaviour are **versioned policy IDs** in `shared/registries/policies.tsv`. **Kimi is a throughput-only lane and holds zero primary roles** — used only for bulk/mechanical passes under a strict downshift gate. `bin/validate-specialists.sh` fail-closes on schema, foreign-key, and rule violations (current roster: 69/69).

There are **69 specialists** across the seven source namespaces: **coding 19 · content 11 · content-engineer 10 · security 10 · sysmgmt 8 · shared 6 · research 5**.

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
| `shared/protocol.md` | Task-packet frontmatter, lifecycle, review behavior |
| `shared/specialist-runtime-map.tsv` | Canonical routing: 69 rows × 28 columns (primary/backup/escalate/review lanes + profiles, capability_class, safety, operator_gate) |
| `shared/registries/profiles.tsv`, `shared/registries/policies.tsv` | Profile → (model + effort + flags); versioned failover/escalation/throughput policies |
| `shared/routing.md` | Narrative routing source of truth (quality-fit model, safety model, failover) |
| `model-lanes/ROSTER.md` | Generated per-lane roster view |
| `shared/api-catalog.md` | Capability catalog specialists bind to (verified states) |
| `shared/lifecycle.md`, `shared/memory-discipline.md` | Persistent panes, sessions, browser attach, memory hygiene |
| `departments/*/specialists/`, `shared/specialists/` | Specialist markdown briefs |
| `departments/*/inbox/`, `departments/*/outbox/` | Dispatch board (packets + responses) |
| `daemon/` | Optional observability API (health/status/summarize/events), support routes, and dormant failover — never a dispatch path |

## Curated design history

Two portfolio design narratives are retained under `docs/design/`: the [2026-07-11 redesign proposal](design/2026-07-11-vibe-squad-redesign-design.md) and the [2026-07-12 lane-panel status design](design/2026-07-12-lane-panel-live-status-design.md). They preserve the decision process and are explicitly historical; this architecture document and the canonical routing/runtime files above describe what ships.

## See also
- Protocol: `shared/protocol.md` (packet schema, lifecycle, review behavior)
- Routing: `shared/specialist-runtime-map.tsv` (canonical) + `model-lanes/ROSTER.md`
- Adding a specialist: `docs/adding-a-specialist.md`
- Lifecycle: `shared/lifecycle.md` (persistent panes, browser attach, memory discipline)

## Planned (not built)

The historical redesign proposed an Ink/React TUI backed by a FastAPI daemon that would supervise PTYs and dispatch work. That application and daemon dispatch spine were not built as the live system. Current dispatch remains the markdown mailbox workflow described above; the optional daemon is limited to observability and support endpoints.
