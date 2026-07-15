# chrono-vault — private memory + learning loop

`chrono-vault` is the squad's durable memory. **Markdown notes in a private, off-repo vault are the source of truth; a SQLite FTS5/BM25 index is a disposable, rebuildable derivative.** The write→recall→apply loop is: a lane `record`s a note, later `recall`s it by plain-English query, applies it, and reports back with `record_usage`. Obsidian is an optional human lens over the same markdown; it is never on the recall correctness path.

This document describes the system **as shipped** (see `mcp_server.py`, `notes.py`, `recall.py`, `index.py`, `lifecycle.py`, `clearance.py`, `vaultroot.py`, `autocapture.py`).

## Architecture

- **Notes = truth.** Every memory is one markdown file with JSON-encoded YAML frontmatter, under `<vault>/notes/{attempt,finding,learning}/mem-XXXXXXXXXXXX.md`. Writes are atomic (temp + `fsync` + `os.replace`, `O_NOFOLLOW`/`O_EXCL`, `0o600` files / `0o700` dirs) and tamper-evident (a `note-content-sha256:` ref is embedded in `evidence_refs`).
- **Index = disposable.** `<vault>/index/kg.db` is an FTS5 (`unicode61`) table plus `meta`/`state`/`config`/`usage`/`quarantine` tables, guarded by an exclusive `.kg.lock`. Losing or corrupting it is a non-event — rebuild from the notes. Recall reads it **read-only** under a shared lock.
- **Recall = BM25.** `recall` compiles a natural-language query into a bounded, literal FTS5 query (`query.py`), ranks with weighted `bm25()`, breaks ties by recency, and returns quoted snippets with provenance. No vectors.
- **Obsidian = human-only.** `vault_list` / `vault_get` / `vault_search` reach a local Obsidian REST API for browsing; `vault_search` is explicitly `legacy`/`human_only` and must never be used as a memory-correctness path.

## Setup / configuration

Two environment variables, both read per MCP process:

- **`CHRONO_VAULT_ROOT`** — absolute path to the private vault. Resolution is **fail-closed** (`vaultroot.py`): it errors, and never writes, when the value is unset, still contains an unexpanded `${…}`, is relative, does not name an existing directory, resolves **inside any public git worktree**, or lacks a valid sentinel. The vault root must contain a `.chrono-vault` JSON sentinel: `{"vault_id": "<non-empty>", "schema_version": <int ≥ 1>}`. `bin/launch-squad.sh` exports `CHRONO_VAULT_ROOT` for every lane (currently `$HOME/Obsidian-Chrono`, outside the public repo).
- **`CHRONO_VAULT_CLEARANCE`** — `internal` (default, fail-safe) or `restricted` (`clearance.py`). It is **server-owned** (set on the MCP process, never supplied by a caller). An `internal` instance can read only `internal` notes; a `restricted` instance can read both. `launch-squad.sh` does not currently export it, so lanes default to `internal` until set explicitly.

Vault layout (created on first write):

```
<CHRONO_VAULT_ROOT>/
  .chrono-vault                 # required JSON sentinel {vault_id, schema_version}
  notes/{attempt,finding,learning}/mem-XXXXXXXXXXXX.md
  index/kg.db  (+ .kg.lock, WAL sidecars)   # disposable FTS5 index
```

## API reference

MCP tools (canonical server name `chrono-vault`; legacy aliases `chrono-kg` and `chrono-obsidian` expose a subset for archived role-agents).

**Write**
- `record(note_type, fields) -> {id, path, indexed, index_dirty}` — the canonical writer. `note_type` ∈ `attempt | finding | learning`. `fields` **requires** `title`, `body`, `target`, `attack_class`; **optional** `status` (default `candidate`), `sensitivity` (`internal` default | `restricted`), `program`, `component`, `source_task`, `source_artifact_hash`, `valid_from`, `supersedes`, `aliases`, `keywords`, `evidence_refs`. `schema_version` and `revision` are fixed at `1` for a new note; `valid_to` must be null; unknown fields are rejected. Indexing is best-effort — on failure the note is still written and `index_dirty: true` is returned.
- `record_attempt(role, target, attack_class) -> id` — compatibility wrapper; writes an `attempt` note.
- `record_finding(attempt_id=None, title, severity, description, evidence, target=None, attack_class=None) -> id` — compatibility wrapper with **no FK friction** (`attempt_id` is optional; if omitted, `target` and `attack_class` are required). `severity` ∈ `critical | high | medium | low | info`. `evidence` is stored as an immutable reference (hashed to `legacy-evidence-sha256:` unless already an `artifact:`/`note:`/`sha256:` ref).

**Recall / read**
- `recall(query, filters=None, limit=8) -> {recall_id, tiers_searched, results[]}` — natural-language BM25. `filters` may include `target`, `attack_class`, `component`, `type`, `keywords`, and `status` (default statuses are `candidate` + `verified` — the "active" tier). Each result carries `id`, `score` + `score_components` (bm25/weights/recency tiebreak), a **quoted, delimited** `snippet` (untrusted note content is wrapped in `[BEGIN/END QUOTED UNTRUSTED NOTE]`), `note_link`, `status`, `sensitivity`, and `provenance` (note id, content hash, index generation). Results are clearance-filtered. `recall_id` is a UUID to pass to `record_usage`. Malformed/oversized queries return an empty result with `query_error`, never an exception.
- `get_note(id) -> note` — one complete note by stable ID, clearance-checked.

**Lifecycle (never delete)**
- `set_status(id, new_status, reason, expected_revision, supersedes=None) -> {…note, reason, index_generation}` — compare-and-swap on `expected_revision` (raises on a revision conflict). `new_status` ∈ `candidate | verified | superseded | invalidated | archived`. When `new_status == "superseded"`, `supersedes` (the replacement note id) is required and cannot be the note itself; supersede/superseded-by links are maintained atomically across notes and the index. Notes are **retracted/superseded, never removed**.
- `record_usage(recall_id, note_id, outcome, source_task=None) -> {…}` — apply-feedback. `outcome` ∈ `used | not_useful | incorrect`. Idempotent per `(recall_id, note_id)`; conflicting feedback for the same pair is rejected.

**Diagnostics**
- `health() -> {vault_id, root_valid, schema_version, fts5, note_counts, index_generation, index_dirty, legacy_stores}` — reports the resolved vault identity, FTS5 availability, per-type note counts, whether the index is stale (`index_dirty`), and any leftover legacy KG stores (e.g., a stray `kg.db` or a literal `${CHRONO_VAULT_ROOT}` phantom directory) so drift is visible.

**Human-only Obsidian navigation** (need `OBSIDIAN_REST_API_KEY` + the optional `httpx` dependency; degrade gracefully): `vault_list`, `vault_get`, `vault_search` (legacy/human-only), `obsidian_health_check`.

**Disabled:** `capture_session` / `capture_dispatch` / `capture_review` / `capture_research` return `capture_disabled_pending_canonical_migration`. Auto-capture is done by `autocapture.py` instead (below).

## Usage

- **Record a finding or learning:** call `record("finding", {...})` (or the `record_finding` wrapper) with `title`, `body`, `target`, `attack_class`. New notes land as `candidate`; promote to `verified` with `set_status` once confirmed.
- **Outbox auto-capture:** `bin/outbox-watcher.sh` runs `autocapture.py <TASK-…-response.md>` best-effort when a response lands. It parses the response frontmatter/body into a bounded `learning` note (≤1500-char summary), de-duplicates by `(source_task, source_artifact_hash)`, and — importantly — labels anything from the `security` namespace or `bounty` mode (or any note declaring it) **`restricted`**. This is the write trigger that keeps recall populated without a lane remembering to call `record`.
- **Recall by plain English:** `recall("solana emitter binding forged inbound")` — no query syntax needed; optionally narrow with `filters` (e.g., `{"attack_class": "...", "type": "finding"}`).
- **Apply feedback:** after using a recalled note, call `record_usage(recall_id, note_id, "used" | "not_useful" | "incorrect")` so recall quality can be measured over time.
- **Bounty capture step:** the bounty workflow's learnings-capture step records durable `finding`/`learning` notes (security/bounty content is `restricted`).

## Boundary & sensitivity

- **The vault lives outside the public repo** and resolution is fail-closed: a `CHRONO_VAULT_ROOT` that lands inside a public git worktree is refused, so notes can never be written into the tracked tree.
- **Per-lane clearance:** `restricted` notes are only returned to a `restricted`-clearance MCP instance; `internal` is the safe default.
- **Pre-commit leak guard:** `scripts/hooks/pre-commit` (install: `ln -sf ../../scripts/hooks/pre-commit .git/hooks/pre-commit`) inspects **staged blobs** and blocks a commit that contains a `_state/bounty/` path, a literal `${CHRONO_VAULT_ROOT}` phantom path, a `kg.db*` / `.db-wal` / `.db-shm` artifact, or any file with `sensitivity: restricted` frontmatter. It fails closed if it cannot inspect the staged content.
- **Never `rm` a note.** Supersede or invalidate via `set_status` — a killed/retracted finding is retained as signal.

## Ops

- **Index is derived and rebuildable.** `record` upserts into the index automatically; a stale-schema index is auto-rebuilt on the next write; `health().index_dirty` flags when the index no longer matches the notes on disk.
- **Maintenance functions** live in `index.py` (module functions, not MCP tools): `sync_index()` (incremental — reindex changed notes, quarantine malformed ones, drop deletions), `rebuild_index()` (full atomic rebuild into a temp DB, `PRAGMA integrity_check`, then publish; preserves the `usage` table and bumps the generation), and `index_generation()`. Run them against the module with `CHRONO_VAULT_ROOT` set when `health` reports `index_dirty: true` or after bulk hand-edits in Obsidian.
- **Recall-quality gold eval:** `tests/` carries the plugin's test suite; extend the recall gold cases with real "should have recalled X" examples from live work, and treat a regression there as the gate before changing ranking (or before ever adding vectors).
- **Malformed notes** are quarantined (recorded in the `quarantine` table) rather than crashing an index build; `health` and a rebuild surface them.
