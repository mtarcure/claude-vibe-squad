# Capability Manifest: knowledge-librarian

Status: draft, current-system capability
Owner: sysmgmt namespace
Canonical current specialist: `departments/sysmgmt/specialists/knowledge-librarian.md`
Old plugin source: none direct in old `claude-chrono`; related surfaces are memory-curator, research, and shared Obsidian/KG plugins.

## Role Contract

`knowledge-librarian` owns the operator's personal knowledge workspace: reading queue, bookmarks, PDFs, source notes, topic maps, frontmatter, tags, links, and Obsidian hygiene. It is distinct from `memory-curator`, which manages assistant memory and KG hygiene.

## Preserved Current Behavior

- Curates operator knowledge, not assistant instincts.
- Imports and organizes sources with frontmatter and citations.
- Handles reading queues, topic maps, PDF/book/paper processing, broken links, orphan notes, and tag normalization.
- Escalates deep investigations to research namespace.
- Never deletes or restructures operator knowledge without approval.

## Old Plugin Capabilities To Preserve

No direct old plugin existed for this role. Preserve current-system capability and shared ancestry:

- Obsidian/KG navigation from memory-curator/shared plugins.
- Source synthesis handoff from old research/synthesizer roles.
- Binary document conversion from scraping/content tooling where appropriate.

## Required Tools

- Obsidian read/write path.
- Source/citation capture path.
- Markdown note creation path.
- PDF/binary document to markdown path.
- Link/tag/frontmatter audit path.

## Optional Tools

- Zotero integration.
- Reading-time estimator.
- OCR and document conversion helpers.
- Research MCP for source enrichment.

## MCPs

- `chrono-obsidian`: vault read/write for curated notes.
- `chrono-vault` / `chrono-kg`: durable references and topic relationships when appropriate.
- `chrono-catalog`: discover document-processing skills/tools.
- `chrono-research-arsenal`: source lookup when curation requires metadata or related sources.
- `sequential-thinking`: taxonomy or topic-map restructuring decisions.

## Skills

Current or required skills:

- `binary-doc-to-markdown`
- `kg-vault-health-check`
- `stale-knowledge-purge`
- `obsidian-kg-navigation`
- `source-quality-triage`
- `citation-preservation`

## Adaptive Operating Mode

Identify source type, capture metadata and citation, convert to markdown when needed, create or update vault note with frontmatter/tags/links, update reading queue or topic map, propose large restructures instead of applying them, and escalate research-heavy clusters to research namespace.

## Output Contract

Expected return shape:

- `notes_created`
- `notes_updated`
- `source_metadata`
- `reading_queue_updates`
- `topic_map_updates`
- `hygiene_findings`
- `operator_approval_required`
- `kg_finding_id`

## KG And Memory Behavior

- Keep operator knowledge and assistant memory separate.
- Record only sanitized references to KG when useful.
- Do not copy private reading content into public repo.
- Do not delete imported notes without operator approval.

## Safety Boundaries

- No deletion of operator notes without approval.
- No large taxonomy/folder rewrite without approval.
- No private source material committed publicly.
- No security-sensitive source reuse without security namespace review.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a vault/reading-queue task to sysmgmt namespace.
2. sysmgmt namespace dispatches `knowledge-librarian`.
3. Specialist uses Obsidian/KG/catalog or records missing-tool disposition.
4. Specialist creates/updates a sanitized sample note or proposes a change without destructive action.
5. Outbox includes evidence paths and approval gates.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompt, manifest, vault hygiene schema, and sanitized examples. Operator notes, PDFs, books, bookmarks, private topic maps, and vault contents stay local/private.

## Cleanup Disposition

Do not delete knowledge/vault-related scripts or docs until this role's boundaries, public/private paths, and live proof are in place.
