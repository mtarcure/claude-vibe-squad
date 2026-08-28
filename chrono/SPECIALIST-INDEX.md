# Specialist Index

Status: quick reference for Chrono. The routing source of truth is `shared/specialist-runtime-map.tsv`; the readable model-lead roster is `model-lanes/ROSTER.md`.

## Dispatch Checklist

Every task brief must include:

- `to_model`
- `specialist`
- `source_namespace`
- `write_scope`
- `review_model`
- `mandatory_review`
- `parallel_safe`
- `direct_lane_work_allowed: false` unless explicitly approved and justified

Before dispatch:

- Check the specialist exists in the TSV map.
- Check `to_model` is one of `gpt-codex`, `claude`, `gemini`, or `kimi`.
- Check source namespace is storage only; do not use it to choose a model.
- Check write scopes do not overlap with active tasks.
- Add read-only review for high-safety classes.
- Include relevant MCP/tool requirements and prior-memory check results in the brief.

## Model Lead Roster

See `model-lanes/ROSTER.md`.

## Specialist Files

- Coding namespace: `departments/coding/specialists/*.md`
- Security namespace: `departments/security/specialists/*.md`
- Content namespace: `departments/content/specialists/*.md`
- SysMgmt namespace: `departments/sysmgmt/specialists/*.md`
- Research namespace: `departments/research/specialists/*.md`
- Shared specialists: `shared/specialists/*.md`

## Common Routing

There are exactly **two modes** — `project` and `bounty`. `shared/modes/` holds one file per mode and
nothing else; those two files are the source of truth for mode behaviour. The retired domain modes
(`content`, `research`, `outreach`, `maintenance`, `incident`) are now **`profile_family` values inside
`project`** — a family tunes the default specialists, overlays, and gates but runs the same S0–S7
lifecycle under the same verification contract (`shared/modes/project.md`). Never emit `mode:` with any
value other than `project` or `bounty`: a packet naming a retired mode has no rules behind it and stops
at close as an unsupported profile (`shared/lifecycle.md` rule 14).

| Operator intent | Mode | `profile_family` / flow | Typical specialists |
|---|---|---|---|
| build, implement, refactor | `project` | `engineering` | `architect`, `backend-engineer`, `frontend-engineer`, `test-engineer`, `code-reviewer` |
| bounty, vuln, exploit, report | `bounty` | — | `scout`, `security-analyst`, `threat-modeler`, `exploit-developer`, `impact-validator`, `technical-writer` |
| research, compare, investigate | `project` | `research` | `research`, `data-extraction-engineer`, `large-context-analyst`, `synthesizer`, `skeptic` |
| write, edit, design, media | `project` | `content` | `editor`, `brand-voice`, `technical-writer`; media generation: `image-designer` / `video-director` / `music-composer` |
| cleanup, doctor, routines | `project` | `operations` | `mac-ops`, `agentops`, `harness-optimizer`, `memory-curator`, `knowledge-librarian` |
| urgent broken system | `project` | Incident flow (reactive, 0 capability cards) | `mac-ops`, `systems-engineer`, `security-analyst`, implementation specialist, `technical-writer` |
| unclear request | resolve to `project` or `bounty` | `triage` is a dispatch mechanic, not a mode | `triage`, `summarizer`, `planner` |

`triage` selects *how* an unclear request resolves to a mode, never *what* mode it is; the panel/swarm
dispatch transports were retired — parallel comparison is now independently dispatched single packets
(`shared/routing.md` § 9 Dispatch shape; `shared/modes/project.md` Dispatch Notes). Run triage under the
mode it resolves to.

## Never Do

- Do not dispatch a model lead without a specialist.
- Do not let a model lead become an independent controller.
- Do not use namespace labels as model identity.
- Do not skip approval gates for sends, deletes, credentials, cleanup, or public release.
- Do not mark a mode complete on anything less than a fresh `vibecoding-check` **`OK=0`** (or a
  strictly attested `AUTOFIX=1`) bound to the current artifact/gate hashes. Running the gate is not
  passing it, and a broad `vibecoding: override` cannot turn an `OPERATOR=3` into a pass. The
  contract, the support boundary, and the exact exit tiers live in one place —
  `shared/lifecycle.md` rule 14. Do not restate them here.
