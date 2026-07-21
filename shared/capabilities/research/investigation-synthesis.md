---
id: research/investigation-synthesis
mode: research
title: Multi-source investigation + synthesis (deep-research · competitive · literature)
capability_state: live
state_reason: Every core tool is live — `perplexity_search_web` (synthesized + cited, claude-lane) and `xai_search` (real-time web/X/news) are `lane-live`, `arxiv_search` is `all·yes`, `firecrawl` (claude) is `lane-live` for competitive scraping, and `chrono-vault`/`chrono-obsidian` are `all·yes`. No catalog-absent tool sits on the path. Merges the deep-research/synthesis, competitive/market, and literature/arxiv packs (Sol's condense).
state_evidence: registry rows — perplexity_search_web = `claude·lane-live·metered`, xai_search = `all·lane-live·metered`, arxiv_search = `all·yes·subscription`, firecrawl = `claude·lane-live·metered`, chrono-vault/chrono-obsidian = `all·yes·subscription`; Google Search grounding = `gemini·yes·subscription`; Brave Search / Serper / Apify = `codex·yes·metered`; Perplexity Sonar structured+recency = `codex·partial·metered` (needs_tool profile — not a live tuple).
overlays: [review, truth-rights, privacy, memory]
gates: []
cost_note: The web-research + scraping tools (`perplexity_search_web`, `xai_search`, `firecrawl`, `Brave Search`, `Serper`, `Apify`) are `metered` (API-key billed) and need a budget/rate-limit guard — a hit limit is a typed `needs_tool`/degraded result, never a silent stall; `Apify` scraping additionally requires a target-authorization gate. `Google Search grounding` (gemini) is subscription-tier, not metered. The opt-in `xAI API` direct-reasoning route is also `metered` and carries the full guard: `default=false`, per-task opt-in, provider/endpoint/model allowlist, call/total-token/reasoning-token/output-token/cost ceilings, no blind retry/loop/fallback, typed `needs_tool:auth|budget|rate_limited` (401/403→auth, 402→budget, 429→rate); it is reasoning-only and never substitutes for the S4 grounding gate. `arxiv_search` and chrono-* MCPs are subscription lane-native.
---

**When to use:** a multi-source investigation that ends in a synthesized, cited answer — deep research,
competitive/market scans, or literature/paper-stack synthesis. Load-bearing web claims must be grounded
(truth-rights / Rule-8); a model cutoff is never verification evidence.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (question + source plan) | `research` | `chrono-vault` (all · yes · subscription) | `scope-decomposition` (stub) | privacy overlay if the topic involves personal data |
| **S2** Design (research strategy) | `research`, `synthesizer` | — | `scope-decomposition` (stub) | — |
| **S3** Produce (gather → synthesize) | `research`, `synthesizer`, `large-context-analyst`, `growth-and-search-analyst` | `perplexity_search_web` (claude · lane-live · metered), `xai_search` (all · lane-live · metered), `arxiv_search` (all · yes · subscription), `firecrawl` (claude · lane-live · metered), `codex --search` (codex · yes · subscription), `xAI API` (codex · yes · metered), `Brave Search` (codex · yes · metered), `Serper` (codex · yes · metered), `Apify` (codex · yes · metered) | `citation-audit` (authored), `technical-seo-audit` (authored) | `xAI API` = opt-in metered reasoning/synthesis only — `default=false`, per-task opt-in, provider/endpoint/model allowlist, call/total-token/reasoning-token/output-token/cost ceilings, no blind retry/loop/fallback, typed `needs_tool` failures (401/403→auth, 402→budget, 429→rate_limited); does NOT substitute for the S4 grounding gate — `xai_search` remains the grounded-search tool; `Apify` scraping requires a target-authorization + spend gate |
| **S4** Verify (grounding + claim-check) | `research`, `skeptic`, `cross-family-reviewer` | `perplexity_search_web` (claude · lane-live · metered), `Google Search grounding` (gemini · yes · subscription) | `claim-verification` (authored), `evidence-chain-preservation` (stub) | truth-rights overlay (Rule-8: load-bearing web claims route through a grounding tool — `Google Search grounding` (gemini, subscription) is the first-class grounding route; claim_to_citation=true, date_window=task-scoped, reject_unsupported=true — a claim maps to a returned citation or it is `needs_tool`, not PASS) |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | — | — | review overlay (mandatory for sensitive / load-bearing deliverables) |
| **S6** Ship/Deliver (synthesis) | `synthesizer`, `technical-writer` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored) | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record); sensitive-topic durable-note approval |

**Notes.** `perplexity_search_web` is Claude-lane only (cite the lane); `xai_search`/`arxiv_search` are
all-lane. Grounding is a first-class S4 stage, not review-lane alone: a load-bearing web claim without a
grounding-tool evidence bundle is `needs_tool`/unverifiable — the primary must NOT PASS and hope the reviewer
supplies evidence later. Sensitive topics require operator approval before a durable vault note is recorded.
Competitive/market and literature/arxiv work are the same flow with the tool mix shifted (firecrawl/xai for
market, arxiv for literature).

**Grounding + new gather tools.** `Google Search grounding` (gemini·yes·subscription — verified cited results)
is the first-class subscription grounding route at S4, alongside the metered `perplexity_search_web`. `Brave
Search`/`Serper` add owned-metered search breadth at S3; `Apify` adds owned-metered scraping/extraction but
requires a target-authorization + spend gate. **`xai_search` live-X claim needs a clean re-probe** before any
strengthening — the discovery live-X capture failed twice (stdout loss), so do not add or strengthen a
real-time-X claim until re-probed. **`Perplexity Sonar structured+recency`** (`codex·partial·metered`,
schema-observed, not squad-lane-smoked) is a `needs_tool` profile, NOT a live tuple; when it is smoked and
promoted, its use requires the S4 truth-gate tokens (`claim_to_citation=true`, `date_window`,
`reject_unsupported=true`) so every load-bearing claim maps to a returned citation.
