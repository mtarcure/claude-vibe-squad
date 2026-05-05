<div align="center">

![Vibe Squad command center](assets/hero/vibe-squad-hero.svg)

# claude-vibe-squad

**A local multi-model AI command center. Chrono coordinates the work, then routes scoped specialist briefs to OpenAI GPT/Codex, Claude, Gemini, or Kimi through persistent terminal lanes. Markdown-first, mailbox-driven, subscription-auth friendly, and built for real daily use.**

`v1` · `Chrono Controller` · `4 Model Leads` · `46 Specialists` · `Markdown-First` · `Filesystem Mailbox` · `Multi-Model Review` · `AGPL-3.0`

</div>

---

## v1 Daily-Driver Release

Vibe Squad is built around one simple shape:

```text
Operator -> Chrono -> 4 model leads -> specialists
```

Chrono is the only controller. The model leads do not own departments, modes, or whole areas of the repo. They execute assigned specialist briefs, write back to the mailbox, and wait for the next scoped task.

The current release is focused on public-ready local operation:

- **Chrono-only control plane** - Chrono chooses the mode, specialist, model lead, write scope, review gate, and final operator response.
- **Canonical specialist routing** - `shared/specialist-runtime-map.tsv` maps every specialist to `best_model_lane`, `review_model`, `source_namespace`, required tools, and safety level.
- **Professional terminal dashboard** - `squad up` starts Chrono plus four visible model leads, with a live status sidebar for active specialist, queue count, last result, and blocked state.
- **Safety-first dispatch** - unknown specialists, invalid model leads, missing map entries, overlapping write scopes, unsafe overrides, and unreviewed high-risk work are blocked.
- **Public-release hygiene** - scripts validate shell/Python syntax, specialist coverage, runtime/private artifact exclusion, MCP/API inventory, memory boundaries, and stale architecture language.
- **Approval-gated risk** - outreach/email stays dry-run by default; deletes, credential changes, cleanup actions, external sends, and public release changes require explicit operator approval.

Reference docs:

- [Operator setup](./chrono/operator-setup.md) - what the operator needs to run the squad
- [Brain map](./docs/brain-map.md) - source-of-truth layers and naming
- [Model runtime map](./docs/model-runtime-map.md) - model lead behavior and review rules
- [State model](./docs/state-model.md) - live truth order and runtime/private boundaries
- [Production readiness](./docs/production-readiness.md) - release checklist
- [Protocol](./shared/protocol.md) - task packet and mailbox contract

## What It Gives You

Each bullet leads with what you get in plain terms. The implementation detail follows for the curious.

- **One conversation while the squad works in the background** - You talk to Chrono. Chrono scopes the task, chooses the specialist, chooses the model lead, sends the packet, watches for the result, and explains the outcome. *Implementation: markdown task packets land in namespace mailboxes and watcher rails nudge the correct tmux model lane.*

- **Four model leads with clean responsibilities** - OpenAI GPT/Codex handles implementation-heavy work, Claude handles judgment and safety-heavy work, Gemini handles media and grounding-heavy work, and Kimi handles long-context/source-heavy work. No folder decides routing. *Implementation: `shared/specialist-runtime-map.tsv` is the canonical map; source namespaces store specialist markdown and local memory; compatibility namespaces carry mailbox packets.*

- **Forty-six specialists without dumping every prompt into every context window** - Chrono loads the relevant mode and dispatch packet. The model lead receives the assigned specialist brief and scoped task, not the entire system history. *Implementation: specialist markdown lives under `departments/*/specialists/` and `shared/specialists/`; lanes load short `model-lanes/*/` instructions.*

- **Markdown-first behavior you can audit** - Modes, specialist roles, Chrono brain files, routing docs, task packets, responses, morning briefs, and memory notes are readable markdown. The shell and Python files are rails and validators, not hidden strategy. *Implementation: `chrono/`, `shared/`, `model-lanes/`, and `departments/*/specialists/` hold the operational instructions.*

- **Persistent terminal sessions** - Chrono, GPT/Codex, Claude, Gemini, Kimi, and watchers live in one named tmux session. Detach, travel, come back, and the system is still there. *Implementation: `bin/launch-squad.sh` creates the `squad` session, enables scrollback/mouse/copy support, starts each CLI, and opens the live model dashboard.*

- **High-risk work gets another model family** - Security findings, bounty reports, privacy/PII, auth/credential work, email/outreach sending, public release, filesystem cleanup, and high-blast-radius architecture require review. *Implementation: task packets carry `review_model` and `mandatory_review`; reviewers are read-only unless Chrono serializes a later write pass.*

- **Bounty, project, research, content, outreach, incident, maintenance, routines, and release workflows stay preserved** - Modes engage only after operator consent. URL pasted? Chrono can suggest a mode, but it waits for approval before switching into it. *Implementation: mode docs live in `shared/modes/` with target profiles in `shared/mode-profiles/`.*

- **Subscription auth by default** - The launcher unsets common API-key env vars inside panes so provider CLIs fall back to their normal login/OAuth/subscription path where supported. *Implementation: `bin/launch-squad.sh` applies the auth prefix before starting Claude Code, Codex, Gemini, and Kimi.*

## Architecture

![Vibe Squad architecture](assets/hero/architecture-lanes.svg)

Chrono coordinates. Model leads execute. Specialists define the work shape.

| Layer | What it does | Source of truth |
|---|---|---|
| Operator | Gives intent, approves risk, receives final synthesis | this terminal conversation |
| Chrono | Plans, scopes, routes, conflict-checks, reviews, reports | `chrono/CLAUDE.md`, `chrono/SOUL.md`, `chrono/current.md` |
| Model leads | Run assigned specialist briefs in their provider CLI | `model-lanes/gpt-codex/`, `model-lanes/claude/`, `model-lanes/gemini/`, `model-lanes/kimi/` |
| Specialists | Encode role-specific work patterns and acceptance criteria | `departments/*/specialists/*.md`, `shared/specialists/*.md` |
| Source namespaces | Store specialist markdown and local memory; they never choose the model lead | `departments/coding`, `security`, `content`, `sysmgmt`, `research` |

Mailbox folders are compatibility rails. A specialist can live in one source namespace and still run on any model lead selected by the specialist runtime map.

Model lead fit is specialist-by-specialist:

| Model lead | Typical fit | Examples |
|---|---|---|
| **OpenAI GPT/Codex** | code edits, tests, refactors, PoC mechanics, implementation review | `backend-engineer`, `frontend-engineer`, `exploit-developer`, `test-engineer` |
| **Claude** | safety, judgment, architecture, privacy, memory, operator-sensitive work | `security-analyst`, `impact-validator`, `memory-curator`, `planner` |
| **Gemini** | visual/media work, content production, brand voice, multimodal review | `media-producer`, `designer`, `content-creator`, `brand-voice` |
| **Kimi** | source-heavy scouting, long-context reading, extraction, synthesis | `scout`, `research`, `large-context-analyst`, `summarizer` |

The mapping is intentionally honest: Claude does have many high-safety specialists because the current system uses it for review and operator-sensitive judgment. That is a routing decision, not a department ownership claim.

## Mailbox Dispatch

![Vibe Squad mailbox flow](assets/hero/mailbox-flow.svg)

Every dispatched task uses model-lead fields:

```yaml
to_model: gpt-codex | claude | gemini | kimi
specialist: <canonical-specialist>
source_namespace: coding | security | content | sysmgmt | research | shared
compatibility_namespace: coding | security | content | sysmgmt | research
write_scope: [...]
review_model: <model-lead | none>
mandatory_review: true | false
parallel_safe: true | false
direct_lane_work_allowed: false
```

`source_namespace` selects specialist markdown/source storage. `compatibility_namespace` selects the mailbox folder that carries the task packet. `to_model` selects the visible model lead that executes the work. None of these folder labels chooses the model.

Task lifecycle:

```text
Chrono writes TASK-<id>.md
  -> compatibility namespace inbox
  -> model lead moves it to active
  -> model lead executes specialist brief
  -> response lands in outbox
  -> Chrono reviews, synthesizes, and reports back
```

## Multi-Model Review

![Vibe Squad review loop](assets/hero/review-loop.svg)

Mandatory review applies to:

- security findings and bounty reports
- privacy, PII, auth, and credential work
- email/outreach sending
- public release changes
- filesystem cleanup and deletes
- high-blast-radius architecture changes

Reviewers are read-only by default. If a reviewer finds a required fix, Chrono creates a later serialized write pass with an explicit write scope.

## Quick Start

Prerequisites: macOS, `tmux`, `jq`, `fswatch`, Bash, and logged-in CLIs for Claude Code, Codex, Gemini, and Kimi.

```bash
git clone https://github.com/mtarcure/claude-vibe-squad.git
cd claude-vibe-squad
bash bin/doctor.sh
bash bin/launch-squad.sh        # auto/yolo model-lane profile
tmux attach -t squad
```

You land in the `chrono` window. Talk to Chrono on the left; the right sidebar shows live model lead status.

Visible windows:

```text
0 chrono
1 gpt-codex
2 claude
3 gemini
4 kimi
5 watchers/status
```

Useful commands:

```bash
bash bin/launch-squad.sh
bash bin/squad-stop.sh
bash bin/where-are-we.sh
bash bin/doctor.sh
bash bin/validate-specialists.sh
bash bin/product-hygiene.sh --public-export
```

If `bin/squad` is installed on your PATH, `squad up`, `squad stop`, `squad status`, and `squad doctor` wrap the common commands. Use `squad up --safe` when you want the conservative approval profile.

## Modes

Modes are operator-consented workflows. They do not auto-fire on vague phrase matches.

| Mode | What it is for |
|---|---|
| `bounty` | target scouting, testing, exploit mechanics, impact validation, report prep |
| `project` | software project planning, implementation, testing, release prep |
| `research` | source-heavy investigation, extraction, citations, synthesis |
| `content` | writing, editing, brand, design, media generation routes |
| `outreach` | lead research, qualification, drafts, approval-gated send prep |
| `incident` | urgent local/system/product issue triage |
| `maintenance` | repo hygiene, memory hygiene, doctor/audit cleanup |
| `triage` | unclear requests that need classification before execution |

Mode instructions live in `shared/modes/*.md`. Target profiles live in `shared/mode-profiles/`.

## Terminal Experience

`squad up` creates a terminal command center:

- Chrono stays in the main left pane.
- The right sidebar is one live dashboard pane with four model lead cards.
- The Chrono pane border shows a colored state badge: healthy, queued, active, warning, or blocked.
- Mouse scrolling and large scrollback are enabled.
- tmux copy-mode can pipe selections to the macOS clipboard.
- Pane titles and borders show the Chrono/model-lane split clearly.

The model lead panes are still available as full CLI windows. The dashboard is a status surface, not a replacement for the model CLIs.

## Repo Shape

The repo is intentionally markdown-first:

```text
chrono/                  Chrono brain, state, operator setup
model-lanes/             short startup instructions for each model lead
departments/*/           source namespace storage, local memory, compatibility mailboxes
shared/modes/            operator-consented workflows
shared/specialists/      cross-cutting specialists
shared/*.md              routing, protocol, lifecycle, API inventory
bin/                     public commands and mechanical rails
scripts/                 validators, audits, routines, Python helpers
assets/hero/             public README visuals
```

Runtime state, private memory, raw logs, browser/session state, mailbox history, and completed task artifacts are excluded from public release unless explicitly curated.

## Public Release Gates

Before publishing:

```bash
bash -n bin/*.sh scripts/*.sh shared/*.sh
python3 -m py_compile scripts/python/*.py bin/*.py
bash bin/validate-specialists.sh
bash bin/product-hygiene.sh --public-export
bash bin/memory-audit.sh
bash bin/mcp-audit.sh
bash bin/doctor.sh
```

The public repo must not track API keys, credentials, private memories, raw runtime logs, browser/session state, runtime mailboxes, completed handoffs, stale specs, private local paths, or generated private artifacts.

## License

AGPL-3.0. See [LICENSE](./LICENSE).
