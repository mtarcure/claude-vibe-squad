---
id: project/ai-llm-application
mode: project
title: AI / LLM application (agents · RAG · tool-use · evals)
capability_state: live
state_reason: Live scope is build + mocked/lane-model integration + eval-harness authoring — code needing no catalog-absent tool (`sequential-thinking`/`chrono-vault` yes all lanes, `context7` lane-live on claude). Live-model acceptance/eval against an external LLM endpoint is now a VERIFIED opt-in metered route: `DeepSeek API` and the `xAI API` direct route are `codex·yes·metered` (probe TASK-0310) — wired `default=false`, per-task opt-in, guarded, behind a conditional `credential_change` gate. Derived stays `live`.
state_evidence: registry rows — sequential-thinking = `all·yes`, chrono-vault = `all·yes`, context7 = `claude·lane-live`; `DeepSeek API` / `xAI API` = `codex·yes·metered` (probe TASK-2026-07-17-0310, reviewed TASK-0320) — verified for TEXT completion only, `default=false` opt-in with the metered guard. OpenAI/Gemini API remain `catalog-absent`.
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change]
cost_note: the default scope (build + mocked/lane-model eval) is subscription-tier; metered spend occurs only when the opt-in live-model acceptance profile is enabled. That profile calls `DeepSeek API` / `xAI API` (`metered`, API-key billed) `default=false`, per-task Chrono opt-in, with a provider/endpoint/model allowlist; call, total-token, output-token, and cost ceilings (plus a reasoning-token ceiling for `xAI API`); no blind retry, loop, or fallback; typed `needs_tool:auth|budget|rate_limited` (401/403→auth, 402→budget, 429→rate); and a `credential_change` gate. A repeated eval suite reuses `DeepSeek context caching` (canonical `deepseek-v4-flash` model) to cut repeat-prompt spend (~95% cheaper on cache hits) — still metered, still under the same guard. A voice-channel profile adds ElevenLabs (Claude-lane, metered).
---

**When to use:** ship an AI-*enabled product* — agent apps, RAG, tool-use, evaluation harnesses. Distinct
from `project/self-extension-agent-tooling`, which changes the squad's own agent/tool *platform*.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (requirements + research) | `product-manager`, `ai-engineer` | `codex --search` (codex · yes · subscription) | `requirements-elicitation` (stub), `scope-decomposition` (stub) | — |
| **S2** Design (agent/RAG arch + eval criteria) | `architect`, `ai-engineer`, `prompt-engineer` | `sequential-thinking` (all · yes · subscription), `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub) | — |
| **S3** Produce (build agents / RAG / tools) | `ai-engineer`, `backend-engineer`, `prompt-engineer` | `context7` (claude · lane-live · subscription), `chrono-vault` (all · yes · subscription) | `prompt-cache-discipline` (stub) | — |
| **S4** Verify (eval harness — mocked / lane-model / opt-in live-model) | `test-engineer` | `DeepSeek API` (codex · yes · metered), `DeepSeek context caching` (codex · yes · metered), `xAI API` (codex · yes · metered) | `eval-harness-pattern` (stub), `representative-workload-design` (stub) | opt-in metered (`default=false`, guarded) + `credential_change` for the live-model provider key |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (mandatory cross-family for routing / high-blast-radius changes) — review tools MECHANICS ONLY, never replacing the independent cross-family reviewer |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | — | `production_mutation` (deploy) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** **Live-model acceptance is now a VERIFIED opt-in metered route.** A real acceptance run against an
external LLM endpoint uses `DeepSeek API` / `xAI API` (`codex·yes·metered`, probe-verified for text) — wired at
S4 `default=false`: per-task Chrono opt-in; provider/endpoint/model allowlist; call, total-token, output-token,
and cost ceilings (`xAI API` adds a reasoning-token ceiling — its probe drew 107 reasoning tokens for an
8-token request); no blind retry, loop, or fallback; typed `needs_tool:auth|budget|rate_limited` (401/403→auth,
402→budget, 429→rate); plus a `credential_change` gate for the provider key.
The default scope (build + mocked/lane-model integration + eval-harness authoring) stays subscription-tier and
incurs metered spend only when that opt-in profile is enabled. (Only TEXT completion is verified — coding/
reasoning quality is unbenchmarked, and xAI `num_sources=0` is reasoning, NOT grounded search.) A voice-channel
profile adds `voice-agent-builder` + the ElevenLabs child MCP (Claude-lane-only, `metered`) at S3. Routing/
auth/high-blast-radius changes require cross-family review (`ai-engineer` is a high-safety role); the S5 review
tools are mechanics only. This builds a product; it does not modify the squad platform (that is self-extension).
