# Claude-Vibe-Squad Routing

Chrono is the only controller. It chooses the mode, specialist, write owner, model lane, and review gate. The visible execution lanes are:

```text
chrono -> gpt-codex | claude | gemini | kimi -> specialists
```

Department folders remain compatibility namespaces for prompts, memory, and mailboxes. Folder location does not determine model choice.

Canonical runtime table: `shared/specialist-runtime-map.tsv`.

## Runtime Defaults

| Model lane | Best for |
|---|---|
| `gpt-codex` | implementation, repo edits, tests, refactors, diff review, PoC mechanics |
| `claude` | coordination, judgment, security reasoning, privacy, SysMgmt, adversarial review |
| `kimi` | long context, source-heavy research, large corpus synthesis |
| `gemini` | multimodal content/design, Google-grounded research, visual/media workflows |

## Mode Invocation

Mode engagement is operator-driven.

Concrete artifacts suggest a mode, then Chrono asks for consent:

| Artifact | Suggested mode |
|---|---|
| HackerOne / Bugcrowd / Intigriti / HackenProof / Code4rena URL | Bounty |
| Sentry alert URL or active outage evidence | Incident |
| GitHub Issue URL | Triage |
| stack trace plus broken/down/failing | Incident |
| `.sol`, `.vy`, `.rs` in audit context | Bounty |
| app or repo files in build context | Project |

Slash commands remain: `/bounty`, `/project`, `/content`, `/outreach`, `/maintenance`, `/incident`, `/research`, `/triage`, `/exit`, `/archive`, `/status`.

Chrono never silently switches modes and never auto-engages from a casual phrase.

## Dispatch Contract

Every complex dispatch must name:

- `to_model`: `gpt-codex | claude | gemini | kimi`
- `specialist`: canonical specialist from `chrono/SPECIALIST-INDEX.md`
- `source_namespace`: compatibility namespace where the canonical specialist lives
- `write_scope`: exact writable paths, or `[]` for read-only work
- `review_model`: read-only reviewer lane, or `none`
- `mandatory_review`: `true | false`
- `parallel_safe`: `true | false`
- `lead_direct_allowed`: default `false`

`scripts/send-task.sh` and `bin/send-task.sh` fill and enforce these fields against `shared/specialist-runtime-map.tsv`.

## Safety Gates

Dispatch is blocked when:

- the specialist is unknown
- the specialist is missing from `shared/specialist-runtime-map.tsv`
- `to_model` or `review_model` is not a valid lane
- `to_model` differs from the model map and no `model_override_reason` is present
- `mandatory_review:true` has `review_model:none`
- a high-safety specialist is dispatched without mandatory review
- write scopes overlap active in-flight work

Reviewers are read-only unless Chrono serializes a later write pass.

Explicit operator approval is required for deletes, external sends, credential changes, cleanup actions, public release changes, and any live outreach/email send. Outreach stays dry-run by default.

Mandatory multi-model review applies to security findings, bounty reports, privacy/PII, auth/credential work, email/outreach sending, public release, filesystem cleanup, and high-blast-radius architecture.

## Compatibility Namespaces

| Namespace | Typical specialists | Usual model lane |
|---|---|---|
| `coding` | backend-engineer, frontend-engineer, test-engineer, exploit-developer | `gpt-codex` |
| `security` | security-analyst, impact-validator, privacy-steward, scout | `claude` or `kimi` by map |
| `content` | media-producer, designer, content-creator, technical-writer | `gemini` or `claude` by map |
| `sysmgmt` | memory-curator, mac-ops, harness-optimizer | `claude` |
| `research` | research, synthesizer, large-context-analyst | `kimi` |
| `shared` | planner, skeptic, triage, vibecoding-check | map-defined |

## Pathology Safety Net

| Pattern | Action |
|---|---|
| same specialist dispatched three times with the same prompt | pause, surface to operator |
| specialist returns errors three times in a row | pause, surface error |
| MCP retry loop | stop the loop, pause, surface |
| no new artifacts after expected specialist turns | pause, surface |
| lane-to-lane request bouncing repeatedly | pause, surface routing ambiguity |

## Nightly Routines

Launchd routines may run doctor, cleanup audits, dream, content sweep, and morning brief generation. They must not perform destructive cleanup, public release changes, external sends, or credential changes without explicit operator approval.
