# Vibe Squad Architecture

## Runtime shape

See the full diagram in `docs/superpowers/specs/2026-07-11-vibe-squad-redesign-design.md` §3.1.

High-level:

```
Ink TUI (Node.js React app)
  ├─ Chrono lane (Claude Fable 5 SDK client)
  ├─ Codex lane (subprocess PTY)
  ├─ Gemini lane (subprocess PTY)
  ├─ Claude lane (subprocess PTY)
  └─ Kimi lane (subprocess PTY)
        ↓ HTTP / WebSocket
  Python Sidecar Daemon (FastAPI @ :9876)
        ├─ Task board (inbox/outbox atomic writes)
        ├─ Protocol validation
        ├─ File watcher
        ├─ MCP proxy layer
        ├─ Circuit breaker
        └─ External trigger endpoints
        ↓
  MCP Servers (Python subprocesses)
        ├─ chrono-vault (knowledge graph, memory, vault search)
        ├─ chrono-research-arsenal (arxiv, xai, perplexity search)
        ├─ chrono-content-engineer (ElevenLabs, Higgsfield)
        └─ chrono-recon (OSINT tools)
  Persistent Chrome (CDP :9222)
        └─ launchd-managed, never killed by vibe-squad stop
```

## Components

### Ink app

- Renders the TUI (Ink + Yoga for layout)
- Hosts Chrono as `@anthropic-ai/claude-agent-sdk` client
- Spawns and manages 4 CLI subprocesses via `node-pty`
- Streams model output into panes in real-time
- Posts task dispatch commands to daemon via `POST /task`
- Subscribes to `WS /events` for daemon-side updates (file watch notifications, circuit breaker trips)

**Location:** `ink-app/`

### Python daemon

- Owns the task-board filesystem (`daemon/state/inbox/`, `daemon/state/outbox/`)
- Validates task packets against schema and specialist references
- Watches outbox with `watchfiles` for task completions, emits WebSocket events
- Proxies tool calls: unified `POST /mcp/tool` endpoint routes to backing MCPs
- Implements circuit breaker (loop detection, timeout tracking, error rate)
- Hosts external endpoints (`/task`, `/project`, `/catalog/search`) for Claude Remote + launchd triggers
- Persists across Ink restarts; Claude Remote can submit tasks while Ink is down

**Location:** `daemon/`

**Key entry:** `daemon/main.py`

### Model lanes

Four long-lived PTY subprocesses, one per model:

| Lane | Subprocess | Fresh session | Tools |
|---|---|---|---|
| **Chrono** | N/A (SDK client inside Ink) | Per task | All MCPs via daemon proxy |
| **Claude** | `claude` CLI | Per task via `/newsession` | claude: tools + MCP proxy |
| **Codex** | `openai` CLI or custom | Per task | codex: tools + MCP proxy |
| **Gemini** | `gemini` CLI | Per task | gemini: tools + MCP proxy |
| **Kimi** | `kimi` CLI | Per task | kimi: tools + MCP proxy |

Each lane receives:
1. Fresh session start signal (via PTY input)
2. Specialist markdown file (system prompt)
3. Task packet body
4. Specialist brief (context + instructions)

Lane writes result to outbox with tool-use manifest.

**Location:** `model-lanes/` for startup/init stubs

### Persistent Chrome

- User-data-dir: `~/.chrono/chrome-persistent-profile/`
- Managed by launchd; not affected by `vibe-squad stop`
- Accessed via Chrome DevTools Protocol on `:9222`
- All lanes attach to the same Chrome; no fresh profile spawns
- Preserves 2FA cookies, signed-in tabs, browser history across restarts

**Rationale:** Avoiding fresh Chrome profiles prevents "profile locked" errors and reuses authenticated sessions across tasks. See `shared/lifecycle.md` §11 for full browser attach rules.

### MCP servers

- **chrono-vault**: knowledge graph queries, memory reads, vault search
- **chrono-research-arsenal**: arxiv_search, xai_search, perplexity_search_web
- **chrono-content-engineer**: ElevenLabs + Higgsfield for audio/video/image
- **chrono-recon**: OSINT tools (DNS, certificate lookups, etc.)

Daemon proxies all calls; lanes do not connect directly to MCPs.

## Task lifecycle

### Dispatch flow (§4.1 in design spec)

1. User types request in Chrono pane
2. Chrono reads request, extracts intent
3. Chrono consults `shared/specialist-runtime-map.tsv` → matches specialist(s)
4. For each specialist:
   - Load specialist frontmatter
   - Look up `model_key` in `config/models.yaml`
   - Verify destination lane has all `required_tools` (pre-flight)
   - Construct task packet
5. Ink `POST /task` to daemon with packet
6. Daemon validates + atomically writes to `inbox/{lane}/task-{uuid}.md`
7. Daemon returns 200 with `task_id`
8. Ink sends `/newsession` to lane's PTY, then feeds specialist file + task
9. CLI subprocess loads specialist as system prompt, works on task
10. Lane writes result to `outbox/{lane}/{task_id}.md` with tool-use manifest
11. Daemon's watchfiles fires → daemon emits WS event
12. Ink receives → Chrono ingests
13. Single specialist: Chrono presents result
    Multi-specialist: Chrono synthesizes + surfaces disagreements

### Concurrent tasks

- Priority queue in daemon (`heapq` on task priority + arrival time)
- Idempotent task IDs (UUIDv7 with dedup check)
- Fan-out: one Chrono request → multiple lanes in parallel
- Fan-in: Chrono waits on all outboxes before synthesis
- Backpressure: if a lane is busy, task queues (visible in TUI pending strip)

## Circuit breaker

Prevents runaway loops and stuck tasks.

| Trigger | Threshold | Action |
|---|---|---|
| Same tool call repeated | 5× in 60s | Hard stop, escalate |
| No progress signal | 4 min silence | Soft stop, ask operator |
| Time on single tool call | 3 min | Soft stop |
| Error rate | 3 errors in 5 min | Open circuit, block new dispatches |
| Unauthorized action attempt | 1 | Hard stop, log |

**States** (per lane):
- `closed` — normal operation
- `half-open` — testing recovery after a trip
- `open` — blocking new dispatches, existing tasks allowed to complete

**Recovery:**
- Half-open after 5 min cool-down
- One test dispatch; if successful, close circuit
- If test fails, back to open

## Crash recovery

| Attempt | Action | UX |
|---|---|---|
| 1st crash | Auto-restart CLI + auto-retry task once | Brief `restarting` badge |
| 2nd on same task within 5 min | Escalate, don't retry | Chrono narrates situation, waits |
| 3 crashes on same CLI within 30 min | Open circuit for lane | Chrono offers alternate routing |

## Session management

Two-layer lifecycle:

- **CLI process** = long-lived (spawned on `vibe-squad start`, alive until `stop`)
- **Session inside CLI** = fresh per task (`/newsession` before each dispatch)

Each model lead controls sessions via its CLI:
- Claude Code: `-c` (continue), interactive `/newsession`
- Codex CLI: `resume`, `fork`
- Gemini CLI: `--resume`, `--list-sessions`, `--delete-session`
- Kimi CLI: `--session`, `--continue`

Daemon drives these programmatically through the PTY.

## Specialists

All 56 specialists have structured frontmatter contracts:

```yaml
specialist: security-analyst
version: 2.0
department: security
lane: claude
model_key: hard
required_tools:
  - chrono-vault:kg_query
  - github:pull_request_read
  - context7:query-docs
preferred_tools:
  - grok_reason
  - deepseek_review_diff
safety_level: high
```

- **lane**: best model for this specialist (claude, codex, gemini, kimi)
- **model_key**: key into `config/models.yaml` (default, hard, deep, highspeed, etc.)
- **required_tools**: must be available; task fails pre-flight if unavailable
- **preferred_tools**: nice-to-have; specialist has discretion
- **safety_level**: triggers review rules (see `shared/lifecycle.md`)

Specialist markdown files live under `departments/{namespace}/specialists/` and `shared/specialists/`.

## Routing & namespaces

**Routing principle:** `specialist` → `best_model_lane` (via specialist-runtime-map.tsv), NOT `source_namespace`.

**Namespaces:**
- `source_namespace`: where specialist markdown + local memory live (coding, security, content, research, sysmgmt, content-engineer, shared)
- `compatibility_namespace`: where task packets land in daemon mailbox (same set, chosen by Chrono based on task domain)

Mailbox folders are compatibility rails only. A specialist can live in one source namespace and still route to any model lane.

## MCP proxy

Unified interface for all tool calls:

```bash
curl -X POST http://127.0.0.1:9876/mcp/tool \
  -H "Content-Type: application/json" \
  -d '{
    "mcp_server": "chrono-vault",
    "tool": "kg_query",
    "input": {...}
  }'
```

Daemon routes to the backing MCP based on `mcp_server` + `tool`.

## Startup sequence

```
vibe-squad start
    ↓ [TUI renders IMMEDIATELY with placeholder panes]
    ↓
BLOCKS ON: daemon health check (~1-2s)
IN PARALLEL: Chrome check, 4 CLIs boot
    ↓
Daemon ready → Chrono INTERACTIVE
User can type prompts even if lanes aren't ready
    ↓
As each component reports ready, badge flips: 🔵 starting → ⚪ idle
    ↓
Fully idle in ~6-8s (slowest CLI cold-boot dominates)
```

Header shows per-component status during startup, collapses to project name once all idle.

## Key files & references

| Path | Purpose |
|---|---|
| `shared/specialist-runtime-map.tsv` | Canonical routing: specialist → lane, model_key, review model, tools |
| `config/models.yaml` | Model roster per lane (claude, codex, gemini, kimi, Chrono, summarizer) |
| `shared/protocol.md` | Task packet schema, response manifest schema |
| `shared/lifecycle.md` | Persistent panes, session management, context discipline, browser attach rules |
| `shared/memory-discipline.md` | Memory hygiene, decay rules, three-layer discipline |
| `shared/tool-catalog.md` | All MCP servers, tools, lane availability |
| `departments/*/specialists/` | Specialist markdown files |
| `daemon/state/inbox/` | Task board inbox (written by daemon on dispatch) |
| `daemon/state/outbox/` | Task board outbox (written by lanes on completion) |
| `ink-app/` | Ink TUI source (Node.js + React) |
| `daemon/` | Python FastAPI sidecar (task board, MCP proxy, watchers) |

## See also

- Design spec: `docs/superpowers/specs/2026-07-11-vibe-squad-redesign-design.md` (task lifecycle, frontmatter schema, circuit breaker logic, model selection rationale)
- Protocol: `shared/protocol.md` (task packet YAML schema, response manifest)
- Lifecycle: `shared/lifecycle.md` (14 hard rules for persistent panes, browser attach, memory discipline, mode cleanup)
