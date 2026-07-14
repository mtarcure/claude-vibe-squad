# Memory / Learning Layer Redesign — Implementation Plan

> **For agentic workers:** each Task below is a scoped dispatch packet (Vibe Squad: codex primary for Python/scripts, claude review). Steps use checkbox (`- [ ]`) syntax. TDD per task: write failing test → confirm fail → minimal impl → confirm pass → commit. Each task ends with an independently-verifiable deliverable + its acceptance test(s).

**Goal:** Replace the broken chrono-vault KG (stub `recall`, split DBs, public-repo leak) with a private markdown-as-truth store + a disposable FTS5/BM25 index that closes the write→recall→apply loop and cannot leak.

**Architecture:** Private markdown notes are the source of truth in a fail-closed external vault; a rebuildable SQLite FTS5 index provides BM25 recall over the same corpus; Obsidian is a human-only lens. All ops are atomic + cross-process-locked; sensitivity is enforced server-side per lane; nothing private can be committed.

**Tech Stack:** Python 3 (stdlib only — `sqlite3` FTS5, `os`, `pathlib`, `hashlib`, `fcntl`), MCP (chrono-vault plugin), bash (send-task.sh, watchers, git pre-commit hook).

## Global Constraints (apply to every task)
- **No external dependencies, no vectors/embeddings, no network.** stdlib + SQLite FTS5 only.
- **Private root is mandatory + fail-closed:** never fall back, never `mkdir` a phantom, never resolve inside a public/worktree root.
- **No destructive deletion of notes** without an operator gate + audit tombstone; `forget` = status change.
- **Atomic writes** (temp→flush→fsync→rename→dir-fsync) + a cross-process lock around record / status-change / index ops.
- **TDD + frequent commits;** every task self-contained + testable.
- Spec of record: `docs/superpowers/specs/2026-07-14-memory-learning-redesign-design.md`.

---

## Phase 0 — Contain (MUST land first; unblocks safety)

### Task 0.1 — Remove the whole-tree auto-commit from dispatch
**Files:** Modify `bin/send-task.sh:423-437` (the `git add -A` + commit block); Test: `tests/dispatch/test_no_autocommit.bats` (or a shell test).
**Interfaces:** Produces: dispatch no longer stages/commits unrelated tree state. Later tasks rely on dispatch being commit-free.
- [ ] Step 1 — Write failing test: a dirty untracked file `x.tmp` present; run a `--dry-run` dispatch; assert `x.tmp` remains untracked and no new commit is created.
- [ ] Step 2 — Run, expect FAIL (current code commits it).
- [ ] Step 3 — Replace `git add -A && git commit …` with **either** nothing (preferred) **or** a scoped snapshot of *only* the packet path list. Remove the auto-snapshot commit entirely for v1.
- [ ] Step 4 — Run, expect PASS.
- [ ] Step 5 — Commit `fix(dispatch): stop git add -A auto-commit (P0-10)`.
**Acceptance:** Test 4 (memory ops leave repo git-status clean) precondition holds.

### Task 0.2 — Fail-closed vault root + sentinel + containment
**Files:** Modify `plugins/chrono-vault/mcp_server.py:29-40` (`_vault_root`, `_state_dir`); Create `plugins/chrono-vault/vaultroot.py` (resolution + checks); Test: `plugins/chrono-vault/tests/test_vaultroot.py`.
**Interfaces:**
- Produces: `resolve_vault_root() -> Path` (raises `VaultRootError` on unset/relative/unresolved-`${}`/symlink-escape/public-descendant/missing); `read_sentinel(root) -> {vault_id, schema_version}`; `PUBLIC_ROOTS` list (repo + worktrees).
- Consumes: env `CHRONO_VAULT_ROOT` (must be absolute + exist).
- [ ] Step 1 — Failing tests (table): unset → raises; relative `./x` → raises; literal `${CHRONO_VAULT_ROOT}` → raises; a symlink pointing into the repo → raises; a path under the repo root → raises; a valid external dir w/ sentinel → returns realpath.
- [ ] Step 2 — Run, expect FAIL.
- [ ] Step 3 — Implement `resolve_vault_root`: require env set + absolute; `os.path.realpath`; reject if `str(root).startswith(any PUBLIC_ROOT realpath)`; reject unresolved `${`; require `root.exists()`; **no `mkdir`**; require `<root>/.chrono-vault` sentinel with `vault_id`+`schema_version`.
- [ ] Step 4 — Run, expect PASS.
- [ ] Step 5 — Commit `fix(vault): fail-closed root resolution + sentinel (P0-8/P0-1)`.
**Acceptance:** Tests 3 (bad roots fail before file creation) + partial 1 (vault_id present).

### Task 0.3 — Legacy backup + migrate the 2 findings + parity
**Files:** Create `plugins/chrono-vault/migrate.py`; Test: `plugins/chrono-vault/tests/test_migrate.py`.
**Interfaces:** Produces: `discover_legacy_dbs() -> [Path]`; `export_rows(db) -> [dict]`; `migrate(dry_run=bool) -> report`. Later phases consume the migrated notes.
- [ ] Step 1 — Failing test: given a fixture legacy `kg.db` with 2 findings, `migrate(dry_run=True)` reports 2 finding-notes to create, 0 conflicts; `migrate(dry_run=False)` writes 2 markdown notes (status `verified`) into the vault; a re-run dedups by content hash (0 new).
- [ ] Step 2 — Run, expect FAIL.
- [ ] Step 3 — Implement: checkpoint WAL, copy each discovered db to `backups/`, export `findings`/`attempts` rows, map to note schema, dedup by stable-id then content-hash, write notes. **Legacy DBs stay read-only.**
- [ ] Step 4 — Run, expect PASS. Then run for-real to migrate the **2 Push Chain findings** (SVM forged-inbound, C1 halt) into the private vault.
- [ ] Step 5 — Commit `feat(vault): legacy backup + migration with dedup`.
**Acceptance:** the 2 findings retrievable post-cutover; parity (count/hash) vs legacy export.

---

## Phase 1 — v1 store + loop

### Task 1.1 — Canonical note write (`record`)
**Files:** Create `plugins/chrono-vault/notes.py` (schema + write); Test: `tests/test_notes.py`.
**Interfaces:** Produces:
```python
def record(note_type: str, fields: dict) -> dict:  # -> {"id","path","indexed":bool,"index_dirty":bool}
# note_type in {attempt,finding,learning}; server-gen id "mem-<12hex>";
# defaults status=candidate, created/updated ts, revision=1, sensitivity=internal
```
Schema validated against §4 of the spec (unknown field → reject; bad enum → reject).
- [ ] Step 1 — Failing tests: valid finding → note file exists w/ frontmatter + server id + status `candidate`; missing required field → `SchemaError`; arbitrary dest path in fields → ignored (server picks path under fixed type dir).
- [ ] Step 2 — FAIL.
- [ ] Step 3 — Implement atomic write (temp→fsync→rename→dir-fsync) under `<root>/notes/<type>/<id>.md`; frontmatter via safe YAML dump; content-hash in `evidence`/`revision`.
- [ ] Step 4 — PASS.
- [ ] Step 5 — Commit `feat(vault): canonical markdown note write`.

### Task 1.2 — Disposable FTS5 index (build + lock + rebuild)
**Files:** Create `plugins/chrono-vault/index.py`; Test: `tests/test_index.py`.
**Interfaces:** Produces:
```python
def upsert(note: dict) -> None            # atomic, locked
def rebuild_index() -> dict               # temp db -> integrity-check -> atomic replace
def sync_index() -> dict                  # scan notes: path,size,mtime,hash; index new/changed; quarantine malformed
def index_generation() -> int
```
FTS5 over `(title, body, aliases, target, component, attack_class, tags, evidence_summary)`; a `meta` table for path/mtime/hash/status; weight title/aliases/attack_class > body.
- [ ] Step 1 — Failing tests: record then `recall`-precondition row present; delete index file → `rebuild_index()` reconstructs from notes deterministically (same row count/hashes); a malformed note → quarantined, surfaced, not indexed; concurrent `upsert` (2 procs) → no loss/corruption (fcntl lock).
- [ ] Step 2 — FAIL.
- [ ] Step 3 — Implement with `fcntl` cross-process lock; rebuild into temp db + `PRAGMA integrity_check` + atomic replace; store mtime/hash in `meta`.
- [ ] Step 4 — PASS.
- [ ] Step 5 — Commit `feat(vault): disposable FTS5 index w/ lock + rebuild`.
**Acceptance:** Tests 5,6,7.

### Task 1.3 — `recall` (BM25 + filters + recall_id)
**Files:** Modify `plugins/chrono-vault/mcp_server.py` (replace the LIKE stub); Test: `tests/test_recall.py`.
**Interfaces:** Produces:
```python
def recall(query: str, filters: dict = None, limit: int = 8) -> dict:
# -> {"recall_id","results":[{"id","score","score_components","snippet","note_link",
#     "status","sensitivity","provenance"}], "tiers_searched":["active"]}
# default excludes status in {superseded,invalidated,archived}; structured filters BEFORE BM25;
# recency = tie-breaker only; snippets are QUOTED untrusted text (see 3.2)
```
- [ ] Step 1 — Failing tests: recall by exact identifier (`MsgExecutePayload`) ranks the matching finding #1; `status:invalidated` note excluded by default; filter `attack_class=...` narrows; every result carries a `recall_id` + score_components; invalid FTS syntax handled (no crash, parameterized).
- [ ] Step 2 — FAIL (stub returns []).
- [ ] Step 3 — Implement `SELECT … WHERE fts MATCH ? AND status IN (…) ORDER BY bm25(fts, weights)`; emit `recall_id` (uuid); attach provenance.
- [ ] Step 4 — PASS.
- [ ] Step 5 — Commit `feat(vault): FTS5 BM25 recall replacing LIKE stub`.

### Task 1.4 — `get_note`, `set_status` (CAS), `record_usage`
**Files:** Modify `mcp_server.py`; Test: `tests/test_lifecycle.py`.
**Interfaces:**
```python
def get_note(id: str) -> dict
def set_status(id, new_status, reason, supersedes=None, expected_revision=int) -> dict  # compare-and-swap
def record_usage(recall_id, note_id, outcome: str, source_task=None) -> dict  # used|not_useful|incorrect
```
- [ ] Step 1 — Failing tests: `set_status` with stale `expected_revision` → `RevisionConflict`; supersede sets both `superseded_by` and target's `supersedes`; superseded note drops from default recall; `record_usage` persists a usage row keyed by recall_id.
- [ ] Step 2 — FAIL.
- [ ] Step 3 — Implement CAS on `revision`; reindex on status change; usage table.
- [ ] Step 4 — PASS.
- [ ] Step 5 — Commit `feat(vault): lifecycle (get/set_status CAS/record_usage)`.
**Acceptance:** Tests 9, plus apply-loop signal exists.

### Task 1.5 — Compat wrappers + `health`
**Files:** Modify `mcp_server.py`; Test: `tests/test_compat_health.py`.
**Interfaces:** `record_attempt(...)`/`record_finding(...)` → thin wrappers over `record` (no FK requirement). `health()` returns `{vault_id, root_valid, schema_version, fts5, note_counts, index_generation, index_dirty, legacy_stores}`.
- [ ] Step 1 — Failing tests: `record_finding` with no prior attempt succeeds (FK friction gone); `health` reports the resolved `vault_id` + counts + any legacy store detected.
- [ ] Step 2 — FAIL.
- [ ] Step 3 — Implement wrappers + health.
- [ ] Step 4 — PASS.
- [ ] Step 5 — Commit `feat(vault): compat wrappers + health`.
**Acceptance:** Tests 1,2 (cross-lane vault_id + record→recall same id).

---

## Phase 2 — Write-in / Apply-out integration

### Task 2.1 — outbox-watcher auto-capture hook
**Files:** Modify `bin/outbox-watcher.sh`; Create `plugins/chrono-vault/autocapture.py`; Test: `tests/test_autocapture.py`.
**Interfaces:** Produces: on each new `*-response.md`, extract `{verdict, specialist, task, artifacts}` → `record("finding"|"learning", …, status=candidate)`. Idempotent (dedup by source_task+hash).
- [ ] Steps — failing test: dropping a fixture response file triggers exactly one candidate note; re-drop → 0 new. Implement; PASS; commit `feat: outbox auto-capture into memory`.

### Task 2.2 — Bounty "capture learnings" phase + apply-citation convention
**Files:** Modify `shared/modes/bounty.md` (+ a `capture` phase); `shared/protocol.md` (citation convention). Test: doc-lint (grep the phase + convention exist).
- [ ] Add a Phase-11 capture step (record verified findings + KILLs + process learnings); document that downstream packets cite consumed `mem-…` IDs so `record_usage` can close the loop. Commit `docs: bounty capture phase + apply-citation`.

---

## Phase 3 — Security floor + boundary

### Task 3.1 — Server-side per-lane clearance
**Files:** Modify `mcp_server.py` (recall/get output gating); Test: `tests/test_clearance.py`.
**Interfaces:** Consumes a per-instance/lane clearance (env/config, not caller-supplied). `restricted` notes/evidence excluded from snippets unless the lane's clearance allows; a caller flag can never raise clearance.
- [ ] Failing test: a `restricted` finding is NOT returned in snippet form to a lane below clearance; is returned to an authorized lane. Implement; PASS; commit `feat(vault): server-side sensitivity clearance (P0)`.
**Acceptance:** Test 10.

### Task 3.2 — Untrusted-recall (quote + provenance + bounds)
**Files:** Modify recall snippet formatting; Test: `tests/test_untrusted.py`.
- [ ] Failing test: a note whose body contains `"IGNORE PREVIOUS INSTRUCTIONS…"` is returned as clearly-delimited quoted data with provenance + a size bound, never as bare instruction text. Implement; PASS; commit `feat(vault): treat recalled text as untrusted`.
**Acceptance:** Test 11.

### Task 3.3 — `capture_*` under policy
**Files:** Modify `mcp_server.py:259-317` (capture tools); Test: `tests/test_capture_policy.py`.
- [ ] Failing test: `capture_session/dispatch/review/research` writes go through the same fail-closed root + schema (or are disabled). Implement; PASS; commit `fix(vault): capture_* under root/schema policy`.

### Task 3.4 — gitignore + pre-commit sensitivity hook
**Files:** Modify `.gitignore`; Create `.git/hooks/pre-commit` (+ tracked `scripts/hooks/pre-commit`); Test: `tests/test_precommit.bats`.
- [ ] Failing test: staging a file with `sensitivity: restricted` (or under a bounty path, or a `kg.db`) → commit refused. Implement hook (scan staged files); install; PASS; commit `feat(security): pre-commit sensitivity/leak guard`.
**Acceptance:** Test 14 (hook rejects synthetic restricted file) + Test 4.

---

## Phase 4 — Decommission legacy/dead code (§10 — no orphans)

### Task 4.1 — Remove obsolete paths
**Files:** `plugins/chrono-vault/mcp_server.py` (delete the LIKE `recall` body, phantom fallback, split write paths); Test: existing suite still green.
- [ ] Delete dead code; run full test suite; commit `refactor(vault): remove LIKE stub + phantom fallback`.

### Task 4.2 — Repoint/retire `vault_search`; reconcile dangling tool refs
**Files:** `mcp_server.py` (`vault_search` → mark human-only or route to `recall`); `shared/tool-catalog.md`, `shared/specialist-runtime-map.tsv`, specialist briefs (remove `chrono-vault:kg_query`, fix `chrono-catalog.list_skills`).
- [ ] Grep all references; remove/implement; assert `learning` correctness never depends on Obsidian REST; commit `refactor: reconcile dangling KG tool refs (P0-11)`.

### Task 4.3 — No-orphans audit
**Files:** Create `scripts/audit-orphans.sh`; Test: it exits non-zero if any removed symbol/tool still has a caller.
- [ ] Implement audit (grep removed function/tool names across code+briefs+docs); run → 0 orphans; commit `test: no-orphans audit for memory decommission`.

---

## Phase 5 — Acceptance suite (the 14 tests)
Wire the spec's §11 tests 1-14 as an integration suite `plugins/chrono-vault/tests/test_acceptance.py` (+ the bats leak/precommit ones). Gate cutover on green. Task per unmet test; commit `test: memory redesign acceptance suite`.

---

## Self-Review
- **Spec coverage:** §3 arch→T1.1-1.3; §4 schema→T1.1; §5 API→T1.1-1.5; §6 loop→T2.1-2.2+T1.3/1.4; §7 security→T0.2,3.1-3.3; §8 boundary→T0.1,3.4; §9 migration→T0.3; §10 decommission→T4.1-4.3; §11 tests→T5 + per-task; §12 rollout = phase order. No gap found.
- **Placeholder scan:** none — each task has concrete files, signatures, and a named failing test. (Impl code is left to the TDD implementer per Vibe Squad dispatch model, but every task's *interface + test* is concrete.)
- **Type consistency:** `record`→`{id,indexed,index_dirty}`, `recall`→`{recall_id,results[…]}`, `set_status`(CAS `expected_revision`), `record_usage(recall_id,note_id,outcome)` — names consistent across T1.1-1.5, 2.1, 3.1-3.2.

## Execution (Vibe Squad dispatch)
This plan is decomposed into scoped packets. Recommended dispatch order = phase order; Phase 0 tasks are blocking. Each task → codex (`ai-engineer`/`backend-engineer` for Python, `devops-engineer` for scripts/hooks) with claude (`code-reviewer`) review; each returns with its acceptance test green. I'll dispatch task-by-task, review between, and gate cutover on the Phase-5 suite.
