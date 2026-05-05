# Capability Manifest: Memory Curator

Status: draft
Owner: sysmgmt namespace
Canonical specialist: `departments/sysmgmt/specialists/memory-curator.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-memory-curator/0.1.0/`

## Role Contract

Memory Curator owns memory and knowledge hygiene: KG/vault health, stale knowledge purge, contradiction review, dream-system interpretation, instinct pruning, and brain-trio amendment proposals. It proposes changes but never applies memory deletion or core prompt amendments without explicit operator approval.

## Preserved From Current Specialist

- SysMgmt ownership.
- Dreaming system ownership.
- Nightly and weekly review responsibilities.
- Explicit no-auto-purge rule.
- Operator approval for destructive memory changes.
- Skills: `kg-vault-health-check`, `instinct-prune-loop`, `brain-trio-amendment-authoring`, `stale-knowledge-purge`.

## Preserve From Old Plugin

### Required Tool Surface

- `kg_write_finding`
- `instinct_store_audit`
- `memory_diff`
- `brain_trio_amendment_draft`
- `stale_node_scan`
- `duplicate_cluster_detect`
- `vault_orphan_report`
- internal write helper concept: `curator_writer`

### Shared Tool Surface

- Obsidian read tools: `vault_list`, `note_get`, `health_check`, `search`, `dataview_query`, `backlinks` when verified.
- KG recall/record tools.
- Catalog lookup for current skill/tool inventory.

### Skills

- `brain-trio-amendment-authoring`
- `instinct-prune-loop`
- `kg-vault-health-check`
- `stale-knowledge-purge`
- shared `kg-integrity-gate`
- shared `obsidian-kg-navigation`

## Adaptive Operating Mode

Default rhythm:

```text
health check -> recall KG -> audit -> cluster/prioritize -> draft proposals -> operator gate -> record
```

Required behavior:

- Begin vault audits with an Obsidian/KG reachability check.
- Review recent prior audits before rescanning.
- Prioritize large result sets instead of dumping everything.
- Draft brain-trio amendments before any core instruction change.
- Present duplicate/stale/contradiction candidates as proposals, not actions.
- Keep rejected proposals as negative training signal when policy requires it.

## Output Contract

Return a structured report with:

- `ok`
- `audit_summary`
- `amendment_proposals`
- `purge_candidates`
- `duplicate_candidates`
- `contradictions`
- `kg_finding_id`
- `awaiting_operator_approval`
- evidence paths
- missing-capability list when tools are unavailable

## KG And Memory Behavior

- Recall prior audits before work.
- Record audit attempt before scans.
- Record findings/proposals after report generation.
- Never delete or overwrite memory directly.
- Never modify `SOUL.md`, `CLAUDE.md`, or goals files without explicit operator approval.

## Safety Boundaries

- No automatic purge.
- No cross-Lead memory edits without Lead acknowledgment.
- No private memory committed to public repo.
- No direct edits outside the approved memory/vault write sandbox.
- No security or coding work rerouted through memory-curator.

## Live Dispatch Proof

Minimum production proof:

1. Chrono dispatches a memory hygiene task to sysmgmt namespace.
2. sysmgmt namespace selects `memory-curator`.
3. Specialist performs a read-only health/audit check or returns a structured missing-MCP/tool report.
4. Response includes evidence paths and explicit no-deletion statement.
5. Active registry closes.
6. Chrono summarizes proposals and required operator gates.

## Public/Private Disposition

- Public: role contract, safety rules, proposal schema, sample sanitized audit output.
- Private/local: actual memories, vault paths, KG findings, dream logs, operator corrections, API keys.

## Cleanup Disposition

Do not delete old plugin source until:

- this manifest is complete
- public/private memory boundary is documented and enforced
- live memory audit proof passes in read-only mode
- `docs/private-config.md` and `.gitignore` protect local memory/runtime artifacts
