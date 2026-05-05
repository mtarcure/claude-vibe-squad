# Operator Setup

Status: current operating facts for Chrono.

Chrono reads this for operator environment facts only. Chrono's coordinator identity and dispatch behavior live in `chrono/CLAUDE.md`, `chrono/SOUL.md`, `shared/routing.md`, and `shared/protocol.md`.

## Model Leads

| Window | CLI | Auth expectation |
|---|---|---|
| `chrono` | Claude Code | subscription/OAuth |
| `gpt-codex` | Codex | ChatGPT login |
| `claude` | Claude Code | subscription/OAuth |
| `gemini` | Gemini CLI | personal OAuth |
| `kimi` | Kimi CLI | `kimi login` |

Launch rails unset API-key env vars for paid CLIs so subscription auth is preferred. Pay-per-token or external paid provider routes stay opt-in.

## Bounty Browser

The operator keeps Chrome available at `127.0.0.1:9222` for authenticated bounty/platform work. Browser-touching work must attach to that existing CDP session; do not spawn a fresh browser profile.

Configured bounty surfaces:

- HackerOne
- Bugcrowd
- Intigriti
- HackenProof
- Code4rena

Do not assume other platforms are configured unless the operator says so.

## Tooling Rules

- Name required MCPs/tools in the task brief.
- Prefer `chrono-research-arsenal` or model-native grounded search for web research; use single-page fetch only when the task is actually single-page.
- Use `chrono-vault` or local memory checks before repeated research, scouting, bounty discovery, or cleanup decisions.
- Provider access that is not live-verified must be reported as `blocked/auth-pending`, not promised.

## Local Commands

- Launch: `bash bin/launch-squad.sh`
- Stop: `bash bin/squad-stop.sh`
- Status: `bash bin/where-are-we.sh`
- Health: `bash bin/doctor.sh`
- Specialist validation: `bash bin/validate-specialists.sh`
- Public hygiene: `bash bin/product-hygiene.sh --public-export`

Do not ask the operator to hand-edit runtime system files while away. Use dispatch packets, mode gates, and approval requests.

## Routing Reminders

- Chrono dispatches specialists, not departments.
- `to_model` selects the visible model lead.
- `source_namespace` selects specialist markdown and mailbox storage.
- `shared/specialist-runtime-map.tsv` is the routing source of truth.
- `model-lanes/ROSTER.md` is the human-readable roster generated from that map.

## Approval Gates

Ask the operator before live sends, external contact, deletes, credential changes, public release actions, filesystem cleanup, destructive testing, or broad runtime changes.

## Public/Private Boundary

Keep private state out of public git: raw logs, completed mailbox tasks, browser/session state, API keys, OAuth tokens, local vault memory, generated task artifacts, and stale handoffs/specs. Curated examples are allowed only under `examples/`.
