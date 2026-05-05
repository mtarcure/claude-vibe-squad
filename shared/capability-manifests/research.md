# Capability Manifest: research

Status: draft, preserve before cleanup
Owner: research namespace
Canonical current specialist: `departments/research/specialists/research.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-research/0.1.0/`

## Role Contract

`research` owns source discovery, multi-source synthesis, claim validation, citation quality, and evidence-level reporting. It finds and grounds information; it does not implement, scan live targets, submit reports, or spend paid API credits without approval.

## Preserved Current Behavior

- Requires multi-model research by default across Kimi, Claude, and Gemini.
- Uses named research MCPs before generic WebFetch fallback.
- Applies three-source/source-triangulation discipline.
- Produces annotated sources, synthesis, and evidence levels.
- Surfaces contradictions and unsourced claims instead of fabricating.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `smart_research`
- `get_playbook`
- `run_granular_tool`
- `consult_peer`
- `update_dossier`

Underlying old granular tools:

- `web_fetch`
- `web_search`
- `grep_sources`
- `kg_recall`

Old playbooks:

- `comparative-analysis`
- `source-investigation`
- `technical-deep-dive`

## Required Tools

- Multi-engine web/source search.
- Specific page/PDF fetch.
- Local corpus/source grep.
- KG/dossier recall and update path.
- Peer consult or multi-model verification path.

## Optional Tools

- Firecrawl/deep crawl, operator-approved when cost-bearing.
- ArXiv/GitHub/Reddit/HN specialized search.
- Context7/library-doc lookup.

## MCPs

- `chrono-research-arsenal`: primary source search and research tools.
- `chrono-kg`: dossier recall and finding records.
- `chrono-catalog`: skill/tool discovery.
- `chrono-vault` / `chrono-obsidian`: research artifact references.
- `sequential-thinking`: complex investigation planning.

## Skills

- `find-sources`
- `research-integrity-gate`
- `cite-properly`
- `evidence-level`
- `source-triangulation`
- `summarize-findings`
- `dual-level-retrieval`

## Adaptive Operating Mode

Recall prior dossier, decide standard/advisory/granular path, search broadly, pivot when results are weak, deepen primary sources, consult peers for novel angles, verify peer claims independently, record attempts and findings, then hand off to synthesizer or skeptic when needed.

## Output Contract

Expected return shape:

- `sources_path`
- `synthesis_path`
- `evidence_levels_path`
- `findings`
- `angles_tried`
- `angles_ruled_out`
- `peer_consults`
- `open_questions`
- `dossier_updated`
- `suggested_next_role`

## KG And Memory Behavior

- Recall before investigation.
- Record attempts and ruled-out angles.
- Record stable findings with source URLs/paths.
- Never store private source material in public/product paths.

## Safety Boundaries

- No fabricated citations.
- No live security scanning.
- No implementation or config writes.
- No paid API/crawl escalation without approval.
- No peer output promoted as evidence without source verification.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a research task to research namespace.
2. research namespace dispatches `research`.
3. Specialist uses research MCP/catalog/KG or records missing-tool disposition.
4. Specialist produces cited sources and evidence levels from a harmless topic.
5. Outbox includes citations, confidence, contradictions/open questions.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompt, manifest, skills, and sanitized sample reports. Private research corpora, customer source packs, and paid API keys stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-research` assets until current research role, catalog, and live proof preserve source discovery, dossier recall, peer consult, and citation discipline.
