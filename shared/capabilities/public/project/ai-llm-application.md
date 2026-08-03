---
id: project/ai-llm-application
mode: project
title: AI / LLM application (agents · RAG · tool-use · evals)
overlays: [review, privacy, memory]
gates: [production_mutation, credential_change]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** ship an AI-*enabled product* — agent apps, RAG, tool-use, evaluation harnesses. Distinct
from `project/self-extension-agent-tooling`, which changes the squad's own agent/tool *platform*.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (requirements + research) | `product-manager`, `ai-engineer` | `codex --search` | `requirements-elicitation`, `scope-decomposition` | — |
| **S2** Design (agent/RAG arch + eval criteria) | `architect`, `ai-engineer`, `prompt-engineer` | `sequential-thinking`, `context7` | `dependency-cycle-audit` | — |
| **S3** Produce (build agents / RAG / tools) | `ai-engineer`, `backend-engineer`, `prompt-engineer` | `context7`, `chrono-vault` | `prompt-cache-discipline` | — |
| **S4** Verify (eval harness — mocked / lane-model / opt-in live-model) | `test-engineer` | `DeepSeek API`, `DeepSeek context caching`, `xAI API` | `eval-harness-pattern`, `representative-workload-design` | opt-in metered (`default=false`, guarded) + `credential_change` for the live-model provider key |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review`, `claude --from-pr` | — | review overlay (mandatory cross-family for routing / high-blast-radius changes) — review tools MECHANICS ONLY, never replacing the independent cross-family reviewer |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` | — | `production_mutation` (deploy) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** **Live-model acceptance is now a VERIFIED opt-in metered route.** A real acceptance run against an
external LLM endpoint uses `DeepSeek API` / `xAI API` — wired at
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
