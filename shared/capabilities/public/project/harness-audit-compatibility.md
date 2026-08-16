---
id: project/harness-audit-compatibility
mode: project
title: Harness audit / compatibility (prompt · tool · script drift · MCP reachability)
overlays: [review, memory]
gates: []
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

## Availability in a fresh clone

A zero-key checkout gets this protocol and its validation metadata as documentation; automated dispatch is `needs_tool`. To make it runnable, install and authenticate the selected model CLI, configure every MCP declared by the dispatched specialists, bind the private vault (`CHRONO_VAULT_ROOT`; Kimi also requires its exact vault context), install any required host-local binaries, and provide approved credentials plus a bounded budget for any metered provider named below. After setup, re-run the production role planner and validators on that host; availability remains subject to the narrower gaps and operator gates documented in this card.

**When to use:** audit the squad's own configuration for drift — prompt/instruction adapters, tool
declarations, script/config compatibility, and MCP reachability. **Audit-only:** findings are reported and
handed off; remediation (mutating the harness) routes to the owning implementer, not this card.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (audit scope) | `harness-optimizer`, `prompt-engineer` | — | `scope-decomposition` | — |
| **S3** Produce (drift + reachability audit) | `harness-optimizer`, `prompt-engineer` | `chrono-vault`, `codex --sandbox`, `claude --worktree` | `mcp-reachability-audit`, `prompt-cache-discipline`, `prompt-cache-hit-monitoring` | — |
| **S4** Verify (findings triage) | `harness-optimizer`, `skeptic` | — | — | — |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer) |
| **S6** Ship/Deliver (audit report + handoff) | `harness-optimizer`, `technical-writer` | `chrono-obsidian` | — | audit-only — remediation routes to the owning implementer |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** `harness-optimizer` audits/reviews only — its runtime charter says implementation is a future
split, so this card produces findings + a handoff, never a harness mutation (that would be a
`self-extension`/implementation task under its own gates). MCP reachability uses the lane shell + the
`mcp-reachability-audit` methodology. `parity-probe` now points only to retained Project/Bounty v2 board
canaries; it runs no provider command and grants no liveness by itself. Retired `chrono-content-engineer` and
`chrono-catalog` spellings are historical findings, not current routes, and must not be reintroduced by an
audit or compatibility repair.
