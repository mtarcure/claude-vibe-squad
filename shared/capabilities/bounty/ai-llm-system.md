---
id: bounty/ai-llm-system
mode: bounty
title: LLM / AI-system vulnerability research (authorized)
capability_state: live
state_reason: The live scope is OFFLINE — analysis of operator-supplied transcripts/outputs and design of prompt-injection / jailbreak / tool-agent-abuse / RAG-exfil / guardrail-bypass attacks (judgment + `context7` docs). No catalog-absent tool is load-bearing for this scope. Live-endpoint probing of the target (autonomously sending prompts, observing responses, iterating attacks) is a `needs_tool` profile — there is NO registry-verified browser/API interaction route (`playwright`/`chrome-devtools` catalog-absent); operator authorization is a gate, not an execution path.
state_evidence: registry rows — context7 = `claude·lane-live·subscription`; xai_search = `all·lane-live·metered`, perplexity_search_web = `claude·lane-live·metered`; chrono-vault/chrono-obsidian/chrono-recon = `all·yes·subscription`; playwright/chrome-devtools = `unknown·catalog-absent·unknown` (→ live-endpoint probing is `needs_tool`, see Profiles). `red-team-operator` is a canonical role with `tool_profile: none` (judgment, no tools) and an `offensive_execution` operator gate (manual hold).
overlays: [review, impact, privacy, memory]
gates: [public_release]
cost_note: The offline analysis/design is model-lane reasoning (subscription lane-native); `context7` is subscription. The S1 web-research passthrough (`xai_search`, `perplexity_search_web`) is `metered` and needs a budget/rate-limit guard. No paid provider is on the core path; live-endpoint interaction is `needs_tool`/operator-performed.
---

**When to use:** authorized vuln research against an LLM / AI system — design attacks and analyze
operator-supplied transcripts/outputs → report. Heightened-risk. Instantiates the `bounty` flow on S0–S7.
Live-endpoint probing is `needs_tool` (no verified interaction route — see Profiles). Requires an
operator-confirmed in-scope target; **no destructive testing, respect the program's model-abuse and
rate-limit rules.**

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); target authorization precheck |
| **S1** Frame (system intel + scope) | `scout`, `research` | `chrono-recon` (all · yes · subscription), `perplexity_search_web` (claude · lane-live · metered), `context7` (claude · lane-live · subscription) | `audit-context-prep` (stub), `program-rubric-lookup` (stub) | operator target-engage gate |
| **S2** Design (attack surface + threat-model) | `threat-modeler`, `ai-engineer`, `security-analyst` | `chrono-vault` (all · yes · subscription) | `attack-coverage-map` (authored), `data-flow-trace` (stub) | — |
| **S3** Produce (attack design + offline analysis) | `red-team-operator`, `ai-engineer`, `security-analyst` | `context7` (claude · lane-live · subscription) | `attack-coverage-map` (authored), `data-flow-trace` (stub) | heightened-risk; **manual hold: `offensive_execution` (NOT machine-enforced)**; live-endpoint probing is `needs_tool`; no destructive testing |
| **S4** Verify (impact + PoC-repro) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | impact G1–G4 overlay; privacy overlay if the finding exposes PII/training data; cross-family PoC-reproduction |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay; staging allowed — **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored), `evidence-chain-preservation` (stub) | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record; `restricted` sensitivity) |

**Notes.** `red-team-operator` is judgment-only (`tool_profile: none`) — the offensive value is analysis, not a
tool. The `offensive_execution` gate named for `red-team-operator` is a **manual hard hold** (runtime metadata
only, not in the machine `operator_gate` enum) — do not claim machine enforcement. The G1–G4 impact gate and
cross-family PoC-reproduction are mandatory before the operator-gated final Submit. Findings that expose PII or
training data fire the privacy overlay (`privacy-steward`). Safety-refusal invariant applies; a genuine refusal
surfaces and is never cross-family re-dispatched. Distinct from `project/ai-llm-application` (BUILD, not attack).

**Needs-tool profile (NOT part of the live claim):** Live-endpoint probing — autonomously sending prompts to
the target, observing responses, and iterating jailbreak/injection attempts — is `needs_tool`: no browser/API
interaction route is registry-verified (`playwright`/`chrome-devtools` catalog-absent). Operator authorization
is a gate, not an execution path; live interaction is operator-performed or deferred until a verified
interaction tool exists. The `live` claim covers only offline transcript analysis + attack design.
