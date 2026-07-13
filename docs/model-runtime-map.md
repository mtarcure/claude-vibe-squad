# Model Runtime Map

Status: canonical model-lane runtime map
Owner: Chrono / harness-optimizer

Vibe Squad routes work as:

```text
Operator -> Chrono -> 4 model execution lanes -> specialists
```

Chrono is the only controller. GPT/Codex, Claude, Gemini, and Kimi are execution lanes. The `departments/` tree is compatibility storage for canonical specialist markdown, memory, and mailboxes until it can be safely renamed or retired.

## Canonical Data

The source of truth is `shared/specialist-runtime-map.tsv`.

Columns (exactly **8**, tab-separated, in this order):

1. `specialist`
2. `best_model_lane` — one of `gpt-codex | claude | gemini | kimi`
3. `review_model` — one of `gpt-codex | claude | gemini | kimi | none`
4. `source_namespace` — one of `coding | security | content | content-engineer | sysmgmt | research | shared`
5. `required_tools_mcp_api` — planning intent only. It says what the specialist
   should normally need; it does not prove the live lane currently exposes that
   tool. Live proof comes from `bin/mcp-audit.sh`, lane smoke tests, and the
   task response's `capability_gap`/fallback reporting.
6. `safety_level` — one of `low | medium | high` (`high` requires a non-`none` `review_model`)
7. `preferred_tools` — optional nice-to-have tools (comma-separated); may be empty
8. `notes` — one-line description; must be non-empty

`bin/validate-specialists.sh` rejects any row that does not have exactly 8 tab-separated
fields, and flags rows where `review_model == best_model_lane` (same-family review is not a
cross-family check). Folder location must not be used to infer model choice.

## Model Lanes

| Lane | CLI | Best fit |
|---|---|---|
| `chrono` | Claude Code | operator conversation, planning, dispatch, conflict prevention, synthesis |
| `gpt-codex` | Codex | implementation, repo edits, tests, refactors, PoC mechanics |
| `claude` | Claude Code | judgment, safety review, privacy/auth reasoning, memory hygiene, adversarial challenge |
| `gemini` | Gemini | multimodal analysis, media generation routes, visual/design review, grounded content |
| `kimi` | Kimi | long-context reading, source-heavy scouting, extraction, synthesis |

## Dispatch Algorithm

1. Chrono identifies the operator-approved mode and desired artifact.
2. Chrono selects the canonical specialist.
3. Chrono looks up `best_model_lane`, `review_model`, `source_namespace`, tool requirements, and safety level in `shared/specialist-runtime-map.tsv`.
4. Chrono assigns one write owner for each path in `write_scope`.
5. Chrono adds read-only review when `mandatory_review:true` or when the task class is high risk.
6. The receiving lane executes the specialist brief only; it does not become an independent controller.
7. Chrono gathers results, resolves conflicts, and speaks to the operator.

## Mandatory Review Classes

Mandatory multi-model review is required for:

- security findings and bounty reports
- privacy/PII and data-flow decisions
- auth, credential, or secret-handling changes
- email/outreach sending
- public release changes
- filesystem cleanup or deletion proposals
- high-blast-radius architecture or runtime changes

Reviewers are read-only unless Chrono serializes a later write pass.

## Compatibility Policy

Generated agent config files are allowed only when a target CLI requires them for startup. They must point back to canonical markdown and be validated. Do not maintain duplicate specialist definitions by model family.

## Verification

Current required gates:

- `bash bin/validate-specialists.sh`
- `bash bin/product-hygiene.sh --public-export`
- `bash bin/memory-audit.sh`
- `bash bin/mcp-audit.sh`
- `bash bin/doctor.sh`
- `squad up` topology check for windows: `chrono`, `gpt-codex`, `claude`, `gemini`, `kimi`, `watchers/status`
