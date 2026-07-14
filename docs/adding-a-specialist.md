# Adding a Specialist

A specialist is two things: a **routing row** in `shared/specialist-runtime-map.tsv` and a **markdown brief** under `departments/<namespace>/specialists/` (or `shared/specialists/`). `bin/validate-specialists.sh` checks that the two agree and that a native lane adapter exists. There is no daemon, no `config/models.yaml`, and no pre-flight HTTP call.

## 1. Routing row (source of truth)

`shared/specialist-runtime-map.tsv` is tab-separated with **28 columns**:

```
# specialist	source_namespace	capability_class	safety_level	safety_tags	tool_profile	primary_lane	primary_profile	backup_lane	backup_profile	escalate_lane	escalate_profile	escalation_policy	review_lane	review_profile	anti_affinity	throughput_lane	throughput_profile	throughput_policy	failover_policy	operator_gate	heightened_risk	requires_approval	required_tools	preferred_tools	notes	tags	version
```

Add one row (real tabs, not spaces):

```
my-specialist	security	security_reasoning	high	[privacy]	none	claude	claude.fable.xhigh	codex	codex.sol.high	claude	claude.fable.max	escalation.safety_floor.v1	codex	codex.sol.high	none	none	none	throughput.never.v1	failover.conservative.v1	[public_release]	true	[Write, Bash, WebFetch]	[]	[]	One-line description of the role.	[]	1.0
```

Column rules (enforced by `bin/validate-specialists.sh`):
- `source_namespace` ∈ `coding | security | content | content-engineer | sysmgmt | research | shared`
- routing lanes use `codex | claude | gemini | kimi`; `primary_lane` may not be `kimi`
- `primary_lane` and `backup_lane` must differ, and every lane/profile pair must resolve through `shared/registries/profiles.tsv`
- `safety_level` ∈ `low | medium | high`
- `high`/`heightened_risk` rows require an independent review, `escalation.safety_floor.v1`, and `throughput.never.v1`
- policy fields must resolve through `shared/registries/policies.tsv`; tool profiles must resolve through `shared/registries/tool-profiles.tsv`
- `operator_gate`, `requires_approval`, tools, tags, and safety tags use bracketed list syntax (`[]` when empty)
- `notes` must be non-empty and `version` must be present

Routing is `specialist → primary_lane`, not `source_namespace → lane`. `model-lanes/ROSTER.md` is a generated per-lane view of this map — regenerate it from the TSV, don't hand-edit.

## 2. Specialist brief

Create the markdown file:

```bash
touch departments/<source_namespace>/specialists/my-specialist.md
# or, for cross-cutting specialists:
touch shared/specialists/my-specialist.md
```

### Frontmatter

Match the shape of the existing briefs:

```yaml
---
specialist: my-specialist
version: 2.0
department: security          # = source_namespace in the TSV
lane: claude
model_key: default
required_tools: []
preferred_tools: []
safety_level: high
requires_approval:
  - Write
  - Bash
  - WebFetch
tags: []
---
```

- `department` must equal the row's `source_namespace`. Runtime assignment comes from `primary_lane`; do not infer it from the brief's folder.
- `model_key` is a nominal label — the effective model is fixed by the lane's launch command in `bin/launch-squad.sh` (e.g. the claude lane runs `claude --model opus`). There is no `config/models.yaml` to resolve it against.
- `required_tools` / `preferred_tools` are commonly left `[]`. Actual tool availability is declared in the brief body (below) and validated against `shared/api-catalog.md`; it is not enforced by a pre-flight.

### Required sections

`bin/validate-specialists.sh` fails any brief missing these headings:

- `## Tools available to me` — the MCPs / CLI features you use. Every cited MCP must be a `verified: yes` entry in `shared/api-catalog.md`; the validator rejects unverified names.
- `## When to fan out` — peer specialists you dispatch to (each name must resolve to a real specialist file).
- `## When to escalate`
- `## What I do NOT do`

Also validated: no `<FILL:...>` placeholders remain, and every skill you cite exists in the local skill catalog. Write the rest of the brief (role, approach, acceptance criteria) as direct prose after the frontmatter.

## 3. Native lane adapter

Every runtime-map specialist needs a thin adapter in its lane so native subagent dispatch is honest. The adapter is a pointer to the canonical brief, not a copy — the markdown brief stays the single source of truth. `bin/validate-specialists.sh` checks for the file matching the lane:

| Lane | Adapter path |
|---|---|
| claude | `model-lanes/claude/.claude/agents/<specialist>.md` |
| gpt-codex | `model-lanes/gpt-codex/.codex/agents/<specialist>.toml` (contains `name = "<specialist_with_underscores>"`) |
| gemini | `model-lanes/gemini/.gemini/agents/<specialist>.md` (YAML frontmatter with `name: <specialist>`) |
| kimi | `model-lanes/kimi/subagents/<specialist>.yaml` (+ an entry in `model-lanes/kimi/main.yaml`) |

## 4. Validate

```bash
bash bin/validate-specialists.sh
```

It emits one JSON line per file and a `Total / Passed / Failed` summary on stderr, exiting non-zero on any failure. It checks: runtime-map row shape + valid enums, a specialist file exists for each row, the brief has the required sections and no fill placeholders, cited MCPs are `verified: yes` in the api-catalog, cited skills exist, peer/fan-out references resolve, and the lane adapter is registered.

## 5. Test dispatch

Send a real packet through the shipped dispatch path (no daemon, no `curl`):

```bash
scripts/send-task.sh <source-namespace> <body-file> my-specialist
```

`scripts/send-task.sh` reads your row from the TSV, maps `primary_lane`/`review_lane` to task-packet model names, generates task frontmatter (`safety_level: high` → `mandatory_review: true`, namespace), and hands off to `bin/send-task.sh`, which writes the packet to `departments/<namespace>/inbox/TASK-*.md` and nudges the lane's tmux window. The lane's response lands at `departments/<namespace>/outbox/TASK-*-response.md`.

## Safety & review

- `safety_level: high` rows must carry an independent `review_lane`; `bin/send-task.sh` enforces the `mandatory_review` contract at dispatch (see `shared/protocol.md` § Mandatory Review Behavior).
- Review is a contract, not automation: same-family reviews run in-lane before the lane declares done; cross-family reviews are dispatched by Chrono after the response lands. Reviewers are read-only unless Chrono serializes a later write packet.

## See also
- Architecture: `docs/architecture.md`
- Protocol: `shared/protocol.md` (packet schema, lifecycle, review behavior)
- Routing map: `shared/specialist-runtime-map.tsv` (canonical) + `model-lanes/ROSTER.md`
- Capability catalog: `shared/api-catalog.md` (what MCPs/tools a brief may cite)
- Lifecycle & review gates: `shared/lifecycle.md`
