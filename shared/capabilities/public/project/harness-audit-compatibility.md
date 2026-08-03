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
`mcp-reachability-audit` methodology; note that the `parity-probe` SKILL still references the retired
`chrono-catalog` namespace and needs maintenance before it can be a hard acceptance gate.

**Confirmed MCP breakages (open audit findings — route to the owning implementer; this card does not fix them):**
1. **`chrono-content-engineer` disconnected.** The plugin directory was renamed `chrono-content-engineer` →
   `chrono-media-studio`, so `~/.kimi/mcp.json` and `.gemini/settings.json` still point at a now-missing
   `mcp_server.py`. Fix = repair the path in those lane configs (restart-unsafe even where a live pane still
   holds the old tools).
2. **`chrono-catalog` disconnected.** `unknown MCP namespace: catalog` — the vault `mcp_server.py` only handles
   the `kg`/`obsidian` namespaces. Fix = implement the `catalog` namespace or re-register under a valid one.
Both are config/implementation repairs (a `self-extension`/maintenance task), not harness mutations by this
audit card.
