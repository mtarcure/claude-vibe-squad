---
id: research/data-extraction-dataset
mode: research
title: Data extraction + dataset wrangling (machine-readable formats)
capability_state: live
state_reason: The live scope is the machine-readable formats a standard stdlib runtime genuinely handles — CSV/JSON/HTML/tabular/plain-text data — parsed and shaped by local shell/script code (no catalog-absent tool), with `firecrawl` (claude·lane-live) for live web-source extraction and `chrono-vault` (all·yes). ALL PDF inputs (text-layer AND scanned/image) and format-specific documents are `needs_tool` — no PDF parser or OCR runtime is registry-verified (Bash+stdlib has none; see Profiles).
state_evidence: registry rows — firecrawl = `claude·lane-live·metered`, chrono-vault/chrono-obsidian = `all·yes·subscription`. Local parsing of machine-readable files (CSV/JSON/HTML/tabular/plain-text) runs via the lane shell (no catalog-absent tool). No PDF parser, OCR (e.g. tesseract), or document-parser runtime is cataloged (→ ALL PDF + format-specific docs are `needs_tool`).
overlays: [review, privacy, memory]
gates: []
cost_note: Local file parsing/wrangling is subscription lane-native (shell). `firecrawl` web extraction is `metered` (API-key billed) and needs a budget/rate-limit guard; chrono-* MCPs are subscription.
---

**When to use:** extract and wrangle structured data from machine-readable sources — CSV/JSON/HTML/tabular/
plain-text data — into a clean, schema-shaped output. Web-sourced extraction uses `firecrawl`
(Claude-lane); local files are parsed via the lane shell. ALL PDF inputs (text-layer + scanned/image) +
format-specific docs are `needs_tool` (no PDF parser/OCR cataloged — see Profiles). PII fires the privacy
overlay **and** the sensitive-topic durable-note operator approval.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (data contract + schema) | `product-manager`, `data-extraction-engineer` | — | `schema-inference` (stub), `scope-decomposition` (stub) | privacy overlay if PII |
| **S2** Design (extraction plan) | `data-extraction-engineer` | — | `schema-inference` (stub) | — |
| **S3** Produce (parse machine-readable + clean + shape) | `data-extraction-engineer` | `firecrawl` (claude · lane-live · metered) | `data-cleaning-pipeline` (stub), `structured-data-authoring` (authored) | local-code branch (shell/script) for CSV/JSON/HTML/tabular/plain-text; ALL PDF + OCR = `needs_tool` |
| **S4** Verify (schema + integrity check) | `data-extraction-engineer`, `skeptic` | — | `structured-data-authoring` (authored) | privacy overlay if PII |
| **S5** Review/Gate | `code-reviewer`, `cross-family-reviewer` | — | — | review overlay (if the dataset feeds a downstream decision) |
| **S6** Ship/Deliver (dataset) | `data-extraction-engineer` | `chrono-obsidian` (all · yes · subscription) | `structured-data-authoring` (authored) | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record); sensitive-topic durable-note operator approval if PII-bearing |

**Notes.** The live core is local parsing/cleaning/schema-shaping of machine-readable formats via the lane
shell (no catalog-absent tool) + `firecrawl` (Claude-lane, `metered`) for web sources; a hit rate/budget limit
is a typed `needs_tool`/degraded result.

**Needs-tool profile (NOT part of the live claim):** ALL PDF inputs (text-layer AND scanned/image) and
format-specific documents are `needs_tool` — PDF extraction is format-specific and needs a real parser/OCR
runtime, and none is registry-verified (Bash+stdlib includes no PDF parser). Do not name a specific PDF
parser or OCR tool until one is cataloged for the lane.

PII-bearing captures fire the privacy overlay (`privacy-steward`) **and** require the research sensitive-topic
durable-note operator approval before a durable dataset note is recorded (the privacy overlay alone does not
state that gate). This is extraction/wrangling, not a production ETL service (`project/data-pipeline`) and not
model training (no ML-training specialist exists).
