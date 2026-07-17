---
id: project/ai-llm-application
mode: project
title: AI / LLM application (agents · RAG · tool-use · evals)
capability_state: live
state_reason: Live scope is build + mocked/lane-model integration + eval-harness authoring — agents, RAG, tool-wiring, and eval harnesses are code that needs no catalog-absent tool, and the cited tools are all live (`sequential-thinking`/`chrono-vault` yes on all lanes, `context7` lane-live on claude). Live acceptance/eval against a SPECIFIC external LLM provider endpoint is a separate profile that is `needs_tool` — no metered LLM provider endpoint is registry-verified (DeepSeek/xAI API = needs-research, OpenAI/Gemini API = catalog-absent) — and carries a conditional `credential_change` gate + a metered budget/rate-limit guard.
state_evidence: registry rows — sequential-thinking = `all·yes`, chrono-vault = `all·yes`, context7 = `claude·lane-live`; no catalog-absent tool on the build/mocked-eval path. No metered LLM provider endpoint is registry-verified: DeepSeek API / xAI API = `needs-research`, OpenAI API / Gemini API = `catalog-absent` → a live-model acceptance run is `needs_tool`.
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change]
cost_note: subscription for the build tools + mocked/lane-model eval — the default scope incurs no metered cost. A live-model acceptance profile calls an external LLM provider endpoint (`metered`, API-key billed, budget/rate-limit guarded) and needs a `credential_change` — but those endpoints are currently `needs_tool` (DeepSeek/xAI = needs-research, OpenAI/Gemini API = catalog-absent), so that profile is not live today. A voice-channel profile adds ElevenLabs (Claude-lane, metered).
---

**When to use:** ship an AI-*enabled product* — agent apps, RAG, tool-use, evaluation harnesses. Distinct
from `project/self-extension-agent-tooling`, which changes the squad's own agent/tool *platform*.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (requirements) | `product-manager`, `ai-engineer` | — | `requirements-elicitation` (stub), `scope-decomposition` (stub) | — |
| **S2** Design (agent/RAG arch + eval criteria) | `architect`, `ai-engineer`, `prompt-engineer` | `sequential-thinking` (all · yes · subscription), `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub) | — |
| **S3** Produce (build agents / RAG / tools) | `ai-engineer`, `backend-engineer`, `prompt-engineer` | `context7` (claude · lane-live · subscription), `chrono-vault` (all · yes · subscription) | `prompt-cache-discipline` (stub) | — |
| **S4** Verify (eval harness — mocked / lane-model) | `test-engineer` | — | `eval-harness-pattern` (stub), `representative-workload-design` (stub) | — |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | — | — | review overlay (mandatory cross-family for routing / high-blast-radius changes) |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | — | `production_mutation` (deploy) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** **Live-model acceptance is a `needs_tool` profile, not part of the live scope.** A real acceptance
run against a specific external LLM provider needs that provider's endpoint + credentials (`credential_change`)
and is metered (budget/rate-limit guarded) — but no metered LLM provider endpoint is registry-verified
(DeepSeek/xAI API = needs-research, OpenAI/Gemini API = catalog-absent), so live-model acceptance is
`needs_tool` today. The default live scope is build + mocked/lane-model integration + eval-harness authoring.
A voice-channel profile adds `voice-agent-builder` + the ElevenLabs child MCP (Claude-lane-only, `metered`) at
S3. Routing/auth/high-blast-radius changes require cross-family review (`ai-engineer` is a high-safety role).
This builds a product; it does not modify the squad platform (that is self-extension).
