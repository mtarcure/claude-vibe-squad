# Model Runtime Map

Status: canonical model-lane runtime map
Owner: Chrono / harness-optimizer

Vibe Squad routes work as:

```text
Operator -> Chrono -> 4 model execution lanes -> specialists
```

Chrono is the only controller. GPT/Codex, Claude, Gemini, and Kimi are execution lanes. The `departments/` tree is compatibility storage for canonical specialist markdown, memory, and mailboxes until it can be safely renamed or retired.

## Canonical Data

The source of truth is `shared/specialist-runtime-map.tsv`: **69 specialist rows with exactly 28 tab-separated fields**. The columns, in order, are:

1. `specialist` — unique canonical specialist name.
2. `source_namespace` — one of `coding | security | content | content-engineer | sysmgmt | research | shared`; storage/mailbox compatibility only.
3. `capability_class` — the work-shape used for quality-fit routing.
4. `safety_level` — `low | medium | high`.
5. `safety_tags` — structured dual-use/privacy/financial and related tags.
6. `tool_profile` — named tool-host constraint, or `none`.
7. `primary_lane` — `codex | claude | gemini`; Kimi is forbidden as a primary.
8. `primary_profile` — model/effort/flags key in `shared/registries/profiles.tsv`.
9. `backup_lane` — genuine cross-family operational backup.
10. `backup_profile` — backup profile registry key.
11. `escalate_lane` — lane used by the escalation policy.
12. `escalate_profile` — stronger profile registry key.
13. `escalation_policy` — versioned policy registry key.
14. `review_lane` — independent reviewer lane, or `none` where permitted.
15. `review_profile` — reviewer profile registry key, or `none`.
16. `anti_affinity` — reviewer-separation constraint, or `none`.
17. `throughput_lane` — optional bulk/downshift lane.
18. `throughput_profile` — optional bulk profile.
19. `throughput_policy` — versioned downshift policy.
20. `failover_policy` — versioned operational-failover policy.
21. `operator_gate` — closed list of actions requiring explicit operator approval.
22. `heightened_risk` — `true | false` defense-in-depth marker.
23. `requires_approval` — harness tool approvals declared by the brief.
24. `required_tools` — required verified tool capabilities.
25. `preferred_tools` — optional verified tool capabilities.
26. `notes` — non-empty one-line role description.
27. `tags` — routing/catalog metadata.
28. `version` — row contract version.

`bin/validate-specialists.sh` rejects a non-exact header or any row that does not have 28 fields. It also validates lane/profile and policy foreign keys, source namespaces, capability and safety enums, cross-family primary/backup separation, Kimi's zero-primary rule, review independence, high/heightened-risk escalation floors, throughput gates, operator gates, tool-profile compatibility, specialist briefs, and native lane adapters. Folder location must never be used to infer model choice.

## Model Lanes

| Lane | CLI | Best fit |
|---|---|---|
| `chrono` | Claude Code | operator conversation, planning, dispatch, conflict prevention, synthesis |
| `gpt-codex` | Codex | implementation, repo edits, tests, refactors, PoC mechanics |
| `claude` | Claude Code | judgment, safety review, privacy/auth reasoning, memory hygiene, adversarial challenge |
| `gemini` | Gemini | multimodal analysis, media generation routes, visual/design review, grounded content |
| `kimi` | Kimi | throughput-only bulk/mechanical work under an explicit downshift gate; zero primary roles |

## Dispatch Algorithm

1. Chrono identifies the operator-approved mode and desired artifact.
2. Chrono selects the canonical specialist.
3. Chrono looks up the `primary_lane`/profile, independent `review_lane`/profile, `source_namespace`, safety/tool constraints, and versioned policies in `shared/specialist-runtime-map.tsv`.
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
