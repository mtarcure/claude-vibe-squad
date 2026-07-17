---
id: maintenance/memory-vault-hygiene
mode: maintenance
title: Memory / vault hygiene (durable-knowledge curation)
capability_state: live
state_reason: Vault curation — dedup, link-integrity repair, contradiction detection, stale-knowledge purge — runs on `chrono-vault` (`all·yes`) + `chrono-obsidian` (`all·yes`), the live durable store. The legacy in-repo `chrono-kg` SQLite is RETIRED (CLAUDE.md; the chrono-vault record/recall loop replaced it) and is NOT a live dependency. Stale-note purge is `delete`-gated; the vault has a 10k-note / 250 MiB capacity threshold.
state_evidence: registry rows — chrono-vault/chrono-obsidian = `all·yes·subscription`. `chrono-kg` is retired per CLAUDE.md (record/recall on chrono-vault is the durable store) and is deliberately not cited as a live tool despite a stale `all·yes` registry row (flagged for registry reconciliation; out of this task's write scope).
overlays: [review, privacy, memory]
gates: [delete]
cost_note: subscription lane-native (chrono-vault / chrono-obsidian). No metered provider. The retired `chrono-kg` is not used.
---

**When to use:** curate the durable knowledge store — deduplicate, repair links, detect contradictions,
purge stale knowledge, and keep the public/private boundary clean. The live store is `chrono-vault` +
`chrono-obsidian`; the legacy `chrono-kg` KG is retired and must not be used.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (hygiene scope) | `knowledge-librarian` | `chrono-vault` (all · yes · subscription) | — | privacy overlay (PII in notes) |
| **S3** Produce (dedup / link-fix / contradiction / purge) | `memory-curator`, `knowledge-librarian` | `chrono-vault` (all · yes · subscription), `chrono-obsidian` (all · yes · subscription) | `terminology-memory` (authored) | `delete` (stale-knowledge purge); privacy overlay |
| **S4** Verify (integrity + capacity) | `knowledge-librarian`, `skeptic` | `chrono-vault` (all · yes · subscription) | — | 10k-note / 250 MiB capacity gate; privacy |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer` | — | — | review overlay; `delete` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** `chrono-vault` (record/recall) + `chrono-obsidian` are the live durable store; **the legacy in-repo
`chrono-kg` SQLite is retired** (CLAUDE.md) and is not a live dependency — its `all·yes` registry row is stale
and should be reconciled to retired/deprecated (flagged here; registry edits are out of this task's scope).
Stale-knowledge purge is a destructive op → operator-gated `delete`. The vault has a **10k-note / 250 MiB
capacity threshold**: approaching it triggers archival/compaction rather than silent overwrite. PII in notes
fires the privacy overlay (`privacy-steward`) and public/private-boundary checks (`memory-curator`).
