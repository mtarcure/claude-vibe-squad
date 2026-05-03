# Squad Lifecycle Rules

Single source of truth for how panes / Leads / specialists manage their lifecycle, effort tiers, and context discipline. Referenced by `chrono/CLAUDE.md`, vault root `CLAUDE.md`, and every `LEAD.md`.

## 1. Persistent panes

Chrono + 5 Leads stay in tmux indefinitely. Idle = zero token cost. Cost is per-task only.

## 2. Short conversation tail per Lead

Target ≤ 3 tasks of conversation history per Lead session. On task pickup, read `inbox/<task>.md` + own `memory.md` + `current.md`. Vault files are persistence; CLI conversation is per-task work window.

## 3. Prompt caching prefix discipline

- Cached prefix = system prompt + LEAD.md + (optionally) memory.md head
- Per-task user message = inbox task body + minimal context excerpts only
- Anthropic prompt cache TTL is 5 min; covers idle gaps in active work-streaks
- Cache poison rule: never let per-task variables pollute the prefix

## 4. Compaction at phase boundaries

When project transitions Phase N→N+1, each Lead:

- Writes phase-summary line to memory.md
- Runs Anthropic compact_20260112 OR `/clear` + re-load from memory.md
- Acknowledges to Chrono

## 5. Hard reset on engagement close

Operator says "we're done" → Chrono signals all Leads → each writes final state to memory.md → full session reset.

## 6. Specialist subprocesses ALWAYS ephemeral

No persistence. Spawn for one task, die after. Output captured by Lead, written to outbox.

## 7. Per-task effort tiering

Specialist subprocess gets explicit effort flag per task tier:

- T1 trivia: `--effort low` / `--reasoning low` / no thinking
- T2 mechanical: `--effort medium` / `--reasoning medium` / thinking optional
- T3 judgment: `--effort xhigh` / `--reasoning high` / thinking on
- T4 multi-model fanout: each model at its scale's max

## 8. Context-budget circuit breaker

Each Lead has a max context window threshold (60% of model max). On hit: auto-compact + alert SysMgmt's finance-analyst.

## 9. Observability via finance-analyst + harness-optimizer

Per-Lead daily token spend logged. Per-engagement spend archived. Anomaly alerts (Lead spending 3× baseline) surfaced in next morning brief.

## Per-pane effort defaults

Set in `bin/launch-squad.sh`. Per Capability Inventory (`_state/capability-inventory-2026-05-02.md`):

| Pane | CLI | Model | Effort tier flag | Rationale |
|------|-----|-------|------------------|-----------|
| chrono | claude | opus | `--effort xhigh` | Coordinator judgment is high-stakes |
| security | claude | opus | `--effort xhigh` | Security work is judgment-heavy |
| coding | codex | gpt-5.5 | `-c model_reasoning_effort=high` | Codex's max scale; implementation depth |
| sysmgmt | claude | sonnet | `--effort high` | Operations mostly mechanical; specialists scope up per task |
| content | gemini | gemini-3.1-pro-preview | (no flag — implicit at model level) | Gemini 3.1 Pro thinks by default; no `--thinking` flag exists per Capability Inventory |
| research | kimi | k2.6 | `--thinking` | Synthesis depth |

## Per-task overrides

A specialist subprocess can scope effort up or down per task:

```bash
# Trivia — scope down
claude -p --effort low "<trivia task>"

# Adversarial review — scope up
claude -p --effort xhigh "<judgment task>"
```

Lead's pane default is the "background" tier; specialist tier is work-specific.

### Tier guidance per work type

- T1 (trivia): single-call factual lookups, classification, mechanical pattern matching
- T2 (mechanical): implementation work, mechanical specialist routines, fast iteration
- T3 (judgment/review): reviewer roles, high-stakes decisions, deep reasoning, design choices
- T4 (multi-model fanout): security-sensitive, irreversible, contested calls

---

*See also: `shared/api-catalog.md` for per-specialist tool catalog. `chrono/CLAUDE.md` for Coordinator runtime rules.*
