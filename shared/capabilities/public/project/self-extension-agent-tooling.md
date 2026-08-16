---
id: project/self-extension-agent-tooling
mode: project
title: Self-extension — MCP servers · plugins · skills · agents · adapters
overlays: [review, privacy, memory]
gates: [credential_change, production_mutation, public_release]
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

**When to use:** build or change the agent/tool platform itself — MCP servers, Claude/Codex/Gemini plugins
or extensions, skills, agent/subagent definitions, tool adapters, routing integrations, eval harnesses.
Distinct from `project/ai-llm-application` (which ships an AI-*enabled product*); this changes the
platform, so it adds manifest, permissions, compatibility, rollback, and multi-lane acceptance.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` | — | memory overlay (recall); scope = which surface to extend |
| **S1** Frame (requirements) | `product-manager`, `architect` | — | `requirements-elicitation` | — |
| **S2** Design | `architect`, `ai-engineer` | `sequential-thinking` | `dependency-cycle-audit` | — |
| **S3** Produce (build) | `ai-engineer`, `backend-engineer`, `prompt-engineer`, `devops-engineer` | `claude mcp/plugin/agents`, `codex mcp`, `codex mcp-server`, `codex plugin`, `gemini extensions`, `gemini skills`, `codex --sandbox`, `claude --worktree` | — | least-privilege fs/egress/credential/secret handling (hard acceptance) |
| **S4** Verify | `test-engineer`, `software-supply-chain-engineer` | — | `mcp-reachability-audit`; `parity-probe` | typed-failure / no-false-success acceptance: startup · `tools/list` discovery · permissions · negative-path · rollback · tested on **every advertised lane** |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (cross-family for routing/auth/high-blast-radius; review tools MECHANICS ONLY — never replace the independent cross-family reviewer); `credential_change`/`production_mutation` on live install; dependency-trust changes → operator approval |
| **S6** Ship/Deliver (install/publish) | `devops-engineer` | — | — | `public_release` on publish; install uses the executing lane's S3 management subcommand |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** Use only the **executing lane's** management surface (the S3 tuple for that lane); a tool is
cited per lane, not shared across lanes. **No new specialist in v1** — `ai-engineer` owns implementation
per its runtime charter (agent apps, tool wiring, eval harnesses); `harness-optimizer` stays audit/reviewer
only (its charter defers the implementation split). Add a future `agent-tooling-engineer` only if demand
proves a stable ownership bottleneck. `parity-probe` is the operator entry point for retained, typed
Project/Bounty v2 board canaries; it does not call providers directly and is not itself liveness evidence.
Only dependency-valid controller receipts may satisfy the later generated capability gate.
Evidence the capability narrowly with the four plugins — do not inflate to "any plugin on every lane." No
`offensive_execution`/`malware_detonation` gates apply here (that is `bounty/authorized-red-team`, not
builder tooling).
