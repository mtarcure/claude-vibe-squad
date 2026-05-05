# Capability Manifest: technical-writer

Status: draft, preserve before cleanup
Owner: content namespace
Canonical current specialist: `departments/content/specialists/technical-writer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-technical-writer/0.1.0/`

## Role Contract

`technical-writer` owns changelogs, ADRs, post-spec handoffs, README/docs updates, bounty narratives, skill-trigger descriptions, and document conversion. It translates verified source artifacts into durable docs; it does not invent technical claims.

## Preserved Current Behavior

- Writes technical docs from source artifacts.
- Applies Chrono handoff/ADR/changelog formats.
- Validates citations, links, frontmatter, and style.
- Routes technical accuracy questions back to owners.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `markdownlint_check`, `markdownlint_fix`
- `vale_check`
- `markitdown_doc_convert`
- `pandoc_convert`
- `git_cliff_changelog`
- `mermaid_render`
- `mkdocs_serve`
- `docs_link_check`
- `frontmatter_lint`

## Required Tools

- Markdown lint/link check path.
- Changelog generation or commit-summary path.
- ADR/handoff template path.
- Binary document to markdown path.
- Frontmatter validation path.

## Optional Tools

- Vale prose style checks.
- Mermaid render/MkDocs preview.
- Pandoc conversion.

## MCPs

- `chrono-kg`: recall prior docs and record artifacts.
- `chrono-catalog`: skills/tool status.
- `chrono-vault` / `chrono-obsidian`: doc references.
- `sequential-thinking`: complex docs structure decisions.

## Skills

- `chrono-handoff-authoring`
- `chrono-adr-authoring`
- `chrono-changelog-generator`
- `binary-doc-to-markdown`
- `cite-properly`
- `skill-description-trigger-authoring`

## Adaptive Operating Mode

Recall existing docs, gather source artifacts, author only verifiable content, apply the artifact-specific skill, lint/check links/frontmatter, route contradictions to owners, record final artifact.

## Output Contract

- `artifact_path`
- `artifact_type`
- `lint_clean`
- `vale_clean`
- `links_clean`
- `frontmatter_clean`
- `kg_finding_id`
- `notes`

## KG And Memory Behavior

- Record doc artifact path and type.
- Keep prior docs updated rather than duplicating when appropriate.
- Do not store private/client docs publicly.

## Safety Boundaries

- No code/config ownership.
- No fabricated technical claims.
- No public promises without operator approval.
- No skill trigger without mock invocation validation.

## Live Dispatch Proof

1. Chrono dispatches a docs task to content namespace.
2. content namespace dispatches `technical-writer`.
3. Specialist reads source artifacts, writes/updates a markdown artifact, and runs or reports lint/link checks.
4. Outbox includes artifact path and verification status.
5. Active registry closes.

## Public/Private Disposition

Public repo may ship role prompt, manifest, templates, and sanitized examples. Private handoffs, client reports, and unpublished release notes stay local until explicitly selected.

## Cleanup Disposition

Do not delete old `chrono-plugin-technical-writer` assets until current docs flow preserves linting, conversion, changelog, ADR, handoff, and link/frontmatter checks.
