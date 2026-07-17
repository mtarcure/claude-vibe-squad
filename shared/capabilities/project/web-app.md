---
id: project/web-app
mode: project
title: Web application (browser UI / SaaS)
capability_state: live
state_reason: Live for the browser-testable build + acceptance surface — `chrome-devtools` and `playwright` are now probe-verified (`claude·yes·subscription`, TASK-0300) for navigate/inspect/interact/UI-QA on an app under test (fresh Chrome, no auth). Design via `figma` and deploy via `firebase` remain `needs_tool` (still catalog-absent) — explicit profiles, not part of the live claim.
state_evidence: registry rows — chrome-devtools/playwright = `claude·yes·subscription` (probe TASK-2026-07-17-0300, reviewed at TASK-0320); context7 + plugin:github:github = `claude·lane-live`. figma/firebase = `unknown·catalog-absent·unknown` → `needs_tool` profiles (see Notes).
overlays: [review, accessibility, privacy, memory]
gates: [public_release, production_mutation]
cost_note: subscription only — the browser MCPs (chrome-devtools/playwright) drive a locally-run fresh Chrome (no per-call billing); context7 / github plugin / chrono-vault are lane-native. No metered provider is on the path.
---

**When to use:** build, refactor, or ship a browser-facing application or SaaS UI. Native iOS/Android is a
`needs_specialist` profile (no native mobile role/toolchain exists) — responsive/PWA work stays here.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); capability_state precheck |
| **S1** Frame (requirements) | `product-manager`, `architect` | — | `requirements-elicitation` (stub), `scope-decomposition` (stub) | — |
| **S2** Design | `architect`, `ui-engineer`, +`threat-modeler` if auth/PII | `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub) | design integration via `figma` = `needs_tool` profile (`unknown·catalog-absent` — no verified connector); privacy overlay if PII |
| **S3** Produce (build) | `ui-engineer`, `frontend-engineer`, `web-builder`, `backend-engineer`, `database-engineer` | `context7` (claude · lane-live · subscription), `chrome-devtools` (claude · yes · subscription), `playwright` (claude · yes · subscription) | `structured-data-authoring` (authored) | — |
| **S4** Verify | `test-engineer`, `accessibility-engineer` | `playwright` (claude · yes · subscription), `chrome-devtools` (claude · yes · subscription) | `wcag-conformance-audit` (authored), `visual-regression-baseline` (stub), `behavior-preservation-test` (stub) | accessibility overlay |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (mandatory cross-family when security-touching) — review tools are MECHANICS ONLY, never replacing the independent cross-family reviewer; `public_release`; +privacy/security if auth/PII |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | — | deploy via `firebase` = `needs_tool` profile (`unknown·catalog-absent` — no verified connector); `production_mutation` (deploy) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Live scope = the browser-testable build + acceptance surface: `chrome-devtools` + `playwright`
(probe-verified `claude·yes·subscription`) drive navigate/inspect/interact/UI-QA on an app under test. They
**spawn a fresh Chrome** — NOT the authenticated raw-CDP `:9222` session — which is exactly right for
acceptance testing / no-auth web work.

**Needs-tool profiles (NOT part of the live claim):**
- **Design integration via `figma` → `needs_tool`** (`unknown·catalog-absent·unknown` — no verified connector).
- **Deploy via `firebase` → `needs_tool`** (`unknown·catalog-absent·unknown`); production deploy is also `production_mutation`-gated.

Native iOS/Android stays `needs_specialist` (no native mobile role/toolchain). The `(stub)` skills are
read-on-start drafts, not invokable dependencies until authored. S5 review tools are mechanics only — the
mandatory independent cross-family reviewer is never replaced.
