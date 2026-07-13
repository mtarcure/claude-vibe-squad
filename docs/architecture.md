# Vibe Squad Architecture

Vibe Squad is a **markdown-first, tmux-hosted** multi-model harness. A coordinator (Chrono) and four model-lane CLIs run as long-lived tmux windows; work moves between them as markdown task packets in per-namespace mailbox folders. There is no TUI app, no PTY supervisor, and no daemon on the dispatch path.

> Historical note: an earlier redesign proposed an Ink (Node/React) TUI backed by a FastAPI daemon as the dispatch spine. That design was **not built** — see "Planned (not built)" at the end. This document describes the system that actually ships.

## Runtime shape

```
tmux session `squad`
  ├─ window 0: chrono      — coordinator, Claude Code (`claude --model opus`)
  ├─ window 1: gpt-codex   — model lane (`codex` CLI)
  ├─ window 2: claude      — model lane (`claude` CLI)
  ├─ window 3: gemini      — model lane (`gemini` CLI)
  ├─ window 4: kimi        — model lane (`kimi` CLI)
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
        ├─ chrono-vault (+ chrono-kg / chrono-obsidian / chrono-catalog namespaces)
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
Four long-lived CLI windows, one per provider, each started by `bin/launch-squad.sh` in its `model-lanes/<lane>/` working directory (loading that lane's instructions):

| Window | Lane | CLI |
|---|---|---|
| 1 | gpt-codex | `codex` |
| 2 | claude | `claude` |
| 3 | gemini | `gemini` (content lane, `gemini-3.1-pro-preview`) |
| 4 | kimi | `kimi` |

A lane reads a dispatched packet plus the named specialist markdown, executes, and writes its response to the outbox.

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

Servers: `chrono-vault` (knowledge graph, memory, vault search — also exposes `chrono-kg`, `chrono-obsidian`, `chrono-catalog` namespaces), `chrono-research-arsenal` (arxiv, xai, perplexity), `chrono-content-engineer` (image/video/audio generation), and `chrono-recon` (OSINT). Availability differs per lane; `shared/api-catalog.md` records the verified state each specialist binds to.

### Optional daemon (secondary)
`daemon/main.py` is an optional FastAPI service ("vibe-squad daemon", v0.1.0) exposing routers for health, task, mcp, events, summarize, project, and catalog, plus a file watcher and bearer-token auth. It is **not** started by `bin/launch-squad.sh` and is **not** on the dispatch path. Auxiliary tooling uses it when it is running: status readouts poll `GET /tasks` (`bin/vs-lane-status.sh`), the weekly review runner posts to `/summarize` (`scripts/python/weekly_review_runner.py`), and remote/scheduled submission uses its trigger endpoints. The markdown mailbox — not the daemon — is the dispatch spine.

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
Routing is `specialist → best_model_lane` via `shared/specialist-runtime-map.tsv`, **not** `source_namespace → lane`. The TSV is the canonical routing source of truth; `model-lanes/ROSTER.md` is a generated per-lane view.

- `source_namespace`: where the specialist markdown + local memory live (coding, content, content-engineer, research, security, sysmgmt, shared).
- `compatibility_namespace`: which mailbox folder a packet lands in (chosen by Chrono for the active workflow).

There are **53 specialists** across the seven source namespaces (coding 14, content-engineer 10, sysmgmt 8, security 6, shared 6, research 5, content 4).

## Key files & references

| Path | Purpose |
|---|---|
| `bin/squad`, `bin/launch-squad.sh` | Lifecycle CLI + tmux launcher |
| `scripts/send-task.sh`, `bin/send-task.sh` | Dispatch (frontmatter generation + hardened writer) |
| `shared/protocol.md` | Task-packet frontmatter, lifecycle, review behavior |
| `shared/specialist-runtime-map.tsv` | Canonical routing: specialist → lane, review model, namespace, tools |
| `model-lanes/ROSTER.md` | Generated per-lane roster view |
| `shared/api-catalog.md` | Capability catalog specialists bind to (verified states) |
| `shared/lifecycle.md`, `shared/memory-discipline.md` | Persistent panes, sessions, browser attach, memory hygiene |
| `departments/*/specialists/`, `shared/specialists/` | Specialist markdown briefs |
| `departments/*/inbox/`, `departments/*/outbox/` | Dispatch board (packets + responses) |
| `daemon/` | Optional FastAPI service (status, summarize, triggers) — not on the dispatch path |

## Planned (not built)

`docs/superpowers/specs/2026-07-11-vibe-squad-redesign-design.md` proposed a redesign that was **not** implemented. None of the following ships today; they are recorded here only so older references resolve:

- **Ink TUI** (`ink-app/`, Node.js + React + Yoga) hosting Chrono as an `@anthropic-ai/claude-agent-sdk` client and spawning lanes as `node-pty` subprocesses, streaming output into panes. *Not built* — the runtime is tmux windows running each CLI directly; `ink-app/` does not exist.
- **FastAPI daemon as the dispatch spine** — `POST /task` dispatch, `daemon/state/inbox|outbox/` as the task board, `WS /events`, an **MCP proxy** at `/mcp/tool`, and a circuit breaker. *Not built as the spine* — dispatch is the markdown mailbox under `departments/*/`; the daemon that exists (`daemon/`) is optional/secondary, and MCPs are registered per-CLI, not proxied.
- **`config/models.yaml`** — a model roster keyed by `model_key`. *Does not exist* — model selection is the `best_model_lane` column in the TSV plus each lane's launch command in `bin/launch-squad.sh`.

## See also
- Protocol: `shared/protocol.md` (packet schema, lifecycle, review behavior)
- Routing: `shared/specialist-runtime-map.tsv` (canonical) + `model-lanes/ROSTER.md`
- Adding a specialist: `docs/adding-a-specialist.md`
- Lifecycle: `shared/lifecycle.md` (persistent panes, browser attach, memory discipline)
