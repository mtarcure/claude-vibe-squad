# Vibe Squad Routing

Chrono is the only controller.

```text
Operator -> Chrono -> gpt-codex | claude | gemini | kimi -> specialists
```

Markdown remains the interface. Chrono writes task packets; model leads execute them; specialists are markdown role files.

## Source Namespace Versus Model Lane

- `source_namespace`: where the specialist markdown and mailbox live.
- `to_model`: which model lead/window executes the task.
- Folder location never determines model choice.

`shared/specialist-runtime-map.tsv` is the routing source of truth.

## Dispatch Contract

Every non-trivial task packet names:

- `to_model`: `gpt-codex | claude | gemini | kimi`
- `specialist`: canonical specialist name
- `source_namespace`: `coding | security | content | sysmgmt | research | shared`
- `write_scope`: exact writable paths, or `[]`
- `review_model`: read-only reviewer lane, or `none`
- `mandatory_review`: `true | false`
- `parallel_safe`: `true | false`
- `direct_lane_work_allowed`: default `false`

## Safety Gates

Dispatch is blocked when:

- specialist is unknown
- specialist is missing from the model map
- `to_model` or `review_model` is invalid
- `to_model` differs from the map without `model_override_reason`
- high-safety specialist lacks mandatory review
- write scopes overlap in-flight work

Explicit operator approval is required for deletes, external sends, credential changes, cleanup, public release changes, live outreach/email, and paid media generation.

## Model Lead Strengths

- `gpt-codex`: implementation, tests, refactors, code review mechanics, PoC mechanics
- `claude`: judgment, security/privacy reasoning, planning, safety, memory/system discipline
- `gemini`: content, design, media, visual/multimodal workflows
- `kimi`: source-heavy research, long-context analysis, extraction, synthesis
