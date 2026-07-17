---
id: project/web-app
mode: project
title: Web application (browser UI / SaaS)
capability_state: needs_tool
state_reason: The browser-driver + design/deploy tools that back real web-app build & acceptance (chrome-devtools, playwright, figma, firebase) are roster-cited but catalog-absent — no verified api-catalog entry on any lane.
state_evidence: registry rows chrome-devtools/playwright/figma/firebase = `catalog-absent` (shared/api-catalog.md no `###` entry, 2026-07-17); context7 + plugin:github:github are `lane-live` on claude only.
overlays: [review, accessibility, privacy, memory]
gates: [public_release, production_mutation]
cost_note: subscription for the lane-native coordination tools (context7, github plugin, chrono-vault). No metered provider is required; the blocking tools are catalog-absent, not paid.
---

**When to use:** build, refactor, or ship a browser-facing application or SaaS UI. Native iOS/Android is a
`needs_specialist` profile (no native mobile role/toolchain exists) — responsive/PWA work stays here.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); capability_state precheck |
| **S1** Frame (requirements) | `product-manager`, `architect` | — | `requirements-elicitation` (stub), `scope-decomposition` (stub) | — |
| **S2** Design | `architect`, `ui-engineer`, +`threat-modeler` if auth/PII | `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub) | privacy overlay if PII |
| **S3** Produce (build) | `ui-engineer`, `frontend-engineer`, `web-builder`, `backend-engineer`, `database-engineer` | `context7` (claude · lane-live · subscription), `chrome-devtools` (unknown · catalog-absent · unknown), `playwright` (unknown · catalog-absent · unknown), `figma` (unknown · catalog-absent · unknown), `firebase` (unknown · catalog-absent · unknown) | `structured-data-authoring` (authored) | — |
| **S4** Verify | `test-engineer`, `accessibility-engineer` | `playwright` (unknown · catalog-absent · unknown) | `wcag-conformance-audit` (authored), `visual-regression-baseline` (stub), `behavior-preservation-test` (stub) | accessibility overlay |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | — | — | review overlay (mandatory cross-family when security-touching); `public_release`; +privacy/security if auth/PII |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | — | `production_mutation` (deploy) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Until `chrome-devtools`/`playwright` (build+acceptance) and `figma`/`firebase` (design+deploy)
get verified api-catalog rows on an executing lane, this capability's S3/S4 steps degrade to blueprint on
those tools and the whole capability is honestly `needs_tool`. Reconciling those catalog rows (FINAL-PLAN
§3 Tier-2, P0) is what upgrades it toward `lane-gated`/`live`. The `(stub)` skills are read-on-start
drafts and cannot be treated as invokable dependencies until authored.
