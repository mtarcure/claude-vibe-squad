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

**When to use:** curate the durable knowledge store — deduplicate, repair links, detect contradictions,
purge stale knowledge, and keep the public/private boundary clean. The live store is `chrono-vault` +
`chrono-obsidian`; the legacy `chrono-kg` KG is retired and must not be used.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (hygiene scope) | `knowledge-librarian` | `chrono-vault` | — | privacy overlay (PII in notes) |
| **S3** Produce (dedup / link-fix / contradiction / purge) | `memory-curator`, `knowledge-librarian` | `chrono-vault`, `chrono-obsidian` | `terminology-memory` | `delete` (stale-knowledge purge); privacy overlay |
| **S4** Verify (integrity + capacity) | `knowledge-librarian`, `skeptic` | `chrono-vault` | — | 10k-note / 250 MiB capacity gate; privacy |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | — | — | review overlay; `delete` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** `chrono-vault` (record/recall) + `chrono-obsidian` are the live durable store; **the legacy in-repo
`chrono-kg` SQLite is retired** (CLAUDE.md) and is not a live dependency — its registry row and lane inventories are retired
and should be reconciled to retired/deprecated (flagged here; registry edits are out of this task's scope).
Stale-knowledge purge is a destructive op → operator-gated `delete`. The vault has a **10k-note / 250 MiB
capacity threshold**: approaching it triggers archival/compaction rather than silent overwrite. PII in notes
fires the privacy overlay (`privacy-steward`) and public/private-boundary checks (`memory-curator`).
