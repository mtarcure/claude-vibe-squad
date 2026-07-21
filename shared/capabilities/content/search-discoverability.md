---
id: content/search-discoverability
mode: content
title: Search / discoverability (on-page SEO · schema · growth)
capability_state: live
state_reason: On-page SEO, structured-data/schema authoring, and keyword work are live — `firecrawl` (page/competitor fetch, claude·lane-live) and `chrono-research-arsenal` (all·lane-live) back it, no catalog-absent tool on the authoring path. **Measured** ranking/traffic impact is `needs_tool` — no analytics connector is cataloged (Search Console/analytics = `catalog-absent`); this card authors on-page/schema work but does NOT claim to measure impact.
state_evidence: registry rows — firecrawl = `claude·lane-live·metered`, chrono-research-arsenal = `all·lane-live·subscription`, chrono-obsidian/chrono-vault = `all·yes·subscription`. Search Console/analytics = `unknown·catalog-absent·unknown` (→ measured impact is `needs_tool`, not cited on the core path).
overlays: [review, memory]
gates: []
cost_note: `firecrawl` fetch is `metered` (API-key billed) and needs a budget/rate-limit guard; research-arsenal + chrono-* MCPs are subscription. No analytics connector is billed here because none is cataloged.
---

**When to use:** improve on-page SEO / discoverability — page audits, structured-data/schema, keyword
clustering, growth recommendations. Authoring is live; **measuring** ranking/traffic impact is `needs_tool`
(no analytics connector) — deliver the on-page/schema work and recommendations, not a measured-impact claim.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (target pages + keywords) | `growth-and-search-analyst` | `firecrawl` (claude · lane-live · metered), `codex --search` (codex · yes · subscription) | `keyword-clustering` (authored) | — |
| **S3** Produce (on-page + schema) | `growth-and-search-analyst` | `firecrawl` (claude · lane-live · metered), `chrono-research-arsenal` (all · lane-live · subscription) | `technical-seo-audit` (authored), `structured-data-authoring` (authored), `keyword-clustering` (authored) | — |
| **S4** Verify (audit conformance) | `growth-and-search-analyst`, `skeptic` | `Google Search grounding` (gemini · yes · subscription) | `technical-seo-audit` (authored) | measured ranking/traffic impact is `needs_tool` (no analytics connector) — verify on-page conformance and perform fact-checks only |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | — | — | review overlay (if the change ships to a public property) |
| **S6** Ship/Deliver (recommendations) | `growth-and-search-analyst` | `chrono-obsidian` (all · yes · subscription) | `structured-data-authoring` (authored) | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** The live deliverable is on-page/schema/keyword authoring + audit against the on-page rubric.
**Measured impact (ranking, traffic, conversions) is `needs_tool`** — `Search Console/analytics` is
`catalog-absent`, so this card must not claim it can measure or attribute ranking/traffic outcomes; that
extension is blocked until an analytics connector is cataloged. `firecrawl` is Claude-lane (`metered`,
budget-guarded).

**Google Grounding.**
1. **Google Search Grounding:** Live on the Gemini lane as a first-class, subscription-tier truth-gate verifier. It is available for factual verification and SEO landing page fact-checking only.
