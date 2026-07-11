---
project: vibe-squad-redesign
date: 2026-07-11
status: design-approved
author: chrono + operator
supersedes:
  - Existing Vibe Squad markdown-first + Python task-board architecture
successors: []
tags: [architecture, multi-agent, tui, orchestration, redesign]
---

# Vibe Squad Redesign — Design Specification

## 1. Executive summary

Vibe Squad is being redesigned as a **multi-model relay TUI** with true real-time collaboration across four subscription CLIs (Claude, Codex, Gemini, Kimi), coordinated by Chrono. The redesign eliminates the dead content pipeline (newsletter/podcast/morning-brief), replaces the ad-hoc Python task-board with a FastAPI daemon, wraps everything in an Ink-based TUI, and codifies specialist routing through structured frontmatter contracts.

**Key design decisions:**

- **Runtime:** Ink (Node/React) frontend + Python FastAPI sidecar daemon (Approach C)
- **Orchestrator:** Claude Fable 5, running as SDK client inside the Ink app
- **Lanes:** 4 subscription CLI lanes as long-lived PTY subprocesses with fresh session per task
- **Tools:** Grok 4.5 + DeepSeek V4 exposed as MCP tools rather than lanes
- **Browser state:** Persistent Chrome at :9222 via CDP attach, launchd-managed, 2FA cookies preserved
- **MCP sharing:** Per-CLI registration with the same set (Option 1); shared-state MCPs attach to shared Chrome
- **Specialists:** All 46 existing + 10 new content-engineer = 56 specialists with structured frontmatter contracts
- **Enforcement:** 4-layer stack — frontmatter contract → pre-flight validation → CLI spawn with specialist-as-system-prompt → outbox tool-use manifest → weekly review drift detection
- **Self-improvement:** Lightweight capture + weekly review + reactive patching (no automated extraction)
- **Storage:** ~730MB reclaimed by Phase A cleanup (52% of repo)

**Scope boundaries:**
- v1 uses only tools/keys that already exist (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `MOONSHOT_API_KEY`, `XAI_API_KEY`, `PERPLEXITY_API_KEY`, `BRAVE_API_KEY`, `SERPER_API_KEY`, `APIFY_TOKEN`, `GH_TOKEN`, `OBSIDIAN_REST_API_KEY`, `ELEVENLABS_API_KEY`)
- Deferred to v1.1: paid-tier OSINT (Shodan/Censys/Hunter/HIBP), Ink pane state persistence, cross-shell attach

---

## 2. Motivation & design principles

### 2.1 What's broken today

- **Dead content pipeline still runs nightly:** newsletter → podcast → dream-light → improvement-extractor → TTS pipeline executes at 03:00 UTC every day but produces broken output (kimi expired, ElevenLabs 401, dream-light never ran successfully in production)
- **Python glue is overweight for the actual work:** ~15 shell scripts + ~24 Python scripts orchestrate what could be a single daemon
- **MCP value leak:** ~50 installed MCPs, but only Chrono can reach them. When Chrono dispatches to Codex/Gemini/Kimi, those lanes have zero tool access
- **No real multi-model collaboration:** current system has models reviewing each other's output, not working together. Tmux was a workaround for this limitation
- **Tool sharing broken for stateful tools:** Playwright/Chrome runs in isolated instances per lane, meaning 2FA repeats, no cross-model handoff of browser state
- **Storage bloat:** 1.4GB total, 765MB transcription cache, 201MB tmux-logs, 331MB legacy video project
- **Session context waste:** every task cold-boots a CLI (3-8s each × dispatch density = real UX cost)

### 2.2 Design principles

1. **Markdown-first, code-second** — intelligence lives in `.md` files (specialists, protocol, lifecycle); code is transport
2. **Panels carry state, Chrono carries signal** — visible state in panels, synthesis+decisions from Chrono, no play-by-play narration
3. **You talk to Chrono; models talk through Chrono** — one attention surface, unified voice
4. **Subscription CLIs first, API second** — flat-rate cost model matters; API only where CLI doesn't exist
5. **Explicit contracts, dynamic tools** — frontmatter declares required capabilities; tool discovery is dynamic at inference time
6. **Human-in-loop for specialist evolution** — every specialist upgrade requires operator approval, no automated promotion
7. **Auditability by default** — task-board files, tool-use manifests, weekly reviews all persist to disk
8. **Fail loud but recover fast** — circuit breakers trip on stuck loops; auto-retry once, escalate to operator on repeat

---

## 3. Architecture

### 3.1 Runtime shape

```
┌──────────────────────────────────────────────────────────────┐
│                     Terminal (tmux optional)                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                  vibe-squad (Ink React app)              │  │
│  │                                                          │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐   │  │
│  │  │  Chrono lane │ │  Codex lane  │ │  Kimi lane   │   │  │
│  │  │  (Fable 5    │ │  (subprocess)│ │  (subprocess)│   │  │
│  │  │   SDK client)│ │              │ │              │   │  │
│  │  └──────────────┘ └──────────────┘ └──────────────┘   │  │
│  │  ┌──────────────┐ ┌──────────────┐                    │  │
│  │  │ Gemini lane  │ │ Claude lane  │                    │  │
│  │  │ (subprocess) │ │ (subprocess) │                    │  │
│  │  └──────────────┘ └──────────────┘                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                              ↕                                 │
│                    HTTP / WebSocket                           │
└──────────────────────────────────────────────────────────────┘
              ┌────────────────────────────────┐
              │   Python Sidecar Daemon        │
              │   FastAPI + Uvicorn @ :9876    │
              │   Managed by launchd           │
              │                                │
              │   ├─ Task board (inbox/outbox) │
              │   ├─ Protocol validation       │
              │   ├─ File watcher              │
              │   ├─ MCP proxy layer           │
              │   ├─ External trigger endpoints│
              │   └─ Circuit breaker           │
              └────────────────────────────────┘
                              ↕
              ┌────────────────────────────────┐
              │   MCP Servers (Python)         │
              │   chrono-vault                 │
              │   chrono-research-arsenal      │
              │   chrono-content-engineer      │
              │   chrono-recon (NEW, v1)       │
              └────────────────────────────────┘
                              ↑
              ┌────────────────────────────────┐
              │   External triggers            │
              │   Claude Remote (Tailscale)    │
              │   launchd cron jobs            │
              └────────────────────────────────┘
              ┌────────────────────────────────┐
              │   Persistent Chrome            │
              │   :9222 (CDP)                  │
              │   launchd-managed              │
              │   ~/.chrono/chrome-persistent/ │
              └────────────────────────────────┘
```

### 3.2 Component responsibilities

**Ink app (Node.js):**
- Renders the TUI (React components via Ink + Yoga)
- Hosts Chrono as `@anthropic-ai/claude-agent-sdk` client
- Manages the 4 CLI subprocesses via `node-pty`
- Streams model output into panels
- Sends dispatch commands via `POST /task` to daemon
- Subscribes to `WS /events` for daemon-side updates

**Python sidecar daemon:**
- Owns the task-board filesystem (inbox/outbox atomic writes)
- Validates protocol (frontmatter, specialist references, tool availability)
- Watches outbox with `watchfiles` (Python's chokidar equivalent), emits WS events
- Hosts MCP proxy (unified `POST /mcp/tool` endpoint that routes to backing MCPs)
- Runs circuit breaker logic (loop detection, timeout tracking, error rate)
- Manages external trigger endpoints (`/task`, `/project`, `/catalog/search`)
- Persists across Ink restarts, receives Claude Remote submissions

**Chrome (persistent service):**
- Runs under `~/.chrono/chrome-persistent-profile/` user-data-dir
- Managed by launchd, never touched by `vibe-squad stop`
- Playwright/Chrome-DevTools MCPs in each lane attach via CDP :9222
- 2FA cookies + saved logins persist across restarts

**MCP servers (Python subprocesses):**
- chrono-vault, chrono-research-arsenal, chrono-content-engineer stay Python (already work well)
- New: chrono-recon MCP for OSINT tools
- Managed lifecycle: daemon spawns on startup, respawns on crash

### 3.3 Model roster

Central config at `config/models.yaml`:

```yaml
models:
  chrono: claude-fable-5
  summarizer: gemini-3.5-flash

lanes:
  claude:
    default: claude-sonnet-5
    hard: claude-opus-4-8
  codex:
    default: gpt-5
  gemini:
    default: gemini-3.5-flash
    deep: gemini-3.1-pro-preview
    image: gemini-3-pro-image
  kimi:
    default: kimi-k2.7-code
    highspeed: kimi-k2.7-code-highspeed

tools:
  grok: grok-4.5
  deepseek: deepseek-v4-pro
  deepseek-flash: deepseek-v4-flash
```

Rationale for each pick documented in the Model Selection appendix (§13).

---

## 4. Task lifecycle

### 4.1 Dispatch flow (end-to-end)

```
1. User types request in Chrono pane
2. Chrono (Fable 5) reads request, extracts intent
3. Chrono consults specialist-runtime-map.tsv → matches specialist(s)
4. For each specialist:
   a. Load specialist frontmatter
   b. Look up model_key in models.yaml
   c. Verify destination lane has all required_tools (pre-flight)
   d. Construct task packet
5. Ink POST /task to daemon with packet
6. Daemon validates + atomically writes to inbox/{lane}/task-{uuid}.md
7. Daemon returns 200 with task_id
8. Ink sends `/newsession` to lane's PTY, then feeds specialist file + task
9. CLI subprocess loads specialist as system prompt, works on task
10. Panel shows: badge, tool-use, natural-language "what I'm doing"
11. CLI writes outbox/{lane}/{task_id}.md with result + tools_used manifest
12. Daemon's watchfiles fires → daemon emits WS event
13. Ink receives → Chrono ingests
14. Single specialist: Chrono presents result
    Multi specialist: Chrono synthesizes + surfaces disagreements
```

### 4.2 Task packet schema

```yaml
task_id: t-abc-123-4567
project: fitness-coaches-2026-07-11    # from active project context
specialist: security-analyst
specialist_file: specialists/security-analyst.md
version: 2.0
lane: claude
model: claude-opus-4-8
model_key: hard
required_tools:
  - chrono-vault:kg_query
  - github:pull_request_read
  - context7:query-docs
preferred_tools:
  - grok_reason
  - deepseek_review_diff
requires_approval: [Write, Bash, WebFetch]
prompt: |
  Review PR #47 in {repo} for auth vulnerabilities...
context:
  project_brief: projects/bounties/immunefi-defi-xyz-2026-07-08/brief.md
  related_handoffs: [docs/handoffs/2026-07-10.md]
```

### 4.3 Outbox manifest schema

```yaml
task_id: t-abc-123-4567
completed_at: 2026-07-11T14:32:00Z
duration_seconds: 187
result: |
  Found 3 vulnerabilities: ...
tools_used:
  chrono-vault.kg_query: 2
  github.pull_request_read: 1
  context7.query-docs: 3
  grok_reason: 1
approvals_requested: 0
tokens_used:
  input: 12043
  output: 4287
next_actions:
  - specialist: patch-writer
    reason: "3 vulns need remediation"
```

### 4.4 Session management

**Two-layer lifecycle:**
- CLI process = long-lived (spawned on `vibe-squad start`, alive until `stop`)
- Session inside CLI = fresh per task (`/newsession` before each dispatch)

**Session control per CLI:**
- Claude Code: `-c` (continue), interactive `/newsession`
- Codex CLI: `resume`, `fork`
- Gemini CLI: `--resume`, `--list-sessions`, `--delete-session`
- Kimi CLI: `--session`, `--continue`

Daemon drives these programmatically through the PTY.

### 4.5 Concurrent tasks (fan-out/fan-in)

- Priority queue in daemon (`heapq` on task priority + arrival time)
- Idempotent task IDs (UUIDv7 with dedup check)
- Fan-out: one Chrono request → multiple lanes in parallel
- Fan-in: Chrono waits on all outboxes before synthesis
- Backpressure: if a lane is busy, task queues (visible in TUI pending strip)

### 4.6 Circuit breaker

**States (per lane):**
- `closed` — normal operation
- `half-open` — testing recovery after a trip
- `open` — blocking new dispatches, existing tasks allowed to complete

**Triggers (subscription-CLI appropriate, NOT cost-based):**
| Trigger | Threshold | Action |
|---|---|---|
| Same tool call repeated | 5× in 60s | Hard stop, escalate |
| No progress signal | 4 min silence | Soft stop, ask operator |
| Time on single tool call | 3 min | Soft stop |
| Error rate | 3 errors in 5 min | Open circuit, block new dispatches |
| Unauthorized action attempt | 1 | Hard stop, log |

**Recovery:**
- Half-open after 5 min cool-down
- One test dispatch; if successful, close circuit
- If test fails, back to open

### 4.7 Crash recovery (A+C ladder)

| Attempt | Action | UX |
|---|---|---|
| 1st crash | Auto-restart CLI + auto-retry task once | Brief `restarting` badge |
| 2nd on same task within 5 min | Escalate, don't retry | Chrono narrates situation, waits |
| 3 crashes on same CLI within 30 min | Open circuit for lane | Chrono offers alternate routing |

### 4.8 Startup sequence

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

---

## 5. Specialists

### 5.1 Frontmatter contract

Every specialist file gets structured frontmatter. Body prose stays as-is.

```yaml
---
specialist: security-analyst
version: 2.0
department: security
lane: claude
model_key: hard
required_tools:
  - chrono-vault:kg_query
  - github:pull_request_read
  - context7:query-docs
  - chrono-recon:dns_enumerate
  - chrono-recon:crt_sh_certificates
preferred_tools:
  - grok_reason
  - deepseek_review_diff
  - firecrawl:scrape
safety_level: high_risk
requires_approval: [Write, Bash, WebFetch]
review_by: architect
tags: [security, offensive, defensive]
---

# Security Analyst

[body prose unchanged — this is the model's system prompt when invoked]
```

### 5.2 Enforcement stack (4 layers)

**Layer 1 — Structured contract** (§5.1)
Specialist file itself is the source of truth for its own operation.

**Layer 2 — Chrono pre-flight validation**
Before dispatch:
1. Look up specialist in runtime map
2. Load frontmatter
3. Verify destination lane has every `required_tools`
4. Refuse dispatch if unsatisfied; escalate to operator
5. Log pre-flight into task packet for audit

**Layer 3 — CLI spawn enforcement**
Task packet spawns CLI with:
- `--system-prompt-file specialists/{name}.md` (or per-CLI equivalent)
- MCP config loading only `required_tools + preferred_tools`
- Approval-gated tools wrapped by daemon-side hooks

**Layer 4 — Outbox manifest verification**
Every completed task's outbox includes `tools_used`. Chrono validates:
- ✅ Required tools all used ≥1× (or explicit skip justification)
- ⚠️ Preferred tools not touched → surfaced in weekly review
- 🔴 Tools used outside declared set → flagged

### 5.3 Weekly review (drift detection + evolution)

**Cadence:** Sunday 8am, launchd-triggered.

**Process:**
1. Flash summarizer reads week's:
   - Handoffs from `docs/handoffs/`
   - Tool-use manifests from `outbox/*/`
   - Chrono's reactive patch log
2. Emits `docs/reviews/weekly/YYYY-WW.md` with sections:
   - Surprising moments (synthesis)
   - Underused required tools (drift)
   - Overused preferred tools (candidates for required)
   - Specialist patches accumulated
   - Handoff patterns worth codifying
   - Projects touched this week
3. Operator reviews (~5 min Sunday reading)
4. Operator approves specific promotions; Chrono applies

**No automated promotion.** Every specialist file change is human-approved.

### 5.4 Specialist inventory (v1: 56 total)

**Existing 46 (frontmatter added, prose unchanged):**
All under `departments/*/specialists/` and `shared/specialists/`. See `shared/specialist-runtime-map.tsv` for full listing.

**New 10 content-engineer specialists** (organized by medium):

| Category | Specialist | Primary lane | Primary tools |
|---|---|---|---|
| Writing | `copywriter` | Gemini | firecrawl, copywriting patterns |
| Audio | `voice-narrator` | Gemini | elevenlabs:text_to_speech, voice_clone |
| Audio | `music-composer` | Gemini | elevenlabs:compose_music, video_to_music |
| Audio | `sound-designer` | Gemini | elevenlabs:text_to_sound_effects |
| Video | `video-director` | Gemini | higgsfield:generate_video, motion_control, virality_predictor |
| Video | `video-editor` | Gemini | higgsfield:reframe, upscale_video, outpaint_image |
| Image | `image-designer` | Gemini | higgsfield:generate_image, gemini-3-pro-image |
| Interactive | `web-builder` | Codex | higgsfield:create_website + firebase + figma |
| Interactive | `game-designer` | Codex | higgsfield:deploy_game, publish_game |
| Conversational | `voice-agent-builder` | Claude | elevenlabs:create_agent, knowledge_base |

Each gets a fresh markdown file under `departments/content-engineer/specialists/`.

---

## 6. Tool layer

### 6.1 MCP sharing (Option 1: per-CLI config)

Every CLI is configured with the same MCP set. Same-config-per-CLI is the accepted 2026 pattern per Anthropic and Google guidance.

**Registration mechanism per CLI:**
- Claude Code: `--mcp-config /path/to/mcp-config.json`
- Codex CLI: `codex mcp add ...` writes to `~/.codex/config.toml`
- Gemini CLI: `gemini mcp` subcommand
- Kimi CLI: config file at `~/.kimi/config.toml`

Ink spawns each CLI with a generated mcp-config pointing to the same set.

### 6.2 Shared-state tools (attach to shared services)

| Tool | Shared how |
|---|---|
| Playwright MCP | Connect to Chrome :9222 via CDP |
| Chrome-DevTools MCP | Same CDP endpoint |
| chrono-vault | All CLIs read same filesystem |
| Higgsfield | Shared `workspace_id` in tool calls |
| ElevenLabs voice library | Shared via API-side state |
| Firebase, GitHub, Linear | Stateless API calls, per-CLI instance fine |
| chrono-research-arsenal | Stateless, per-CLI instance |

### 6.3 New `chrono-recon` MCP (v1)

Location: `/Users/user/chrono/plugins/chrono-recon/`
Pattern: same as `chrono-research-arsenal` (Python + FastMCP)

**v1 tools (keyless or existing keys only):**

| Tool | Purpose | Auth |
|---|---|---|
| `dns_enumerate(domain, record_types=None)` | A/MX/NS/TXT + basic subdomain discovery | none |
| `whois_lookup(domain_or_ip)` | Registration + ownership | none |
| `crt_sh_certificates(domain)` | Subdomain discovery via TLS logs | none |
| `wayback_snapshots(url, from_date=None, to_date=None)` | Historical page versions | none |
| `github_leaked_secrets(query, org=None)` | Public GitHub secret hunt | existing `GH_TOKEN` |

**Deferred to v1.1** (require new signups/keys):
- `shodan_search`, `shodan_host` — Shodan free tier
- `censys_search` — Censys free tier
- `hunter_domain_search` — Hunter.io free 25/mo
- `ip_reputation` — AbuseIPDB
- `hibp_check` — HaveIBeenPwned paid

### 6.4 Underused MCPs — integration into specialist required_tools

**Added to specialist required_tools during migration:**

| MCP | Added to |
|---|---|
| firecrawl | researcher, content-triage, all recon-tier |
| cloudflare | web-builder, security-analyst |
| figma | image-designer, web-builder, copywriter |
| frontend-design | web-builder, image-designer |
| coderabbit | code-reviewer (as preferred_tools) |
| security-guidance | security-analyst, pentester |
| huggingface-skills | researcher, image-designer |

**Chrono-only meta-tools (not lane-facing):**
- claude-md-management
- skill-creator
- plugin-dev
- hookify
- session-report

### 6.5 Grok / DeepSeek as tools

Exposed via extension to `chrono-research-arsenal`:

```python
grok_reason(prompt: str, effort: str = "high", context: str = None) -> str
grok_x_search(query: str, sources: list = ["x","web","news"]) -> list
deepseek_analyze(prompt: str, long_context: str) -> str
deepseek_review_diff(diff_text: str) -> dict
```

Any lane can call these as regular MCP tools. No panel commitment.

---

## 7. Project organization

### 7.1 Directory structure

**Top-level:**
```
projects/
├── bounties/
├── lead-gens/
├── websites/
├── content/
├── research/
├── experiments/
└── system/
```

**Per-project structure:** `projects/<category>/<slug>-<YYYY-MM-DD>/`

```
projects/bounties/immunefi-defi-xyz-2026-07-08/
├── brief.md            # request + Chrono's understanding
├── state.yaml          # metadata (indexed by chrono-catalog)
├── research/           # multi-model research outputs
├── drafts/             # in-progress work
├── deliverables/       # final outputs
├── handoffs/           # per-task handoffs within project
└── review.md           # retrospective when project closes
```

### 7.2 `state.yaml` schema

```yaml
project: immunefi-defi-xyz
category: bounties
started: 2026-07-08
last_touched: 2026-07-11
status: active           # active | shipped | paused | archived
tags: [defi, oauth, sql-injection]
participants:
  - chrono
  - claude:security-analyst
  - codex:exploit-developer
  - kimi:researcher
deliverables:
  - deliverables/report.md
  - deliverables/poc/
  - deliverables/screencast.mp4
external_links:
  - https://immunefi.com/bug-bounty/defi-xyz/
budget:
  claude_tokens: 84000
  codex_tokens: 42000
  kimi_tokens: 156000
```

### 7.3 chrono-catalog integration

- MCP watches `projects/*/*/state.yaml`
- Indexes: tags, participants, deliverables, dates, status
- Search tool: `catalog_search(query, filters=None)`
- Enables `catalog search "fitness"` → matches across all categories

---

## 8. External interface

### 8.1 Daemon HTTP/WS API

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness/readiness for Ink boot |
| `/task` | POST | General task dispatch |
| `/tasks` | GET | List queued + running |
| `/tasks/{id}` | GET | Task state |
| `/tasks/{id}/cancel` | POST | Soft cancel |
| `/tasks/{id}/kill` | POST | Hard kill |
| `/projects` | GET | List projects |
| `/projects` | POST | Create project |
| `/projects/{slug}` | GET | Project detail |
| `/projects/{slug}/task` | POST | Task within project context |
| `/catalog/search` | GET | Catalog search proxy |
| `/mcp/{server}/{tool}` | POST | MCP proxy (unified surface) |
| `/summarize` | POST | Flash summarizer proxy |
| `/events` | WS | Real-time event stream |

### 8.2 External triggers

**Claude Remote (mobile):**
- Uses Tailscale or ngrok to reach daemon at Mac mini
- Same `POST /task` endpoint as Ink uses
- Auth: bearer token from operator secrets

**launchd cron jobs:**

| Job | Schedule | Purpose |
|---|---|---|
| `com.vibesquad.daemon.plist` | boot + keepalive | The daemon itself |
| `com.vibesquad.chrome.plist` | boot + keepalive | Persistent Chrome |
| `com.vibesquad.weekly-review.plist` | Sun 08:00 local | Weekly review generation |
| `com.vibesquad.transcription-cache-ttl.plist` | daily 04:00 local | 15-day TTL cleanup |
| `com.vibesquad.nightly-content.plist` | 03:00 UTC daily | Healthy nightly pipeline (feed_sweep, triage, processing, synthesis, cross_day_context, brain_cleanup, morning-brief) |

### 8.3 Nightly pipeline (what stays)

Phases 5-12 of current `run-nightly.sh` remain:
- browser_keep_alive (keeps bounty sessions warm)
- feed_sweep (ingest RSS/YouTube feeds)
- content_triage (categorize new items)
- content_processing (deep-process depth-tier)
- content_synthesis (daily insights)
- cross_day_context (build cross-day context)
- brain_cleanup (memory audit)
- morning-brief (aggregate outputs — delivered via Claude Remote, not Telegram)

Phases 13-17 (newsletter/podcast/dream/improvement/telegram) removed per Phase A.

---

## 9. TUI design

### 9.1 Layout (4-pane grid, normal PC screen)

```
┌──────────────────────────────────────────────────────────────┐
│ vibe-squad │ project: bounty-x │ 4 models ready │ 2:14 PM   │
│ claude 68% weekly │ codex 40% daily │ gemini 22% │ kimi 55% │
├──────────────────────────────────────────────────────────────┤
│                        ● Chrono                               │
│                                                              │
│  you  ▸ research the auth pattern in this bounty            │
│                                                              │
│  chrono                                                      │
│  fanning to kimi (research) + codex (impl patterns).        │
│                                                              │
│  ─── kimi is asking ────────────────────────────────────    │
│  should I check both cookie and header auth paths? y/n      │
│                                                              │
│  ▸ _                                                         │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ ⣾ Codex     │ ⣾ Kimi       │ ⚪ Gemini    │ ⚪ Claude      │
│ 🔧 read     │ 💭 thinking  │ idle         │ idle           │
│ auth_utils  │ auth patterns│              │                │
│ ↳ 12 lines  │ ↳ 340 tokens │              │                │
│ 00:42       │ 01:15        │              │                │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

### 9.2 Status vocabulary

| Badge | State | Meaning |
|---|---|---|
| ⚪ | idle | Ready for dispatch |
| ⣾ | thinking | LLM inference |
| 🔧 | tool: X | Executing tool |
| ⏸ | waiting | Blocked on approval/dependency |
| 🟢 | done | Task complete |
| ⚠️ | error | Needs attention |
| 🔴 | stuck | Circuit breaker signal |
| 🔵 | starting/restarting | Boot or recovery state |

### 9.3 Interaction rules

- You talk to Chrono in natural language
- Model panes are read-only (no direct typing)
- Model→user questions route through Chrono, presented in Chrono's voice
- Minimal slash commands: `/stop`, `/newsession`, `/model` (switches Chrono's own model)
- `Tab`/`Shift-Tab` cycle focus; `Cmd+1..5` jump to pane; `Cmd+M` maximize; `Esc` return to Chrono input

### 9.4 Chrono narration rules

**Chrono speaks when:**
- Routing decision made (once per fan-out)
- Handoff synthesis after fan-out completes
- Question from model needs operator input
- Steering alert (circuit breaker trip, stuck loop)
- Direct conversation with operator

**Chrono does NOT speak:**
- Play-by-play of what panels already show
- "Waiting for X" (spinner shows it)
- "Y finished" (badge shows it)

### 9.5 Handoff visualization

Subtle 1-second arrow animation between panes when task moves lanes (Codex → Chrono for synthesis, Chrono → Kimi + Gemini for fan-out). Visual only, no text noise.

---

## 10. Model configuration

Central `config/models.yaml` (also §3.3), read by daemon at boot. Chrono references model_key strings; upgrading a model is a one-line edit.

Model choices lock as of July 11, 2026. See §13 for rationale and update procedure.

**Environment variable handling:**

Per operator's memory rule (`feedback_claude_headless_max_plan.md`), subscription CLI subprocesses must be spawned with API-key env vars unset to force OAuth path:

```python
env = os.environ.copy()
for key in [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
]:
    env.pop(key, None)
subprocess.Popen(["claude", ...], env=env)
```

---

## 11. Legacy cleanup (Phase A)

### 11.1 Commit sequence

**A.1 — cleanup: remove dead content pipeline** (single commit)
- Delete: `scripts/python/newsletter_tts.py`, `podcast_script.py`, `newsletter_format.py`, `dream_light.py`, `improvement_extractor.py`, `telegram_deliver.py`
- Delete: matching shell wrappers in `bin/`
- Edit `bin/run-nightly.sh` to remove phases 10, 13-17
- **Must land together** to prevent 03:00 UTC cron failure

**A.2 — cleanup: purge tmux-logs**
- `rm -rf _state/tmux-logs/` (-201MB)

**A.3 — cleanup: delete short-survivalist video projects**
- `rm -rf _state/short-survivalist-2026-05-07/`
- `rm -rf _state/short-survivalist-v2-2026-05-07/`
- `rm _state/short-survivalist-*.mp4`
- Total: -331MB

**A.4 — chore: transcription-cache TTL policy**
- Add `bin/transcription-cache-ttl.sh` + Python impl
- Add `com.vibesquad.transcription-cache-ttl.plist`
- 15-day TTL, weekly run

**Verification after A.1:**
- `launchctl start com.claudevibesquad.nightly`
- Check stdout log for missing-script errors
- Confirm morning-brief still generates cleanly

**Reclaimed storage:** ~730MB (52% of current repo)

### 11.2 Rollback

If A.1 breaks something unforeseen: `git revert HEAD` restores scripts + phases; cron resumes previous (broken) behavior. No data loss (script outputs are regenerable).

---

## 12. Build plan (Phase B)

**Sequenced milestones:**

**B.1 — Daemon skeleton**
- `daemon/main.py` FastAPI app with `/health` endpoint
- Uvicorn runner
- launchd plist installed
- Confirm daemon starts, responds, restarts cleanly

**B.2 — Task-board wrapping**
- Import existing `protocol.py` and validators
- Expose `/task`, `/tasks`, `/tasks/{id}` endpoints
- watchfiles-based outbox watcher emitting WS events

**B.3 — MCP proxy layer**
- Unified `/mcp/{server}/{tool}` route
- Wraps existing chrono-vault, chrono-research-arsenal, chrono-content-engineer
- Health checks + respawn logic

**B.4 — Chrome service**
- launchd plist for persistent Chrome
- `~/.chrono/chrome-persistent-profile/` bootstrap
- Playwright CDP attach smoke test

**B.5 — chrono-recon MCP (v1 keyless)**
- Scaffold at `/Users/user/chrono/plugins/chrono-recon/`
- 5 tools: dns_enumerate, whois_lookup, crt_sh_certificates, wayback_snapshots, github_leaked_secrets
- FastMCP stdio protocol
- Register in chrono-recon plugin.json

**B.6 — Ink app scaffold**
- Ink + React + Yoga bootstrap
- 4-pane layout with placeholder content
- Header + status line

**B.7 — PTY management**
- `node-pty` wrapper per lane
- Spawn CLIs with subscription-safe env
- Read stream → panel rendering
- Write stream → dispatch actions

**B.8 — Chrono integration**
- `@anthropic-ai/claude-agent-sdk` client wired to Fable 5
- System prompt loading from `shared/CHRONO-SOUL.md` + specialist context
- MCP registration for Chrono's own use

**B.9 — Specialist frontmatter migration**
- Add frontmatter to all 46 existing specialists
- Update `specialist-runtime-map.tsv` with new models + preferred_tools
- Generate 10 new content-engineer specialist files
- Total: 56 specialists

**B.10 — Enforcement layers**
- Chrono pre-flight validation (Layer 2)
- Daemon spawn enforcement (Layer 3)
- Outbox manifest ingestion (Layer 4)

**B.11 — Weekly review pipeline**
- `bin/weekly-review.sh` orchestration
- Flash summarizer via daemon `/summarize`
- Template output to `docs/reviews/weekly/YYYY-WW.md`
- launchd plist for Sunday 08:00

**B.12 — Project workspace primitives**
- `POST /projects` creates category dir + slug dir + skeleton files
- `state.yaml` schema validation
- chrono-catalog watcher on `projects/*/*/state.yaml`
- `catalog_search` tool

**B.13 — Circuit breaker + crash recovery**
- Loop detector on tool-use manifest
- Timeout tracker per lane
- A+C escalation ladder implementation

**B.14 — End-to-end test**
- One-specialist dispatch through full stack
- Multi-specialist fan-out synthesis
- External trigger via curl to daemon
- Crash injection test

---

## 13. Cutover plan (Phase C)

**C.1 — Bin swap**
- Replace `bin/vibe-squad` shell wrapper with Ink app launcher
- Old wrapper archived to `_archive/pre-redesign-bin/`

**C.2 — Docs rewrite**
- New `README.md` describing redesigned architecture
- New `docs/architecture.md` with runtime diagram
- New `docs/adding-a-specialist.md` guide
- Old docs archived to `_archive/pre-redesign-docs/`

**C.3 — Old task-board archive**
- `_state/inbox/` and `_state/outbox/` archived to `_archive/task-board-2026-05.tar.gz`
- New `daemon/state/` becomes the working task-board location

**C.4 — Git cleanup**
- List old branches with `git branch -a`
- Prune merged/abandoned branches (operator approves each)

**C.5 — Launchd swap**
- Unload old plists
- Load new plists (daemon, Chrome, weekly-review, transcription-TTL, updated nightly-content)
- Verify all jobs report LOADED

**C.6 — Vibe-squad shakedown week**
- Use redesigned system for one full week on real work
- Log issues, fix inline
- After 1 week clean, mark v1 as stable in `docs/architecture.md`

---

## 14. Follow-up backlog (v1.1)

- **chrono-recon paid-tier tools** (Shodan, Censys, Hunter, HIBP)
- **Ink pane state persistence** (`vibe-squad resume` restores prior session's task state)
- **Cross-shell attach** (`vibe-squad attach` from another SSH session)
- **Ink → Terminal owns everything** (deeper Ink integration, no external tmux)
- **Reddit MCP** (community intelligence)
- **HackerOne/Bugcrowd MCPs** (if published)
- **Linear/Sentry deep integration** (if operator adopts)
- **Podcast-producer specialist** (on-demand, not nightly cron)
- **Landing-page-optimizer specialist**
- **Auto-project detection** (Chrono infers project context from cwd)

---

## 15. Open questions & risks

**Known risks:**

1. **Fable 5 pricing shift on July 12** — Anthropic's extension for Max plans ends tomorrow. Post-July-12 terms may reduce Chrono's Fable availability. **Mitigation:** models.yaml fallback chain (Fable → Opus 4.8 → Sonnet 5).

2. **Ink app CLI spawning across environments** — subscription auth via OAuth in subprocess relies on unsetting API-key env vars. If any lane's OAuth token expires mid-session, it silently degrades.  **Mitigation:** daemon health-checks each CLI's auth state at boot; surfaces expired-auth in status line.

3. **Persistent Chrome profile corruption** — Chrome profiles can rarely corrupt on unclean shutdowns. **Mitigation:** `vibe-squad chrome reset` archives the current profile before starting fresh; documented recovery procedure.

4. **MCP config drift across CLIs** — Option 1 duplicates config across 4 CLIs. If one drifts, only that lane loses a tool. **Mitigation:** Ink generates all 4 configs from a single source, regenerates on `vibe-squad start`.

5. **Fable's safety layer blocking legitimate coordination** — if Fable refuses to route a security task because the prompt mentions offensive terms, coordination breaks. **Mitigation:** Chrono's dispatch prompt is generic ("route to security-analyst specialist"); details go to the specialist, not to Fable's system prompt.

6. **Weekly review noise from lightweight tasks** — many short tasks may drown out important patterns. **Mitigation:** Flash summarizer weighted by task duration/impact, not raw count.

**Open questions (deferred, not blocking v1 build):**

- Does chrono-catalog scale to 100+ projects? (Currently untested at that size)
- Should `game-designer` specialist route to Codex or Gemini? (Depends on Codex's game-building performance in practice)
- Do we need per-project rate-limit caps to prevent one long-running project from consuming the weekly Claude cap?

---

## Appendix — Approved model selection rationale (July 11, 2026)

- **Chrono = `claude-fable-5`** — Anthropic's orchestration-tuned Mythos-class model. Adaptive thinking, safety layer enforces coordinator role boundary (won't do offensive work directly, only routes). 1M context, 128K output.
- **Summarizer = `gemini-3.5-flash`** — beats Gemini 3.1 Pro on agentic benchmarks (Finance Agent v2, MCP Atlas, Terminal-Bench). 4× faster, 25% cheaper. Structured output.
- **Claude lane default = `claude-sonnet-5`** — new frontier default, replaces Sonnet 4.6.
- **Claude lane hard = `claude-opus-4-8`** — practical reasoning ceiling (Opus 5 suspended under export controls).
- **Codex lane = `gpt-5`** — Sol/Cyber variants gated to Daybreak Trusted Access, not available to operator.
- **Gemini lane deep = `gemini-3.1-pro-preview`** — reasoning-heavy design work.
- **Gemini lane image = `gemini-3-pro-image`** — image generation.
- **Kimi lane = `kimi-k2.7-code`** — best open coding model, 256K context, MCP Mark leader (81.1%).
- **Grok tool = `grok-4.5`** — peer-frontier reasoning for cross-model second opinions.
- **DeepSeek tool = `deepseek-v4-pro`** — long-context (1M) analysis, huge-diff review.

**Update procedure when a new model ships:**
1. Verify availability via API probe (`curl .../v1/models`)
2. Edit `config/models.yaml` (one line per swap)
3. If model has substantially different capabilities (new modalities, safety layer changes), review affected specialist frontmatters
4. Restart daemon; new model loads on next dispatch

---

*End of design specification.*
