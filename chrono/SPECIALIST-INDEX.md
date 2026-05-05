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

| Operator intent | Typical mode | Typical specialists |
|---|---|---|
| build, implement, refactor | project | `architect`, `backend-engineer`, `frontend-engineer`, `test-engineer`, `code-reviewer` |
| bounty, vuln, exploit, report | bounty | `scout`, `security-analyst`, `threat-modeler`, `exploit-developer`, `impact-validator`, `technical-writer` |
| research, compare, investigate | research | `research`, `data-extraction-engineer`, `large-context-analyst`, `synthesizer`, `skeptic` |
| write, edit, design, media | content | `editor`, `brand-voice`, `content-creator`, `designer`, `media-producer`, `technical-writer` |
| cleanup, doctor, routines | maintenance | `mac-ops`, `agentops`, `harness-optimizer`, `memory-curator`, `knowledge-librarian` |
| urgent broken system | incident | `mac-ops`, `systems-engineer`, `security-analyst`, implementation specialist, `technical-writer` |
| unclear request | triage | `triage`, `summarizer`, `planner` |

## Never Do

- Do not dispatch a model lead without a specialist.
- Do not let a model lead become an independent controller.
- Do not use namespace labels as model identity.
- Do not skip approval gates for sends, deletes, credentials, cleanup, or public release.
- Do not mark a mode complete before `vibecoding-check`.
