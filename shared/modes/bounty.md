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

- Bounty work does not imply one model lead. Chrono dispatches each specialist through `shared/specialist-runtime-map.tsv`.
- PoC code and harness mechanics usually route to GPT/Codex with Claude review.
- Source-heavy target research may route to Kimi or Claude depending on specialist.
- Report wording may route to Claude or Gemini depending on the assigned specialist.

## Gates

- Operator approval before engaging a target, touching authenticated scope, submitting a report, contacting a program, or writing private bounty details to durable public-facing files.
- Mandatory multi-model review for exploitability, impact, privacy, auth, and final report claims.
- No destructive testing, rate-limit abuse, persistence, credential use, or out-of-scope probing.
- Run `vibecoding-check` before final operator summary.
