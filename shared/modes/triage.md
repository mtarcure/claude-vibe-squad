---
name: triage
version: 1.1
primary_mode_namespace: chrono
status: active
phases: 3
---

# Mode: Triage

For ambiguous incoming work. Triage classifies and recommends; it does not auto-engage another mode.

## Capabilities

Part of the **Operations** nav-family (incident · maintenance · triage) — triage is the **front door**; a display grouping, **not** a 7th `ops` mode; keeps `mode: triage`.

`triage` has **0 capability cards** — it classifies and routes, it does not execute a capability. Its recommendation output is **`mode` + `capability` + `capability_state` + cost exposure + uncertainty** (FINAL-PLAN §5), so the operator sees exactly where it routes and the target capability's honest state/cost before engaging. The `capability_state` it cites is the derived, machine-checked value from `bin/validate-capabilities.sh`, never hand-set.

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 1 | Classification | `triage` when Chrono needs help |
| 2 | Duplicate and context check | `triage`, `summarizer` |
| 3 | Recommendation | Chrono direct, `vibecoding-check` if the routing risk is high |

## Dispatch Notes

- Surface the likely mode, specialist family, safety level, and uncertainty.
- Ask the operator before escalating into bounty, project, incident, research, maintenance, content, or outreach.

## Gates

- Operator confirmation before starting another mode.
- No external sends, writes, deletes, credential changes, or public actions during triage.
