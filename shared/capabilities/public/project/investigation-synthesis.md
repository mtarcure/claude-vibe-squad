---
id: project/investigation-synthesis
mode: project
title: Multi-source investigation + synthesis (deep-research · competitive · literature)
overlays: [review, truth-rights, privacy, memory]
gates: []
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** a multi-source investigation that ends in a synthesized, cited answer — deep research,
competitive/market scans, or literature/paper-stack synthesis. Load-bearing web claims must be grounded
(truth-rights / Rule-8); a model cutoff is never verification evidence.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (question + source plan) | `research` | `chrono-vault` | `scope-decomposition` | privacy overlay if the topic involves personal data |
| **S2** Design (research strategy) | `research`, `synthesizer` | — | `scope-decomposition` | — |
| **S3** Produce (gather → synthesize) | `research`, `synthesizer`, `large-context-analyst`, `growth-and-search-analyst` | `perplexity_search_web`, `xai_search`, `arxiv_search`, `firecrawl`, `codex --search`, `xAI API`, `Brave Search`, `Serper`, `Apify` | `citation-audit`, `technical-seo-audit` | `xAI API` = opt-in metered reasoning/synthesis only — `default=false`, per-task opt-in, provider/endpoint/model allowlist, call/total-token/reasoning-token/output-token/cost ceilings, no blind retry/loop/fallback, typed `needs_tool` failures (401/403→auth, 402→budget, 429→rate_limited); does NOT substitute for the S4 grounding gate — `xai_search` remains the grounded-search tool; `Apify` scraping requires a target-authorization + spend gate |
| **S4** Verify (grounding + claim-check) | `research`, `skeptic`, `cross-family-reviewer` | `perplexity_search_web`, `Google Search grounding` | `claim-verification`, `evidence-chain-preservation` | truth-rights overlay (Rule-8: load-bearing web claims route through a grounding tool — `Google Search grounding` (gemini, subscription) is the first-class grounding route; claim_to_citation=true, date_window=task-scoped, reject_unsupported=true — a claim maps to a returned citation or it is `needs_tool`, not PASS) |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | — | — | review overlay (mandatory for sensitive / load-bearing deliverables) |
| **S6** Ship/Deliver (synthesis) | `synthesizer`, `technical-writer` | `chrono-obsidian` | `citation-audit` | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | `evidence-chain-preservation` | memory overlay (record); sensitive-topic durable-note approval |

**Notes.** `perplexity_search_web` is Claude-lane only (cite the lane); `xai_search`/`arxiv_search` are
all-lane. Grounding is a first-class S4 stage, not review-lane alone: a load-bearing web claim without a
grounding-tool evidence bundle is `needs_tool`/unverifiable — the primary must NOT PASS and hope the reviewer
supplies evidence later. Sensitive topics require operator approval before a durable vault note is recorded.
Competitive/market and literature/arxiv work are the same flow with the tool mix shifted (firecrawl/xai for
market, arxiv for literature).

**Grounding + new gather tools.** `Google Search grounding`
is the first-class subscription grounding route at S4, alongside the metered `perplexity_search_web`. `Brave
Search`/`Serper` add owned-metered search breadth at S3; `Apify` adds owned-metered scraping/extraction but
requires a target-authorization + spend gate. **`xai_search` live-X claim needs a clean re-probe** before any
strengthening — the discovery live-X capture failed twice (stdout loss), so do not add or strengthen a
real-time-X claim until re-probed. **`Perplexity Sonar structured+recency`** (,
schema-observed, not squad-lane-smoked) is a `needs_tool` profile, NOT a live tuple; when it is smoked and
promoted, its use requires the S4 truth-gate tokens (`claim_to_citation=true`, `date_window`,
`reject_unsupported=true`) so every load-bearing claim maps to a returned citation.
