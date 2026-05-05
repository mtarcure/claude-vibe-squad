# claude-vibe-squad

Vibe Squad is a local, markdown-first AI command center:

```text
Operator -> Chrono -> 4 model leads -> specialists
```

Chrono is the only controller. GPT/Codex, Claude, Gemini, and Kimi are model leads that execute assigned specialist briefs. Specialist routing comes from `shared/specialist-runtime-map.tsv`; folder location never decides which model works a task.

## Current Shape

- `chrono` plans, scopes, dispatches, prevents file conflicts, gathers results, and speaks to the operator.
- `gpt-codex`, `claude`, `gemini`, and `kimi` are visible tmux windows.
- `departments/` remains only as source namespace storage for specialist markdown, memory, and mailbox compatibility.
- `model-lanes/` contains the short startup instructions for each model lead.
- `shared/modes/` contains operator-consented workflows such as bounty, project, research, content, outreach, incident, maintenance, and triage.
- Runtime state, mailboxes, logs, and private memory stay local unless explicitly curated for public release.

## Quick Start

Prerequisites: macOS, `tmux`, `jq`, Bash, and logged-in CLIs for Claude Code, Codex, Gemini, and Kimi.

```bash
git clone https://github.com/mtarcure/claude-vibe-squad.git
cd claude-vibe-squad
bash bin/doctor.sh
bash bin/launch-squad.sh
tmux attach -t squad
```

The visible windows are:

```text
chrono
gpt-codex
claude
gemini
kimi
watchers/status
```

Talk to Chrono in the `chrono` window. Use `/status` for current state and `/stop` for a clean shutdown.

## Routing

Every dispatched task uses model-lane fields:

```yaml
to_model: gpt-codex | claude | gemini | kimi
specialist: <canonical-specialist>
source_namespace: coding | security | content | sysmgmt | research | shared
write_scope: [...]
review_model: <model-lane | none>
mandatory_review: true | false
parallel_safe: true | false
direct_lane_work_allowed: false
```

`source_namespace` tells the system where the specialist markdown and mailbox live. `to_model` tells the system which visible model lead executes the task.

## Safety Gates

Dispatch blocks unknown specialists, invalid model lanes, missing map entries, overlapping write scopes, unsafe model overrides without a reason, and direct lane work without explicit scope. Deletes, credential changes, external sends, cleanup actions, and public release changes require operator approval.

Mandatory multi-model review applies to security findings, bounty reports, privacy/PII, auth or credential work, email/outreach sending, public release changes, filesystem cleanup, and high-blast-radius architecture.

Outreach and email remain dry-run by default.

## Markdown First

The repo keeps role and workflow behavior in markdown:

- Chrono brain: `chrono/CLAUDE.md`, `chrono/SOUL.md`, `chrono/current.md`
- Model lead prompts: `model-lanes/*/`
- Specialist briefs: `departments/*/specialists/*.md`, `shared/specialists/*.md`
- Modes and profiles: `shared/modes/*.md`, `shared/mode-profiles/**/*.md`
- Protocol and routing: `shared/protocol.md`, `shared/routing.md`

Scripts under `bin/`, `scripts/`, and `shared/*.sh` are rails and validators. They should enforce markdown instructions, not hide routing policy.

## Useful Commands

```bash
bash bin/launch-squad.sh
bash bin/squad-stop.sh
bash bin/where-are-we.sh
bash bin/doctor.sh
bash bin/validate-specialists.sh
bash bin/product-hygiene.sh --public-export
```

`bin/squad` wraps the common commands when installed on your PATH.

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

The public repo must not track API keys, private memories, raw runtime logs, browser/session state, mailbox history, stale handoffs, private local paths, or completed task artifacts.

## License

AGPL-3.0. See `LICENSE`.
