---
name: triage
version: 1.1
primary_mode_namespace: chrono
status: active
phases: 3
---

# Mode: Triage

For ambiguous incoming work. Triage classifies and recommends; it does not auto-engage another mode.

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
