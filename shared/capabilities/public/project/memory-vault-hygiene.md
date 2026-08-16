---
id: project/memory-vault-hygiene
mode: project
title: Memory / vault hygiene (durable-knowledge curation)
overlays: [review, privacy, memory]
gates: [delete]
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

**When to use:** curate durable knowledge — deduplicate, repair links, detect contradictions, apply reviewed
lifecycle transitions, and keep the public/private boundary clean. `chrono-vault` is the canonical
Markdown-backed store and recall path; `chrono-obsidian` is an optional human browse lens. Legacy KG material
is migration input, never a live recall path.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (hygiene scope) | `knowledge-librarian` | `chrono-vault` | — | privacy overlay (PII in notes) |
| **S3** Produce (dedup / link-fix / contradiction / lifecycle) | `memory-curator`, `knowledge-librarian` | `chrono-vault`, `chrono-obsidian` | `terminology-memory` | `delete` only for separately approved physical removal; privacy overlay |
| **S4** Verify (integrity + capacity) | `knowledge-librarian`, `skeptic` | `chrono-vault` | — | 10k-note / 250 MiB capacity gate; privacy |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | — | — | review overlay; `delete` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** `chrono-vault` owns record, recall, and lifecycle over canonical private Markdown; its FTS5/BM25
index is disposable. `chrono-obsidian` may help a human browse the same material but is never correctness
authority. Legacy KG material is retired from runtime but remains a protected P4 migration source; it is not
removed until migration, restore, stability, and separate approval pass. Wrong or stale notes move to
`invalidated`, `superseded`, or `archived`; they are not silently erased. The vault has a **10k-note / 250 MiB
capacity threshold**: approaching it triggers an operator-reviewed archival/compaction proposal. PII in notes
fires the privacy overlay (`privacy-steward`) and public/private-boundary checks (`memory-curator`).
