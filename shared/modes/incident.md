---
name: incident
version: 1.1
primary_mode_namespace: sysmgmt
status: active
phases: 4
---

# Mode: Incident

For urgent reactive triage when something is broken. Chrono keeps the work scoped and evidence-preserving.

## Capabilities

Part of the **Operations** nav-family (incident · maintenance · triage) — a display grouping over three canonical modes, **not** a 7th `ops` mode; incident keeps `mode: incident`.

`incident` has **0 capability cards** — it is a mode-level reactive workflow (see Flow below), not a set of registry capabilities. `capability_state` is derived + machine-checked by `bin/validate-capabilities.sh` for the cards that exist; incident has none to index.

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 1 | Stabilize | `mac-ops`, `agentops`, `site-reliability-engineer` (reliability) / `incident-responder` (suspected compromise) |
| 2 | Diagnose | `systems-engineer`, `backend-engineer`, `security-analyst`, `incident-responder`, `skeptic` as needed |
| 3 | Patch | implementation specialist plus read-only reviewer |
| 4 | Postmortem | `technical-writer`, `incident-responder` (post-incident + `detection-engineer` handoff), `memory-curator`, `vibecoding-check` |

## Dispatch Notes

- Capture volatile evidence before changing state; preserve chain of custody.
- Use the smallest reversible fix first.
- Reliability-only incidents → `site-reliability-engineer` (codex/Sol, high-safety). Suspected compromise → `incident-responder` leads (claude/Fable, heightened-risk); it preserves evidence and hands observed TTPs to `detection-engineer`.
- Security, auth, secrets, and network incidents require multi-model review. The GLOBAL safety-refusal invariant applies — a genuine refusal surfaces and is never cross-family re-dispatched.

## Gates

- Operator approval before destructive actions, rollback, credential changes, public disclosure, broad system cleanup, or live production mutation (`operator_gate`: `delete`/`cleanup`/`credential_change`/`public_release`/`production_mutation`).
- Run `vibecoding-check` before closing the incident.
