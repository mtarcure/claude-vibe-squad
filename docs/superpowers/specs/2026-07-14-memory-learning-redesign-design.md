# Memory / Learning Layer Redesign — Design Spec

- **Date:** 2026-07-14
- **Status:** direction approved (operator); spec pending sign-off
- **Sources:** Fable + Sol system reviews & memory critiques, landscape analysis, KG-leak post-mortem
- **Approved shape:** own-it markdown-first store + disposable FTS5 index; Fable's feature-cuts + Sol's security floor; vectors/graph/bi-temporal deferred behind evidence.

## 1. Problem
The write→recall→apply loop is broken and unsafe: `recall` is a `LIKE` stub; `record_finding` writes SQLite that `vault_search` (Obsidian) can't see; an unexpanded `${CHRONO_VAULT_ROOT}` split writes across phantom in-repo DBs; and the KG lived inside the **public** repo, leaking bounty findings. Root cause: no canonical store and no enforced public/private boundary. The only learning loop that actually works today is skills + file-memory.

## 2. Goals / Non-goals
**Goals:** a working write→recall→apply loop; private-by-construction; zero external/vector deps; bounded growth; re-leak-proof; and removal of the legacy/dead paths this obsoletes.
**Non-goals (v1, deferred behind evidence):** vectors/embeddings, mem0/GraphRAG, full bi-temporality, semantic contradiction detection, auto-pruning/tiered retention, remote-git storage, file-watchers, Obsidian-as-correctness-dependency, periodic `VACUUM`, universal recency decay.

## 3. Architecture
- **Private markdown vault = source of truth** (notes are inspectable, hand-editable, git-diffable in a *private* store).
- **SQLite FTS5 index = disposable, rebuildable** from the markdown. Same corpus recall + `vault_search` read → no split.
- **Obsidian = human lens only** (graph/backlinks/browse) — never a correctness dependency; core `record`/`recall` work with Obsidian closed.
- **Storage:** an external **local directory** with a fail-closed absolute root + an independently-configured **encrypted backup**. A private git repo is *optional history*, never the trust boundary or the backup.

## 4. Note schema (merged Fable + Sol)
A note = YAML frontmatter (metadata below) **+ a markdown body** (the actual finding/learning text). `title` (frontmatter) and `body` (the markdown content after the frontmatter) are the primary indexed content.
```yaml
schema_version: 1
id: mem-<server-generated>          # immutable, in frontmatter (not filename)
title: <one-line summary>           # indexed, high weight
type: attempt | finding | learning
status: candidate | verified | superseded | invalidated | archived
target: <canonical target>
program: <program | none>
component: <component | none>
attack_class: <controlled value>
sensitivity: internal | restricted   # NOTE: a label, NOT access control (see §7)
source_task: <task id | none>
source_artifact_hash: <hash | none>
created_at: <ts>
updated_at: <ts>
valid_from: <ts/version | none>
valid_to: none                       # single-temporal only; no transaction-time in v1
supersedes: []
superseded_by: none
aliases: []                          # cheap "poor-man's embedding" for paraphrase recall
keywords: []
evidence_refs: []                    # immutable refs/hashes, NOT raw secrets/PII blobs
revision: 1
```
Agent-written notes default `status: candidate`; promotion to `verified` requires explicit evidence/review provenance. Evidence = bounded summaries + immutable references, never raw secrets.

## 5. API (chrono-vault MCP)
- `record(note_type, fields)` — frictionless: server-gen ID, **no required prior `attempt`** (drop today's FK friction), atomic note write then transactional index update.
- `recall(query, filters)` — FTS5 **BM25** over the same corpus; **default filter `status in (verified, candidate)` excluding superseded/invalidated**; structured filters applied before ranking; returns ranked snippets + stable IDs + relative links + provenance + status + **score components** + a **`recall_id`**.
- `get_note(id)`.
- `set_status(id, new_status, reason, supersedes, expected_revision)` — **compare-and-swap** on revision.
- `sync_index` / `rebuild_index` — deterministic rebuild into a temp DB, integrity-check, atomic replace.
- `record_usage(recall_id, note_id, outcome=used|not_useful|incorrect, source_task)` — the **apply-feedback** primitive.
- `health` — `vault_id`, root-valid flag, schema version, FTS5 availability, note counts, index generation/freshness, dirty/error state, legacy-store detection.
- **Compat wrappers:** `record_attempt` / `record_finding` become thin wrappers over `record` (or are removed if unused — see §10).

## 6. The loop (write-in + apply-out) — the real fix
Both critiques' #1 gap: the store/recall were fine but the *loop ends* were missing.
- **Write-in (Fable):** frictionless `record` **+ an outbox-watcher auto-capture hook** (each `*-response.md` verdict → a `candidate` note) **+ a bounty Phase-11 "capture learnings" step.** Recall quality is downstream of write coverage.
- **Recall paraphrase aid:** `aliases`/`keywords` frontmatter (LLM-authored on write) closes most vocabulary-mismatch gaps at ~zero cost; weight title/aliases/attack_class above body; recency is a **tie-breaker**, not decay.
- **Apply-out (Sol):** `recall` emits `recall_id`; downstream task artifacts cite consumed note IDs; `record_usage(outcome)` closes the loop and feeds invalidation.
- **Curation:** `forget` = **invalidate/supersede (preserve history), never `rm`**; destructive `redact/purge` is operator-gated with an audit tombstone.

## 7. Security floor (Sol — load-bearing after the leak)
- **Mandatory external private root; NO fallback, NO lazy `mkdir`.** Resolve with `realpath`; reject unresolved `${...}`, relative roots, symlink escapes, and any root under a known public/worktree root.
- **Sentinel** file carrying `vault_id` + schema version; all lanes must report the same `vault_id` in `health`.
- `0700`/`0600` modes, restrictive umask.
- **Server-side clearance per lane/MCP instance** — a `sensitivity:` *label is not access control*; a caller-supplied flag must never raise its own clearance. Default restricted evidence out of snippets.
- **Treat recalled text as quoted untrusted data** (stored markdown is a prompt-injection channel) with provenance/status/trust metadata and size bounds; never splice as executable instructions.
- **Bring the `capture_*` tools under the same root/schema policy** (they persist prompts/outputs via a separate code path today) — or disable until migrated.
- Atomic writes: temp file in destination dir → flush → file-`fsync` → atomic replace → dir-`fsync`. Cross-process lock around record / status-change / manual-edit sync / index rebuild.

## 8. Public/private boundary (git is not the only path)
- Store lives **outside** the public repo.
- Root `.gitignore` excludes the private vault path, `_state/bounty/**`, `**/kg.db*`.
- **Pre-commit hook** refuses any staged file labeled `sensitivity: restricted|bounty` or under bounty paths — *regardless of which script staged it* (belt + suspenders; removing `git add -A` alone is insufficient).
- **Sync-layer:** if Obsidian syncs the vault (Sync/iCloud/Drive), the vault must be private there too.
- **No secondary copies:** restricted recall snippets must not land in public task packets, outboxes, transcripts, or logs.

## 9. Phase 0 — contain + migrate (before feature work)
1. Remove the whole-tree **`git add -A` auto-commit** from `send-task.sh` (P0-10); stage only explicit snapshot paths.
2. Fix root resolution to **fail-closed** so no new phantom store can be created (P0-8/P0-1).
3. Checkpoint every legacy WAL, back up every discovered `kg.db`, export rows, produce a dry-run migration report.
4. **Migrate the 2 Push Chain findings** (held verbatim) into the new private store; re-record as `verified` findings.
5. Dedup by stable ID first, content hash second; **never silently merge contradictory findings** (surface candidates).
6. Keep legacy stores **read-only** until cross-lane count/hash + recall parity passes.

## 10. Decommissioning / dead-code removal (operator requirement — no orphans)
Everything this redesign obsoletes is removed or converted; a "no orphans" audit runs at the end.
- **Remove:** the `recall` `LIKE` stub; the phantom-root fallback + lazy-`mkdir` in `plugins/chrono-vault/mcp_server.py:29-40`; the split/duplicate SQLite write paths.
- **Convert:** `record_attempt`/`record_finding` → thin compat wrappers over `record` (or delete if no live callers); `vault_search`'s KG use → repointed to `recall`/`get_note`, or explicitly marked **human-only legacy** and dropped as a learning dependency.
- **Reconcile with the runtime map / briefs:** remove or implement dangling tool references — e.g. `chrono-vault:kg_query` and `chrono-catalog.list_skills` that specialist briefs require but don't exist (Sol P0-11).
- **Already done:** in-repo phantom `${CHRONO_VAULT_ROOT}` dirs purged + gitignored.
- **Audit:** grep for callers of every removed function/tool; assert none remain in code, specialist briefs, `tool-catalog.md`, or mode docs.

## 11. Acceptance tests (Sol's 13 + dead-code + leak)
1. All lanes report the same `vault_id` and index generation.
2. Record in one lane; recall/`get` the same ID from every authorized lane.
3. Unset/relative/unresolved/symlinked/nonexistent/public-descendant roots **fail before creating files**.
4. Memory operations leave the public repo unchanged (git status clean).
5. Concurrent records lose no notes and don't corrupt the index.
6. A manual valid note edit becomes searchable after `sync_index`; malformed edits quarantined + surfaced.
7. Missing/corrupt/stale index rebuilds deterministically from notes.
8. Simulated index failure preserves the note and reports `index_dirty`.
9. Invalidated/superseded notes drop from default recall but remain explicitly retrievable.
10. Sensitivity clearance enforced at recall/`get` output (label alone never leaks restricted content cross-lane).
11. Recalled instruction-like text stays quoted data (no prompt-injection execution).
12. A real-query eval (gold set from Push Chain) meets an agreed recall@5 threshold **before** vectors are considered.
13. Backup restoration reproduces note counts/hashes + a working index.
14. **No orphans:** every removed function/tool has zero remaining callers in code/briefs/docs; pre-commit hook rejects a synthetic `sensitivity: restricted` staged file.

## 12. Rollout
Phase 0 (contain + migrate) → v1 (store + loop + security floor + decommission) → measure recall (eval) → only then consider deferred items. Each phase gated by its acceptance tests.
