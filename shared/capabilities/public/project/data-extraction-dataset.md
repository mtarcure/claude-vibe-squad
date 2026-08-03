---
id: project/data-extraction-dataset
mode: project
title: Data extraction + dataset wrangling (machine-readable formats)
overlays: [review, privacy, memory]
gates: []
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** extract and wrangle structured data from machine-readable sources — CSV/JSON/HTML/tabular/
plain-text data — into a clean, schema-shaped output. Web-sourced extraction uses `firecrawl`
(Claude-lane); local files are parsed via the lane shell. ALL PDF inputs (text-layer + scanned/image) +
format-specific docs are `needs_tool` (no PDF parser/OCR cataloged — see Profiles). PII fires the privacy
overlay **and** the sensitive-topic durable-note operator approval.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (data contract + schema) | `product-manager`, `data-extraction-engineer` | — | `schema-inference`, `scope-decomposition` | privacy overlay if PII |
| **S2** Design (extraction plan) | `data-extraction-engineer` | — | `schema-inference` | — |
| **S3** Produce (parse machine-readable + clean + shape) | `data-extraction-engineer` | `firecrawl`, `Apify`, `Brave Search`, `Serper` | `data-cleaning-pipeline`, `structured-data-authoring` | local-code branch (shell/script) for CSV/JSON/HTML/tabular/plain-text; ALL PDF + OCR = `needs_tool`; `Apify` scraping requires a target-authorization + spend gate |
| **S4** Verify (schema + integrity check) | `data-extraction-engineer`, `skeptic` | — | `structured-data-authoring` | privacy overlay if PII |
| **S5** Review/Gate | `code-reviewer`, `cross-family-reviewer` | — | — | review overlay (if the dataset feeds a downstream decision) |
| **S6** Ship/Deliver (dataset) | `data-extraction-engineer` | `chrono-obsidian` | `structured-data-authoring` | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record); sensitive-topic durable-note operator approval if PII-bearing |

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
