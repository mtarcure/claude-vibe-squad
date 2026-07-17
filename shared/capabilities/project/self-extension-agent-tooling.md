---
id: project/self-extension-agent-tooling
mode: project
title: Self-extension — MCP servers · plugins · skills · agents · adapters
capability_state: live
state_reason: The system already ships four working plugin implementations (manifest + FastMCP server + skills), proving MCP/plugin/skill/agent construction is a real capability; the lane management subcommands used to build/install/test are `yes` on their lanes. Lane-scoped — use only the executing lane's surface.
state_evidence: plugins/{chrono-vault,chrono-research-arsenal,chrono-recon,chrono-media-studio}/.claude-plugin/plugin.json (working implementations); registry rows — `claude mcp/plugin/agents` = `claude·yes`, `codex mcp/mcp-server` + `codex plugin` = `codex·yes`, `gemini extensions` + `gemini skills` = `gemini·yes`, `sequential-thinking` = `all·yes` (api-catalog §1–3, §9).
overlays: [review, privacy, memory]
gates: [credential_change, production_mutation, public_release]
cost_note: subscription only — the lane management subcommands are lane-native (no paid provider). No metered tool is required to build/test/install an extension.
---

**When to use:** build or change the agent/tool platform itself — MCP servers, Claude/Codex/Gemini plugins
or extensions, skills, agent/subagent definitions, tool adapters, routing integrations, eval harnesses.
Distinct from `project/ai-llm-application` (which ships an AI-*enabled product*); this changes the
platform, so it adds manifest, permissions, compatibility, rollback, and multi-lane acceptance.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); scope = which surface to extend |
| **S1** Frame (requirements) | `product-manager`, `architect` | — | `requirements-elicitation` (stub) | — |
| **S2** Design (interface · trust-boundary · permissions · rollback · compat) | `architect`, `ai-engineer` | `sequential-thinking` (all · yes · subscription) | `dependency-cycle-audit` (stub) | — |
| **S3** Produce (build) | `ai-engineer`, `backend-engineer`, `prompt-engineer`, `devops-engineer` | `claude mcp/plugin/agents` (claude · yes · subscription), `codex mcp/mcp-server` (codex · yes · subscription), `codex plugin` (codex · yes · subscription), `gemini extensions` (gemini · yes · subscription), `gemini skills` (gemini · yes · subscription) | — | least-privilege fs/egress/credential/secret handling (hard acceptance) |
| **S4** Verify | `test-engineer`, `software-supply-chain-engineer` | — | `mcp-reachability-audit` (stub); `parity-probe` (SKILL.md) — stale | typed-failure / no-false-success acceptance: startup · `tools/list` discovery · permissions · negative-path · rollback · tested on **every advertised lane** |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay (cross-family for routing/auth/high-blast-radius); `credential_change`/`production_mutation` on live install; dependency-trust changes → operator approval |
| **S6** Ship/Deliver (install/publish) | `devops-engineer` | — | — | `public_release` on publish; install uses the executing lane's S3 management subcommand |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Use only the **executing lane's** management surface (the S3 tuple for that lane); a tool is
cited per lane, not shared across lanes. **No new specialist in v1** — `ai-engineer` owns implementation
per its runtime charter (agent apps, tool wiring, eval harnesses); `harness-optimizer` stays audit/reviewer
only (its charter defers the implementation split). Add a future `agent-tooling-engineer` only if demand
proves a stable ownership bottleneck. `parity-probe` is a real invokable skill but flagged `stale` (still
expects the retired `chrono-catalog` namespace) — repair it before it becomes a hard acceptance gate.
Evidence the capability narrowly with the four plugins — do not inflate to "any plugin on every lane." No
`offensive_execution`/`malware_detonation` gates apply here (that is `bounty/authorized-red-team`, not
builder tooling).
