---
id: research/investigation-synthesis
mode: research
title: Multi-source investigation + synthesis (deep-research · competitive · literature)
capability_state: live
state_reason: Every core tool is live — `perplexity_search_web` (synthesized + cited, claude-lane) and `xai_search` (real-time web/X/news) are `lane-live`, `arxiv_search` is `all·yes`, `firecrawl` (claude) is `lane-live` for competitive scraping, and `chrono-vault`/`chrono-obsidian` are `all·yes`. No catalog-absent tool sits on the path. Merges the deep-research/synthesis, competitive/market, and literature/arxiv packs (Sol's condense).
state_evidence: registry rows — perplexity_search_web = `claude·lane-live·metered`, xai_search = `all·lane-live·metered`, arxiv_search = `all·yes·subscription`, firecrawl = `claude·lane-live·metered`, chrono-vault/chrono-obsidian = `all·yes·subscription`.
overlays: [review, truth-rights, privacy, memory]
gates: []
cost_note: The web-research + scraping tools (`perplexity_search_web`, `xai_search`, `firecrawl`) are `metered` (API-key billed) and need a budget/rate-limit guard — a hit limit is a typed `needs_tool`/degraded result, never a silent stall. `arxiv_search` and chrono-* MCPs are subscription lane-native.
---

**When to use:** a multi-source investigation that ends in a synthesized, cited answer — deep research,
competitive/market scans, or literature/paper-stack synthesis. Load-bearing web claims must be grounded
(truth-rights / Rule-8); a model cutoff is never verification evidence.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (question + source plan) | `research` | `chrono-vault` (all · yes · subscription) | `scope-decomposition` (stub) | privacy overlay if the topic involves personal data |
| **S2** Design (research strategy) | `research`, `synthesizer` | — | `scope-decomposition` (stub) | — |
| **S3** Produce (gather → synthesize) | `research`, `synthesizer`, `large-context-analyst`, `growth-and-search-analyst` | `perplexity_search_web` (claude · lane-live · metered), `xai_search` (all · lane-live · metered), `arxiv_search` (all · yes · subscription), `firecrawl` (claude · lane-live · metered) | `citation-audit` (authored), `technical-seo-audit` (authored) | — |
| **S4** Verify (grounding + claim-check) | `research`, `skeptic`, `cross-family-reviewer` | `perplexity_search_web` (claude · lane-live · metered) | `claim-verification` (authored), `evidence-chain-preservation` (stub) | truth-rights overlay (Rule-8: load-bearing web claims route through a grounding tool; unverifiable ⇒ `needs_tool`, not PASS) |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | — | — | review overlay (mandatory for sensitive / load-bearing deliverables) |
| **S6** Ship/Deliver (synthesis) | `synthesizer`, `technical-writer` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored) | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record); sensitive-topic durable-note approval |

**Notes.** `perplexity_search_web` is Claude-lane only (cite the lane); `xai_search`/`arxiv_search` are
all-lane. Grounding is a first-class S4 stage, not review-lane alone: a load-bearing web claim without a
grounding-tool evidence bundle is `needs_tool`/unverifiable — the primary must NOT PASS and hope the reviewer
supplies evidence later. Sensitive topics require operator approval before a durable vault note is recorded.
Competitive/market and literature/arxiv work are the same flow with the tool mix shifted (firecrawl/xai for
market, arxiv for literature).
