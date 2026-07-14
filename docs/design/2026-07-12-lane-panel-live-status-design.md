---
date: 2026-07-12
topic: lane-panel-live-status
status: approved
scope: single-file enhancement to bin/watch-lane.sh
---

# Lane panel live status — design

> **Curated design record.** Field positions below have been refreshed to the current 28-column routing schema; `docs/architecture.md` and `shared/routing.md` remain runtime truth.

## Goal

Make each model-lane card in the Chrono sidebar answer, at a glance: **which
specialist is running, what the task is, which tools it uses, and what the lane
is doing right now.** Enhancement only — no daemon or dispatch changes.

## Surface

`bin/watch-lane.sh` `draw_card()` — the sidebar dashboard already renders one
boxed card per lane (state, tagline, specialist, queue, last). We enrich the
**active** card and leave the idle card as-is.

## Card layout (active lane)

```
┌ CLAUDE · WORKING ───────────────┐
│ spec   security-analyst          │
│ task   Audit auth flow for SSRF  │
│ tools  chrono-vault · chrono-kg  │
│ now    ▸ Churned for 5m 40s      │
│ queue  in 1 · active 1 · out 3   │
└──────────────────────────────────┘
```

Idle lane (no active packet) keeps today's card: tagline + queue + `last <result>`.
So idle lanes stay quiet; the new lines appear only when there is real work.

## Data sources (all local, read in the existing 2s loop)

| Field   | Source |
|---------|--------|
| `spec`  | `departments/*/active/TASK-*.md` frontmatter `specialist:` (already read by `active_specialist`) |
| `task`  | body `# <H1>` of that same active packet (same parse `latest_result` already does on responses) |
| `tools` | `shared/specialist-runtime-map.tsv` row for the specialist → `required_tools` (column 24) + `preferred_tools` (column 25), joined with `·` |
| `now`   | `tmux capture-pane -t squad:<lane> -p`, parsed (see below) |

## The `now` line — approach A (generic + graceful)

Per lane, when it has an active task:
1. `tmux capture-pane -t "${SESSION}:<lane>" -p` (visible pane text).
2. Decide **working vs idle** by presence of any activity marker: `✻`, `⏺`
   (Claude), `─ Working for` / `─ Worked for` (Codex), or a thinking/spinner
   line. No marker → emit **no** `now` line (don't guess).
3. If working: take the most recent marker/content line, strip ANSI, box-drawing
   chars (`─│╭╮╰╯▄▀`), leading glyphs, and collapse whitespace; truncate to the
   card inner width.

Deliberately CLI-agnostic: survives CLI UI updates and shows nothing rather than
garbage when it can't parse. Precision like "running semgrep scan" is a non-goal
(that was approach B, rejected as brittle across 4 CLIs).

## New/changed units in `watch-lane.sh`

- `tools_for_specialist <specialist>` — TSV lookup, returns `a · b · c` or empty.
- `active_task_objective <lane>` — H1 of the newest active packet for the lane.
- `live_now_line <lane>` — capture-pane → marker-detect → cleaned snippet or empty.
- `draw_card` — when state is WORKING/PENDING and data is present, render the
  `spec` / `task` / `tools` / `now` rows (each omitted if its value is empty),
  then keep `queue`. Height-fill padding (already added) unchanged.

## Behavior notes

- Manually-driven lanes (operator types straight into the pane, no mailbox
  packet) have no `spec`/`task`/`tools`, so only `now` shows — still useful.
- `SESSION` is available to `watch-lane.sh` via `SQUAD_SESSION` (default `squad`).
- Performance: 4 extra `capture-pane` + a couple file reads per 2s tick — all
  local, negligible.

## Out of scope

- Real-time individual tool-call tracking (that's approach B).
- Pane-border (poller) changes — the border stays state + elapsed.
- Any daemon `/tasks` schema change.

## Verification

Respawn the sidebar pane (`tmux respawn-pane -k -t squad:chrono.1 …`) and
screenshot; confirm active lanes show spec/task/tools/now and idle lanes are
unchanged. Dispatch a real task to one lane to see the active path populate.
