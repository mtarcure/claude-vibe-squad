---
id: project/prospecting-outreach
mode: project
title: Prospecting / outreach (client-acquisition · job-search · general prospecting)
overlays: [review, privacy, memory]
gates: [live_outreach]
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

**When to use:** client-acquisition / freelance prospecting, job-search applications, or general outreach —
find + qualify targets, then draft personalized messages and follow-ups. **Drafting/research is live; the SEND
is operator-gated `needs_tool`** — every message needs per-message operator approval (`live_outreach`).

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (ICP + targets + goals) | `research`, `growth-and-search-analyst` | `chrono-research-arsenal` | `scope-decomposition` | privacy overlay (prospect PII) |
| **S2** Design (qualify + enrich list) | `research`, `data-extraction-engineer`, `privacy-steward` | `firecrawl`, `chrono-research-arsenal`, `codex --search` | `technical-seo-audit`, `citation-audit` | privacy overlay (PII minimization) |
| **S3** Produce (draft messages + follow-ups) | `brand-voice`, `editor` | `chrono-research-arsenal` | `citation-audit` | — |
| **S4** Verify (personalization + accuracy) | `editor`, `skeptic` | — | `citation-audit` | privacy overlay; no fabricated claims about the prospect |
| **S5** Review/Gate (send approval) | `skeptic`, `operator` | — | — | review overlay; **`live_outreach` — per-message operator "go"** (send is `needs_tool`/operator-gated) |
| **S6** Ship/Deliver (staged drafts) | `editor` | `chrono-obsidian` | — | send is operator-gated (`needs_tool`); bridge is dry-run only |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** **The live scope is find → qualify → draft, not send.** `Gmail` is `partial` and the outreach
bridge is dry-run only, so a live automated send is `needs_tool` and is not claimed — `live_outreach` is
per-message operator approval before any real send. Prospect PII fires the privacy overlay (`privacy-steward`);
minimize retained personal data and never fabricate facts about a prospect. Job-search and general-prospecting
are the same flow with the specialist mix shifted (job-search adds tailored-application drafting).

**Roster consolidation 2026-08-14 (P13.64):** the dedicated finance and personal-operations roles were retired
(zero dispatches since 2026-05-02, no successors). Budget/ROI framing stays inside S1 (`research` +
`growth-and-search-analyst`), with material cost questions surfaced to the `operator`; `editor` — already the
S4 verifier — stages the S6 draft handoff. Send approval was always the `operator`'s and is unchanged.
