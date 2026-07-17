---
id: maintenance/harness-audit-compatibility
mode: maintenance
title: Harness audit / compatibility (prompt · tool · script drift · MCP reachability)
capability_state: live
state_reason: Auditing prompt/tool/script drift and MCP reachability is judgment + local shell + `chrono-vault` (`all·yes`); no catalog-absent tool is load-bearing. `harness-optimizer` is audit/review-only (implementation is a future split per Sol) — findings route to the owning implementer; this card does not mutate the harness.
state_evidence: registry rows — chrono-vault/chrono-obsidian = `all·yes·subscription`. MCP reachability is checked via the lane shell + the `mcp-reachability-audit` methodology; no catalog-absent tool is required.
overlays: [review, memory]
gates: []
cost_note: subscription lane-native (chrono-vault / chrono-obsidian) + local shell. No metered provider is required.
---

**When to use:** audit the squad's own configuration for drift — prompt/instruction adapters, tool
declarations, script/config compatibility, and MCP reachability. **Audit-only:** findings are reported and
handed off; remediation (mutating the harness) routes to the owning implementer, not this card.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (audit scope) | `harness-optimizer`, `prompt-engineer` | — | `scope-decomposition` (stub) | — |
| **S3** Produce (drift + reachability audit) | `harness-optimizer`, `prompt-engineer` | `chrono-vault` (all · yes · subscription), `codex --sandbox` (codex · yes · subscription), `claude --worktree` (claude · yes · subscription) | `mcp-reachability-audit` (stub), `prompt-cache-discipline` (stub), `prompt-cache-hit-monitoring` (stub) | — |
| **S4** Verify (findings triage) | `harness-optimizer`, `skeptic` | — | — | — |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer) |
| **S6** Ship/Deliver (audit report + handoff) | `harness-optimizer`, `technical-writer` | `chrono-obsidian` (all · yes · subscription) | — | audit-only — remediation routes to the owning implementer |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** `harness-optimizer` audits/reviews only — its runtime charter says implementation is a future
split, so this card produces findings + a handoff, never a harness mutation (that would be a
`self-extension`/implementation task under its own gates). MCP reachability uses the lane shell + the
`mcp-reachability-audit` methodology; note that the `parity-probe` SKILL still references the retired
`chrono-catalog` namespace and needs maintenance before it can be a hard acceptance gate.
