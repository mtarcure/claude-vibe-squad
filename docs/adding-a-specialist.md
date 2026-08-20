# Adding a Specialist

A specialist is two things: a **routing row** in `shared/specialist-runtime-map.tsv` and a **markdown brief** under `departments/<namespace>/specialists/` (or `shared/specialists/`). `bin/validate-specialists.sh` checks that the two agree and that a native adapter exists for each CLI the specialist can be routed to. There is no daemon, no `config/models.yaml`, and no pre-flight HTTP call.

## 1. Routing row (source of truth)

`shared/specialist-runtime-map.tsv` is tab-separated with **29 columns**:

```
# specialist	source_namespace	capability_class	safety_level	safety_tags	tool_profile	primary_lane	primary_profile	backup_lane	backup_profile	escalate_lane	escalate_profile	escalation_policy	review_lane	review_profile	anti_affinity	throughput_lane	throughput_profile	throughput_policy	failover_policy	operator_gate	heightened_risk	requires_approval	required_tools	preferred_tools	notes	tags	version	operator_model_consult
```

Add one row (real tabs, not spaces):

```
my-specialist	security	security_reasoning	high	[privacy]	none	claude	claude.fable.xhigh	codex	codex.sol.high	claude	claude.fable.max	escalation.safety_floor.v1	codex	codex.sol.high	none	none	none	throughput.never.v1	failover.conservative.v1	[public_release]	true	[Write, Bash, WebFetch]	[]	[]	One-line description of the role.	[]	1.0	false
```

Column rules (enforced by `bin/validate-specialists.sh`):
- `source_namespace` ∈ `coding | security | content | sysmgmt | research | shared`
- routing lanes use `codex | claude | gemini | kimi`; `primary_lane` may not be `kimi` unless the specialist has an explicit `primary_exception` row in `shared/lane-policy.tsv` (currently three: `experimental-attacker`, `large-context-analyst`, `summarizer`)
- `primary_lane` and `backup_lane` must differ, and every lane/profile pair must resolve through `shared/registries/profiles.tsv`
- `safety_level` ∈ `low | medium | high`
- `high`/`heightened_risk` rows require an independent review, `escalation.safety_floor.v1`, and `throughput.never.v1`
- policy fields must resolve through `shared/registries/policies.tsv`; `tool_profile` must be one of the `vocabulary	tool_profile` values in `shared/lane-policy.tsv` (currently `none`, `media.elevenlabs`, `media.elevenlabs-agent`, `media.higgsfield`)
- `operator_gate`, `requires_approval`, tools, tags, and safety tags use bracketed list syntax (`[]` when empty)
- `notes` must be non-empty and `version` must be present
- `operator_model_consult` ∈ `true | false` — whether operator-model consultation is part of the routed contract. A 28-column legacy row is still accepted and normalized to `false`, but new rows should be written with all 29 fields.

Routing is `specialist → primary_lane`, not `source_namespace → lane`. Each specialist binds its own model, so two specialists in one namespace routinely run on different CLIs. `model-lanes/ROSTER.md` is a generated per-CLI view of this map — regenerate it with `bash bin/gen-roster.sh`, and never hand-edit it.

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
- The brief carries **no** model or lane field. The effective model is resolved per specialist from the TSV row's `*_profile` keys through `shared/registries/profiles.tsv` (model + effort + flags), and the board spawns that CLI for the task. There is no `config/models.yaml`, and no launch-time per-lane model pin.
- `required_tools` / `preferred_tools` are commonly left `[]`. Actual tool availability is declared in the brief body (below) and validated against `shared/api-catalog.md`; it is not enforced by a pre-flight.
- `blind_discovery: true` is optional and omitted by all but a handful of roles. Add it only when the role's job **is** rediscovery, so that prior findings would bias it: the dispatch blind floor (`shared/protocol.md` § The blindness floor) reads this key and forces `memory_aperture: cold` for the role whenever the packet's `target` has a `_blind/` dossier. Later-stage roles on the same target — `skeptic`, `impact-validator`, `technical-writer` — legitimately need prior art and must **not** carry it. The key is the roster: there is no list of blinded roles in code, so marking a brief is the whole change. `bin/validate-specialists.sh` rejects a misspelled key or a non-boolean value, because a brief that merely *looks* marked would leave the role reading freely.

### Required sections

`bin/validate-specialists.sh` fails any brief missing these headings:

- `## Tools available to me` — the MCPs / CLI features you use. Every cited MCP must be a `verified: yes` entry in `shared/api-catalog.md`; the validator rejects unverified names.
- `## When to fan out` — peer specialists you dispatch to (each name must resolve to a real specialist file).
- `## When to escalate`
- `## What I do NOT do`

Also validated: no `<FILL:...>` placeholders remain, and every skill you cite exists in the local skill catalog. Write the rest of the brief (role, approach, acceptance criteria) as direct prose after the frontmatter.

## 3. Native adapters (one per routed CLI)

Every runtime-map specialist needs a thin adapter for each CLI it can be routed to, so native subagent dispatch is honest. The adapter is a pointer to the canonical brief, not a copy — the markdown brief stays the single source of truth. `bin/validate-specialists.sh` checks for the file matching each routed CLI, using the `adapter_template` rows in `shared/lane-policy.tsv`:

| CLI | Adapter path |
|---|---|
| claude | `model-lanes/claude/.claude/agents/<specialist>.md` |
| gpt-codex | `model-lanes/gpt-codex/.codex/agents/<specialist>.toml` (contains `name = "<specialist_with_underscores>"`) |
| gemini | `model-lanes/gemini/.gemini/agents/<specialist>.md` (YAML frontmatter with `name: <specialist>`) |
| kimi | `model-lanes/kimi/.kimi/agents/<specialist>.yaml` (+ an entry in `model-lanes/kimi/main.yaml`) |

Ranked routes need adapters too, not only the primary route. Generate/check the primary, backup, escalation, review, and throughput lanes from the canonical brief and runtime-map row:

```bash
python3 model-lanes/generate-specialist-adapters.py --write <specialist>
python3 model-lanes/generate-specialist-adapters.py <specialist>
```

The first command creates missing adapters and never replaces reviewed adapters. Canonical brief updates take effect through the adapter pointer, so ordinary updates do not require rewriting its lane wrappers. Kimi adapters must also remain registered under `agent.subagents` in `model-lanes/kimi/main.yaml`; the check fails if that registry entry is absent. The runtime map remains the routing source of truth, so this procedure does not make a lane legitimate merely by creating a file.

## 4. Validate

```bash
bash bin/gen-roster.sh
bash bin/gen-roster.sh --check
bash bin/validate-specialists.sh
```

The first command atomically regenerates the readable roster from the TSV; the second is the drift gate and fails with a unified diff if they disagree. Specialist validation then emits one JSON line per file and a `Total / Passed / Failed` summary on stderr, exiting non-zero on any failure. It checks: runtime-map row shape + valid enums, a specialist file exists for each row, the brief has the required sections and no fill placeholders, cited MCPs are `verified: yes` in the api-catalog, cited skills exist, peer/fan-out references resolve, and the adapter is registered for each routed CLI. It then runs the capability-home gate (`scripts/python/validate_capability_homes.py`), which checks the generated adapters against their `capability_source_sha256` provenance stamps.

In a public clone the two stages degrade differently, and the difference decides
how to read the exit code:

- Checks that resolve against `shared/registries/skill-tool-registry.tsv` are
  **skipped, with non-fatal `registry-not-published` warnings**. The private
  registry is deliberately withheld from the public tree, so its absence is the
  export policy working rather than a defect.
- The capability-home gate also reads each specialist's **pre-strip brief from
  the pinned baseline commit** (`baseline_ref` in
  `model-lanes/adapter-capability-policy.json`). That commit is private history
  and is not an ancestor of the public tip, so a public clone does not have the
  object. The gate **exits 2 with a `configuration` error naming the commit**
  instead of reporting a pass it cannot justify: `base-boundary` and
  `migration-parity` exist to prove no pre-strip capability was lost, and with
  no history to compare against there is nothing to prove it from. Treating an
  unreadable baseline as an empty one would make both checks succeed by
  construction.

So the exit code has three states, not two: `0` clean, `1` real diagnostics, `2`
the gate could not run and says which input is missing. Only `1` means the tree
is wrong.

The capability checks that do not read history still run in a public clone:

```bash
python3 scripts/python/validate_capability_homes.py --only existence,source,required,index
```

That subset covers adapter/source sync, routed-lane coverage, primary-lane
requirements, and the generated index. It does **not** cover migration parity —
no public checkout can. The baseline-backed checks and the full registry
cross-checks run on the maintainer checkout, which is also what
`.github/workflows/public-validate.yml` says and why it does not run this gate.

Read the current roster and adapter counts from the validator output; do not copy those mutable totals into
this guide.

## 5. Test dispatch

Send a real packet through the shipped dispatch path (no daemon, no `curl`):

```bash
scripts/send-task.sh <source-namespace> <body-file> my-specialist
```

`scripts/send-task.sh` reads your row from the TSV, maps `primary_lane`/`review_lane` to task-packet model names, generates task frontmatter (`safety_level: high` → `mandatory_review: true`, namespace), and hands off to `bin/send-task.sh`. That writes the packet to `departments/<namespace>/inbox/TASK-*.md`, pins a verification contract to it, and hands delivery to a detached `bin/board-supervisor.sh`, which creates a git worktree and spawns a fresh CLI for your specialist. The response lands at `departments/<namespace>/outbox/TASK-*-response.md` and `bin/registry-reconciler.sh` settles it.

## Safety & review

- `safety_level: high` rows must carry an independent `review_lane`; `bin/send-task.sh` enforces the `mandatory_review` contract at dispatch (see `shared/protocol.md` § Mandatory Review Behavior).
- Review is a contract, not automation: same-family reviews run inside the specialist's own attempt before it declares done; cross-family reviews are dispatched by Chrono as a separate attempt after the response lands. Reviewers are read-only unless Chrono serializes a later write packet.

## See also
- Architecture: `docs/architecture.md`
- Protocol: `shared/protocol.md` (packet schema, lifecycle, review behavior)
- Routing map: `shared/specialist-runtime-map.tsv` (canonical) + `model-lanes/ROSTER.md`
- Capability catalog: `shared/api-catalog.md` (what MCPs/tools a brief may cite)
- Lifecycle & review gates: `shared/lifecycle.md`
