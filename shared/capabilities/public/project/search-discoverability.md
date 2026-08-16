---
id: project/search-discoverability
mode: project
title: Search / discoverability (on-page SEO · schema · growth)
overlays: [review, truth-rights, memory]
gates: []
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

## Availability in a fresh clone

A zero-key checkout gets this protocol and its validation metadata as documentation; automated dispatch is `needs_tool`. To make it runnable, install and authenticate the selected model CLI, configure every MCP declared by the dispatched specialists, bind the private vault (`CHRONO_VAULT_ROOT`; Kimi also requires its exact vault context), install any required host-local binaries, and provide approved credentials plus a bounded budget for any metered provider named below. After setup, re-run the production role planner and validators on that host; availability remains subject to the narrower gaps and operator gates documented in this card.

**When to use:** improve on-page SEO / discoverability — page audits, structured-data/schema, keyword
clustering, growth recommendations. Authoring is live; **measuring** ranking/traffic impact is `needs_tool`
(no analytics connector) — deliver the on-page/schema work and recommendations, not a measured-impact claim.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (target pages + keywords) | `growth-and-search-analyst` | `firecrawl`, `codex --search` | `keyword-clustering` | — |
| **S3** Produce (on-page + schema) | `growth-and-search-analyst` | `firecrawl`, `chrono-research-arsenal` | `technical-seo-audit`, `structured-data-authoring`, `keyword-clustering` | — |
| **S4** Verify (audit conformance + truth) | `growth-and-search-analyst`, `skeptic`, `content-verifier` | `Google Search grounding` | `technical-seo-audit` | truth-rights overlay — Rule-8 truth gate (published on-page/schema claims grounded; unverifiable ⇒ `needs_tool`, not PASS); measured ranking/traffic impact is `needs_tool` (no analytics connector) |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | — | — | review overlay (if the change ships to a public property) |
| **S6** Ship/Deliver (recommendations) | `growth-and-search-analyst` | `chrono-obsidian` | `structured-data-authoring` | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** The live deliverable is on-page/schema/keyword authoring + audit against the on-page rubric.
**Measured impact (ranking, traffic, conversions) is `needs_tool`** — `Search Console/analytics` is
`catalog-absent`, so this card must not claim it can measure or attribute ranking/traffic outcomes; that
extension is blocked until an analytics connector is cataloged. `firecrawl` is Claude-lane (`metered`,
budget-guarded).

**Google Grounding.**
1. **Google Search Grounding:** Live on the Gemini lane as a first-class, subscription-tier truth-gate verifier. It is available for factual verification and SEO landing page fact-checking only.
