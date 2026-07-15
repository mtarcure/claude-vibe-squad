---
id: TASK-2026-07-14-1826-8fd0baa1-response
in_response_to: TASK-2026-07-14-1826-8fd0baa1
from: gpt-codex
to: chrono
to_lead: chrono
type: RESULT
status: needs_review
specialist: systems-engineer
review_model: claude
mandatory_review: true
capability_gap: none
---

# Phase 4 — legacy decommission and no-orphans audit

## Outcome

Phase 4 implementation and authorized verification are complete. The registered `systems_engineer` adapter executed the specialist work; there is no specialist capability gap.

### Removed or retired

- Removed eager `httpx` loading. Core `mcp_server` import now succeeds when `httpx` is unavailable; the optional package is loaded only when a human Obsidian REST tool is invoked.
- Marked `vault_search` human-only legacy in its tool documentation and every response shape. Canonical learning and recall continue through markdown notes plus FTS5 (`record_note` / `recall_notes`) without Obsidian.
- Removed obsolete split-SQL helpers and tools: `_vault_root`, `_state_dir`, `_connect`, `_init_kg_schema`, `list_attempts`, and its KG alias. The remaining `record_attempt` and `record_finding` compatibility paths call canonical `record_note`; no duplicate SQLite write path remains.
- Removed the empty `chrono-catalog.list_skills` alias/server. Unknown or retired namespaces now exit non-zero instead of silently starting the canonical MCP under the wrong namespace.
- Reconciled live tool contracts: removed `chrono-catalog`, replaced eight `chrono-vault:kg_query` bindings with `chrono-vault:recall`, removed stale `read_specialist`/catalog entries, and updated stale chrono-vault KG wording to canonical private-memory record/recall.
- Updated `shared/tool-catalog.md`, the 28-column runtime map, and 61 live specialist briefs under `departments/*/specialists` and `shared/specialists`.

Historical inbox/archive/outbox packets were intentionally left unchanged: they are audit records, not live callers.

### No-orphans gate

Added executable `scripts/audit-orphans.sh`. It audits live specialist contracts, tool catalog, runtime map, and `mcp_server.py` for retired names and implementations, including:

- `kg_query`, `list_skills`, `read_specialist`, `write_specialist`, `obsidian_search`, and `chrono-catalog` variants;
- split-SQL helpers and `list_attempts`;
- `SELECT ... LIKE` recall remnants;
- eager top-level `httpx` imports;
- stale chrono-vault KG/knowledge-graph descriptions.

`ORPHAN_AUDIT_ROOT` permits isolated fixture testing. A clean fixture passes and each injected retired tool reference fails non-zero.

## TDD and grep evidence

RED:

1. Initial decommission tests failed because blocking `httpx` prevented core import, split-SQL/catalog symbols remained, and the audit script did not exist.
2. After core/script implementation, the fixture negative control passed while the real-repository audit failed on live `kg_query` and catalog references.
3. A targeted absence assertion failed on the remaining `_vault_root` wrapper; it was then removed.
4. Parent review added a negative control for the removed `read_specialist` catalog entry. It failed because the audit missed the name and `voice-agent-builder` still referenced it; both were reconciled.

GREEN:

```text
PYTHONWARNINGS=error python3 -m unittest discover -s plugins/chrono-vault/tests -p 'test_*.py'
Ran 82 tests — OK
recall@5=1.000, MRR=1.000

bash scripts/audit-orphans.sh
No-orphans audit passed.

bash -n scripts/audit-orphans.sh
shellcheck scripts/audit-orphans.sh
python3 -m py_compile plugins/chrono-vault/mcp_server.py \
  plugins/chrono-vault/tests/test_decommission.py \
  plugins/chrono-vault/tests/test_audit_orphans.py
runtime-map 28-column awk check
git diff --check
All passed.
```

The subprocess test actively blocks `httpx` resolution, imports `mcp_server`, and verifies the human-only search returns a structured optional-dependency error.

## Scoped diff

Before this response artifact: 67 files changed, 365 insertions, 238 deletions.

- Core: `plugins/chrono-vault/mcp_server.py`
- Tests: `test_decommission.py`, `test_audit_orphans.py`
- Audit: `scripts/audit-orphans.sh`
- Contracts: `shared/tool-catalog.md`, `shared/specialist-runtime-map.tsv`, and 61 live specialist briefs

No files were deleted.

## Review and scope handoff

Status is `needs_review` because the packet requires Claude review and no in-lane Claude review adapter was available. No additional mailbox task was created.

Potential launcher/config follow-up: plugin manifests or host configuration outside this packet's authorized read/write paths may still invoke `--namespace catalog`. Those paths were not inspected. Because that retired namespace now exits non-zero, Claude/operator review should authorize a separate configuration audit if the catalog launcher may still be registered.
