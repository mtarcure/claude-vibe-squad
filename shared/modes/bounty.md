---
name: bounty
version: 1.1
primary_mode_namespace: security
status: active
phases: 11
---

# Mode: Bounty

For bug bounty and vulnerability research. Chrono owns target selection, safety gates, dispatch, review, and operator-facing decisions.

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 0 | Target discovery and operator selection | Chrono direct |
| 1 | Target OSINT | `scout`, `research`, `data-extraction-engineer` |
| 2 | Scope and rules | `scout`, `security-analyst` |
| 3 | Recon | `scout` |
| 4 | Threat model | `threat-modeler`, `security-analyst` |
| 5 | Focused analysis | `security-analyst` |
| 6 | PoC mechanics | `exploit-developer`, `backend-engineer`, `test-engineer` when code-heavy |
| 7 | Variant hunt | `exploit-developer`, `security-analyst` |
| 8 | Chain validation | `impact-validator`, `skeptic` |
| 9 | Report draft | `technical-writer`, `security-analyst` |
| 10 | Final review | `skeptic`, `vibecoding-check` |

## Dispatch Notes

- Bounty work does not imply one model lead. Chrono dispatches each specialist per `shared/specialist-runtime-map.tsv` on capability; see `shared/routing.md` for the model.
- PoC and harness mechanics route to codex (`gpt-5.6-sol`) with claude (`claude-fable-5`) review; judgment/security-reasoning (`security-analyst`, `threat-modeler`, `impact-validator`, `scout`) is claude-primary with codex backup.
- Target research and synthesis route to claude or codex on capability — **not kimi** (kimi is the throughput-only lane, 0 primaries).
- Report wording routes to the assigned writer's lane (`technical-writer` = claude/Fable).
- **Safety-refusal invariant:** a genuine safety refusal on any lane surfaces to the operator and is NEVER cross-family re-dispatched in either direction. The offensive-security specialists here (`security-analyst`, `exploit-developer`, `scout`, `impact-validator`, `smart-contract-engineer`, `threat-modeler`) run under heightened-risk defaults — a refused request is never shopped to a more permissive lane.

## Gates

- Operator approval before engaging a target, touching authenticated scope, submitting a report, contacting a program, or writing private bounty details to durable public-facing files.
- **Pre-submit G1–G4 gate (`impact-validator` owns it):** no finding is submitted unless it clears G1 impact-realized · G2 third-party-reproduced · G3 dedup'd · G4 in-scope defended-boundary, plus its per-class add-on — any FAIL is no-submit. Full gate: `departments/security/specialists/impact-validator.md` → "Pre-Submit Gate (G1–G4)".
- Mandatory multi-model review for exploitability, impact, privacy, auth, and final report claims.
- No destructive testing, rate-limit abuse, persistence, credential use, or out-of-scope probing.
- Run `vibecoding-check` before final operator summary.
