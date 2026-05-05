# Capability Manifest: data-extraction-engineer

Status: draft, current-system capability
Owner: research namespace
Canonical current specialist: `departments/research/specialists/data-extraction-engineer.md`
Old plugin source: none direct in old `claude-chrono`; related surfaces are scraping-engineer, research, and technical-writer document conversion.

## Role Contract

`data-extraction-engineer` owns document-focused extraction: PDFs, CSV/JSON/XML cleanup, tables, schema inference, document-to-markdown conversion, and provenance-preserving normalized datasets. It is distinct from web-focused `scraping-engineer`.

## Preserved Current Behavior

- Extracts from files/static corpora, not live dynamic websites.
- Preserves row/page/source provenance.
- Infers schemas and flags ambiguity.
- Applies redaction baseline for PII/sensitive data.
- Produces extraction logs and manual review queues.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve current capability through:

- document conversion from technical-writer/scraping capabilities
- research citation/provenance discipline
- schema/data normalization skills

## Required Tools

- PDF text/table extraction path.
- Pandoc/format conversion path.
- Dataframe normalization path.
- Schema inference and validation path.
- Provenance and extraction-log writing path.

## Optional Tools

- OCR for scanned PDFs.
- Parquet output.
- LLM-assisted table cleanup when allowed.

## MCPs

- `chrono-kg`: record extraction attempts/findings.
- `chrono-catalog`: discover extract/convert tools.
- `chrono-vault` / `chrono-obsidian`: artifact references.
- `chrono-research-arsenal`: source lookup when extraction is tied to research.
- `sequential-thinking`: schema ambiguity decisions.

## Skills

- `schema-inference`
- `data-cleaning-pipeline`
- `cite-properly`
- `evidence-level`
- `research-integrity-gate`
- `binary-doc-to-markdown`

## Adaptive Operating Mode

Identify source format and target schema, extract conservatively, normalize with reversible transforms, typecheck/dedupe, preserve provenance per row or chunk, document anomalies, surface schema instability, and hand to research/synthesizer when analysis is needed.

## Output Contract

Expected return shape:

- `extracted_data_path`
- `format`
- `schema_path`
- `extraction_log_path`
- `success_rate`
- `manual_review_queue`
- `provenance_summary`
- `kg_finding_id`

## KG And Memory Behavior

- Record extraction attempt and source provenance.
- Store only references to private/source documents when sensitive.
- Do not place raw private datasets in public repo paths.

## Safety Boundaries

- No ToS-restricted extraction without operator approval.
- No PII extraction without redaction baseline.
- No fresh browser sessions; hand browser needs to `scraping-engineer`/Security.
- No lossy schema coercion without reporting it.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a document extraction task to research namespace.
2. research namespace dispatches `data-extraction-engineer`.
3. Specialist extracts from sanitized sample data or reports missing-tool disposition.
4. Outbox includes schema, log, provenance, and quality notes.
5. Sensitive data boundary is stated.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompt, manifest, sample fixtures, and schemas. Private datasets, financial docs, customer docs, and source corpora stay local.

## Cleanup Disposition

Do not delete document extraction helpers or docs until this role's extraction/provenance boundary and live proof are covered.
