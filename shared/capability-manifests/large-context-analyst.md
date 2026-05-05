# Capability Manifest: large-context-analyst

Status: draft, preserve before cleanup
Owner: research namespace
Canonical current specialist: `departments/research/specialists/large-context-analyst.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-large-context-analyst/0.1.0/`

## Role Contract

`large-context-analyst` owns full-codebase, multi-repo, long-document, and large-corpus analysis where cross-file or cross-document relationships matter. It analyzes and reports; it does not implement, decide architecture, or produce exploit chains.

## Preserved Current Behavior

- Uses Kimi/long-context capability for large corpora.
- Requires scope estimation before analysis.
- Preserves file/path evidence chains.
- Applies claim validation before reporting findings.
- Escalates when corpus exceeds safe context strategy.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `scope_card_generate`
- `layered_map_build`
- `cross_file_trace`
- `claim_validate_gate`
- `kg_crossref_read`

Old shared Obsidian tools:

- `vault_list`, `note_get`, `note_put`
- `search`, `dataview_query`, `backlinks`, `health_check`

## Required Tools

- Scope card/token estimate path.
- File map/import relationship path.
- Cross-file symbol/text trace path.
- Claim validation path.
- KG/corpus recall path.

## Optional Tools

- Obsidian export/navigation helpers.
- Graph visualization for cross-file edges.

## MCPs

- `chrono-kg`: recall prior corpus analysis and record findings.
- `chrono-catalog`: tool/skill discovery.
- `chrono-vault` / `chrono-obsidian`: corpus and artifact references.
- `sequential-thinking`: layered analysis planning.

## Skills

- `layered-analysis-loop`
- `dual-level-retrieval`
- `claim-validation-gate`
- `scope-estimation`
- `cross-file-relationship-synthesis`
- `evidence-chain-preservation`

## Adaptive Operating Mode

Generate scope card first, recall prior analysis, choose hold-all/chunked/delegate strategy, map corpus structure, trace relevant symbols/files, validate claims against source paths, preserve evidence chains, record findings, and suggest next role.

## Output Contract

Expected return shape:

- `scope_card`
- `strategy`
- `findings`
- `cross_repo_edges`
- `claim_validations`
- `kg_finding_id`
- `suggested_next_role`

## KG And Memory Behavior

- Record scope metadata with findings.
- Tag multi-repo findings with involved repos/corpora.
- Never silently repeat prior corpus analysis.

## Safety Boundaries

- No production code changes.
- No exploit chain/CVSS work.
- No architecture decisions.
- No silent truncation beyond context limits.
- No full-codebase review when dispatched for a narrow question.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a large-corpus task to research namespace.
2. research namespace dispatches `large-context-analyst`.
3. Specialist generates scope card and recalls KG.
4. Specialist traces/validates at least one harmless cross-file or cross-document claim.
5. Outbox includes evidence paths and scope strategy.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompt, manifest, skill docs, and small sample corpus tests. Private repos, client corpora, and full source packs stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-large-context-analyst` assets until current role preserves scope-card, layered mapping, trace, validation, and evidence-chain behavior.
