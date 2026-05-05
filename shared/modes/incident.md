---
name: incident
version: 1.1
primary_mode_namespace: sysmgmt
status: active
phases: 4
---

# Mode: Incident

For urgent reactive triage when something is broken. Chrono keeps the work scoped and evidence-preserving.

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 1 | Stabilize | `mac-ops`, `agentops`, affected-domain specialist |
| 2 | Diagnose | `systems-engineer`, `backend-engineer`, `security-analyst`, `skeptic` as needed |
| 3 | Patch | implementation specialist plus read-only reviewer |
| 4 | Postmortem | `technical-writer`, `memory-curator`, `vibecoding-check` |

## Dispatch Notes

- Capture volatile evidence before changing state.
- Use the smallest reversible fix first.
- Security, auth, secrets, and network incidents require multi-model review.

## Gates

- Operator approval before destructive actions, rollback, credential changes, public disclosure, or broad system cleanup.
- Run `vibecoding-check` before closing the incident.
