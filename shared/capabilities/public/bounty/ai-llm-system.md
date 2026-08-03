---
id: bounty/ai-llm-system
mode: bounty
title: LLM / AI-system vulnerability research (authorized)
overlays: [review, impact, privacy, memory]
gates: [public_release]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** authorized vuln research against an LLM / AI system — design attacks and analyze
operator-supplied transcripts/outputs → report. Heightened-risk. Instantiates the `bounty` flow on S0–S7.
Live-endpoint probing is `needs_tool` (no verified interaction route — see Profiles). Requires an
operator-confirmed in-scope target; **no destructive testing, respect the program's model-abuse and
rate-limit rules.**

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` | — | memory overlay (recall); target authorization precheck |
| **S1** Frame (system intel + scope) | `scout`, `research` | `chrono-recon`, `perplexity_search_web`, `context7`, `codex --search`, `Brave Search`, `Serper`, `Apify`, `Google Search grounding` | `audit-context-prep`, `program-rubric-lookup`, `dedup-prior-art-check` | operator target-engage gate; **prior-art/dedup runs BEFORE effort** (`dedup-prior-art-check` — disclosure DBs + `chrono-dedup`); `Apify` scraping requires authorized-scope + spend gate (no Actor run outside the authorized target); `Google Search grounding` = CVE/advisory source-fact grounding, not a substitute for the vuln analysis |
| **S2** Design (attack surface + threat-model) | `threat-modeler`, `ai-engineer`, `security-analyst`, `experimental-attacker` | `chrono-vault` | `systematic-attacking`, `attack-coverage-map`, `data-flow-trace` | governing method: this card is the LLM/AI domain branch of `systematic-attacking` (Phase 2 attack-surface + impact model); **impact-class first** — pre-register HIGH/CRIT termini in the payout classes; **dedicated novel-attack ideation pass every engagement** (Phase 2b) — `experimental-attacker` (kimi) generates broad/novel hypotheses (leads only) fanning out to heavy-hitter (Sol / Opus 5) validation; push past known + known-advisory jailbreak/injection classes, full-arsenal distance is the FLOOR; leads re-enter the verification spine, never ship unproven |
| **S3** Produce (attack design + offline analysis) | `red-team-operator`, `ai-engineer`, `security-analyst` | `context7`, `codex --sandbox`, `claude --worktree` | `agentic-sandbox-escape`, `mcp-schema-poisoning`, `attack-coverage-map`, `data-flow-trace` | heightened-risk; **manual hold: `offensive_execution` (NOT machine-enforced)**; live-endpoint probing is `needs_tool`; no destructive testing; **exhaustive-arsenal every engagement** — adversarial-prompt corpora / red-team datasets generated OFFLINE (see Notes), a Linux-only tool run in a container (colima/docker present), never skipped |
| **S4** Verify (impact + PoC-repro) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `chrono-vault` | `systematic-attacking`, `multi-agent-evidence-gating`, `evidence-chain-preservation` | impact G1–G4 overlay; **evidence-gate to ≥0.85 confidence** (`multi-agent-evidence-gating`) before a candidate reaches the operator / heavy-hitter lane; privacy overlay if the finding exposes PII/training data; cross-family PoC-reproduction; runs `systematic-attacking`'s Phase 4 chaining (chain-strike v2) → Phase 6 impact-bar spine |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); staging allowed — **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` | `citation-audit`, `evidence-chain-preservation` | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | `evidence-chain-preservation` | memory overlay (record; `restricted` sensitivity) |

**Notes.** `red-team-operator` is judgment-only (`tool_profile: none`) — the offensive value is analysis, not a
tool. The `offensive_execution` gate named for `red-team-operator` is a **manual hard hold** (runtime metadata
only, not in the machine `operator_gate` enum) — do not claim machine enforcement. The G1–G4 impact gate and
cross-family PoC-reproduction are mandatory before the operator-gated final Submit. Findings that expose PII or
training data fire the privacy overlay (`privacy-steward`). Safety-refusal invariant applies; a genuine refusal
surfaces and is never cross-family re-dispatched. Distinct from `project/ai-llm-application` (BUILD, not attack).

**Depth standard (operator).** Full-arsenal distance is the FLOOR, not the ceiling. Every engagement runs a
**dedicated novel/innovative-attack ideation pass** past known + known-advisory jailbreak / prompt-injection /
tool-agent-abuse / RAG-exfil / guardrail-bypass classes (leads re-enter `systematic-attacking`'s verification
spine, never ship unproven). The domain analog of "multi-fuzzer" coverage is **systematic adversarial-prompt
fuzzing** — automated red-team corpora / attack-dataset generation and scoring of operator-supplied transcripts.
Two frameworks are host-available for the OFFLINE slice: **`promptfoo`** (host-PATH `/opt/homebrew/bin/promptfoo`,
api-catalog §12 verified 0.121.19) and **`garak`** (api-catalog §12 verified 0.15.1, installed in a state-local
Python venv — not on global PATH, invoke via the arsenal venv). They are referenced in prose, not as live
step-table tuples, because neither is yet promoted into the enforced `skill-tool-registry.tsv` — so they carry no
`live` tuple claim here. Their AUTONOMOUS mode (driving prompts at the target endpoint and iterating) is the SAME
`needs_tool` live-endpoint path already declared below, NOT part of the live claim; a Linux-only red-team tool is
run in a container (colima + docker present) rather than skipped. There is no symbolic-execution analog for this
domain, so none is claimed. Go **beyond commodity tools+chaining** (AI+SAST is table stakes): novel
attack-chain design, custom probe corpora, and dynamic weaponization against the operator-authorized surface.
Impact-bar discipline holds — only intrinsic-impact deterministic findings convert;
reachability/disclosure never pays; never resubmit a non-reproducible finding.

**Impact-class targeting (operator).** S2 pre-registers termini only in the payout classes — **RCE/
sandbox-escape · auth-bypass · privilege-escalation · private-data/PII/training-data · attacker-controlled
agent action**. The two 2025-26 exploit-derived skills wired at S3 hit the top LLM-system payout classes:
`agentic-sandbox-escape` (CBSE + git/worktree confusion → sandbox-to-host RCE; CVE-2026-48124 / -55607) and
`mcp-schema-poisoning` (tool/schema/output poisoning → credential theft / attacker-controlled action). A
bare jailbreak/refusal-bypass with no intrinsic impact is at most a lead.

**Experimental fan-out (operator).** `experimental-attacker` emits broad/novel
LLM-attack hypotheses as **leads only** at S2/S3, fanning out to heavy-hitter (Sol / Opus 5) validation and
gated to ≥0.85 confidence by `multi-agent-evidence-gating` at S4 — no laxer bar than known-class hypotheses
(`systematic-attacking` Phase 3b). This fan-out runs OFFLINE (transcript/design analysis); autonomous
live-endpoint probing stays the `needs_tool` profile below.

**Elite tooling — prose/`needs_tool` (not live tuples).** The OFFLINE adversarial-prompt fuzzers `promptfoo`
(host-PATH) and `garak` (arsenal venv) remain prose-only (not promoted into the enforced registry). Corpus B
Tier-1 addition **NVIDIA Garak** probe packs and a passive-injection corpus are `needs_tool` for the
autonomous path. Two further corpus-C skills are a noted follow-up: `context-stitching-poison` (fragmented
passive prompt injection across log/chat streams) and `prompt-injection-to-rce` (Semantic-Kernel-class
orchestration RCE).

**Needs-tool profile (NOT part of the live claim):** Live-endpoint probing — autonomously sending prompts to
the target, observing responses, and iterating jailbreak/injection attempts — is `needs_tool`: `chrome-devtools`/
`playwright` are verified only for a fresh UNauthenticated Chrome (, web-acceptance /
no-auth), which does NOT cover the authenticated/sanctioned target-interaction path (raw-CDP `:9222`) this
profile requires — that authed route is unverified. Operator authorization is a gate, not an execution path;
live interaction is operator-performed or deferred until a verified authenticated-interaction route exists. The
`live` claim covers only offline transcript analysis + attack design.
