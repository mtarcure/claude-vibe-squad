---
id: outreach/prospecting-outreach
mode: outreach
title: Prospecting / outreach (client-acquisition · job-search · general prospecting)
capability_state: live
state_reason: Finding, qualifying, and DRAFTING outreach (research, list-building, personalized messages, follow-up copy) is backed by live tools — `chrono-research-arsenal` (all·lane-live), `firecrawl` (claude·lane-live), `chrono-vault` (all·yes). No catalog-absent tool is load-bearing on the draft path. The actual SEND is `needs_tool`/operator-gated (Gmail `partial`, outreach bridge dry-run only) and is NOT claimed live.
state_evidence: registry rows — chrono-research-arsenal = `all·lane-live·subscription`, firecrawl = `claude·lane-live·metered`, chrono-vault = `all·yes·subscription`. Gmail = `claude·partial`, outreach bridge = `local·partial` (→ live send is `needs_tool`, not cited on the core path).
overlays: [review, privacy, memory]
gates: [live_outreach]
cost_note: Research + drafting is subscription lane-native (research-arsenal, chrono-vault); `firecrawl` prospect enrichment is `metered` (API-key billed) and needs a budget/rate-limit guard. Sends are per-message operator-gated (`live_outreach`), not billed on the drafting path.
---

**When to use:** client-acquisition / freelance prospecting, job-search applications, or general outreach —
find + qualify targets, then draft personalized messages and follow-ups. **Drafting/research is live; the SEND
is operator-gated `needs_tool`** — every message needs per-message operator approval (`live_outreach`).

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (ICP + targets + goals) | `research`, `growth-and-search-analyst`, `finance-analyst` | `chrono-research-arsenal` (all · lane-live · subscription) | `scope-decomposition` (stub) | privacy overlay (prospect PII) |
| **S2** Design (qualify + enrich list) | `research`, `data-extraction-engineer`, `privacy-steward` | `firecrawl` (claude · lane-live · metered), `chrono-research-arsenal` (all · lane-live · subscription) | `technical-seo-audit` (authored), `citation-audit` (authored) | privacy overlay (PII minimization) |
| **S3** Produce (draft messages + follow-ups) | `copywriter`, `brand-voice`, `editor` | `chrono-research-arsenal` (all · lane-live · subscription) | `citation-audit` (authored) | — |
| **S4** Verify (personalization + accuracy) | `editor`, `skeptic` | — | `citation-audit` (authored) | privacy overlay; no fabricated claims about the prospect |
| **S5** Review/Gate (send approval) | `skeptic`, `operator`, `personal-ops` | — | — | review overlay; **`live_outreach` — per-message operator "go"** (send is `needs_tool`/operator-gated) |
| **S6** Ship/Deliver (staged drafts) | `personal-ops` | `chrono-obsidian` (all · yes · subscription) | — | send is operator-gated (`needs_tool`); bridge is dry-run only |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** **The live scope is find → qualify → draft, not send.** `Gmail` is `partial` and the outreach
bridge is dry-run only, so a live automated send is `needs_tool` and is not claimed — `live_outreach` is
per-message operator approval before any real send. Prospect PII fires the privacy overlay (`privacy-steward`);
minimize retained personal data and never fabricate facts about a prospect. Job-search and general-prospecting
are the same flow with the specialist mix shifted (drop `finance-analyst`; job-search adds tailored-application
drafting).
