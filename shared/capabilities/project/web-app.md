---
id: project/web-app
mode: project
title: Web application (browser UI / SaaS)
capability_state: live
state_reason: Live for the browser-testable build + acceptance surface — `chrome-devtools` and `playwright` are now probe-verified (`claude·yes·subscription`, TASK-0300) for navigate/inspect/interact/UI-QA on an app under test (fresh Chrome, no auth). Design via `figma` (`chrono·yes·subscription` — controller-session read-only; squad-lane access + design writes unverified) and deploy (Vercel `local·partial` / Firebase `claude·partial` connected-login-gated / Cloudflare edge / Codex Sites) remain squad-lane `needs_tool` profiles — explicit, not part of the live claim.
state_evidence: registry rows — chrome-devtools/playwright = `claude·yes·subscription` (probe TASK-2026-07-17-0300, reviewed at TASK-0320); context7 + plugin:github:github = `claude·lane-live`. figma = `chrono·yes·subscription` (OAuth connector smoke-confirmed read-only on the controller session; View seat authorizes no design writes; squad-lane access unverified → squad-lane `needs_tool` design profile); Vercel = `local·partial·subscription` (installed, unauthenticated); firebase = `claude·partial·subscription` (MCP connected, login/project-gated) → `needs_tool` deploy profiles (see Notes).
overlays: [review, accessibility, privacy, memory]
gates: [public_release, production_mutation, credential_change]
cost_note: subscription only — the browser MCPs (chrome-devtools/playwright) drive a locally-run fresh Chrome (no per-call billing); context7 / github plugin / chrono-vault are lane-native. No metered provider is on the path.
---

**When to use:** build, refactor, or ship a browser-facing application or SaaS UI. Native iOS/Android is a
`needs_specialist` profile (no native mobile role/toolchain exists) — responsive/PWA work stays here.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); capability_state precheck |
| **S1** Frame (requirements) | `product-manager`, `architect` | — | `brainstorming` (SKILL.md), `requirements-elicitation` (stub), `scope-decomposition` (stub) | — |
| **S2** Design | `architect`, `ui-engineer`, +`threat-modeler` if auth/PII | `context7` (claude · lane-live · subscription) | `dependency-cycle-audit` (stub) | design integration via `figma` = squad-lane `needs_tool` profile (registry `chrono·yes·subscription` — controller-read-only; squad-lane design writes unverified); privacy overlay if PII |
| **S3** Produce (build) | `ui-engineer`, `frontend-engineer`, `web-builder`, `backend-engineer`, `database-engineer` | `context7` (claude · lane-live · subscription), `chrome-devtools` (claude · yes · subscription), `playwright` (claude · yes · subscription) | `structured-data-authoring` (authored) | — |
| **S4** Verify (required visual-verify + e2e acceptance gate) | `test-engineer`, `accessibility-engineer` | `playwright` (claude · yes · subscription), `chrome-devtools` (claude · yes · subscription), `view_image` (codex · yes · subscription) | `wcag-conformance-audit` (authored), `visual-regression-baseline` (authored), `behavior-preservation-test` (stub) | **required acceptance gate — built UI is not accepted until seen + driven** (a FAIL blocks S6 ship): (a) e2e key user journeys pass (playwright / chrome-devtools drive the app); (b) visual verification — capture screenshots (take_screenshot / browser_take_screenshot), review them (view_image / lane image-read), run visual-regression-baseline vs the baseline; (c) lighthouse_audit thresholds (perf / a11y / best-practices); (d) wcag-conformance-audit. + accessibility overlay |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (mandatory cross-family when security-touching) — review tools are MECHANICS ONLY, never replacing the independent cross-family reviewer; `public_release`; +privacy/security if auth/PII |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | — | deploy = `needs_tool:auth` profile — target selector: Vercel primary (`local·partial·subscription`) / Firebase fallback (`claude·partial·subscription`, connected/login-gated) / Cloudflare edge / Codex Sites (deferred); `credential_change` for login; `public_release` + `production_mutation` per deploy; domain/DNS separately approved; stays `needs_tool` until an authenticated smoke + preview→rollback rehearsal produce evidence |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Live scope = the browser-testable build + acceptance surface: `chrome-devtools` + `playwright`
(probe-verified `claude·yes·subscription`) drive navigate/inspect/interact/UI-QA on an app under test. They
**spawn a fresh Chrome** — NOT the authenticated raw-CDP `:9222` session — which is exactly right for
acceptance testing / no-auth web work. **S4 is a required acceptance gate, not optional tooling** — the built
UI is not accepted until it is captured/seen (screenshots reviewed via `view_image` / lane image-read +
`visual-regression-baseline` vs baseline), driven (e2e key journeys via `playwright`/`chrome-devtools`),
audited (`lighthouse_audit` perf/a11y/best-practices), and WCAG-checked; a FAIL blocks the S6 ship.

**Needs-tool profiles (NOT part of the live claim):**
- **Design integration via `figma` → squad-lane `needs_tool`** (registry `chrono·yes·subscription` — OAuth connector smoke-confirmed read-only on the controller session, View seat authorizes no design writes, squad-lane access unverified; pair with Stitch for generated design work).
- **Deploy → `needs_tool:auth` profile.** Target selector, explicit operator choice per release (NOT auto-failover between providers): **Vercel** primary (`local·partial·subscription`, installed/unauthenticated — the operator's Next.js/Turbo tool), **Firebase** fallback (`claude·partial·subscription`, MCP connected/login-gated), **Cloudflare** Workers/Pages (edge/specialized, OAuth-available), **Codex Sites** deferred (session-live, every deployment URL is production). `credential_change` for login; every deploy is `public_release` + `production_mutation`; domain/DNS separately gated. Stays `needs_tool` until an authenticated smoke + a preview→rollback rehearsal produce evidence — never flipped live on faith. (See `_state/audit-2026-07-17/deploy-rec/`.)

Native iOS/Android stays `needs_specialist` (no native mobile role/toolchain). The `(stub)` skills are
read-on-start drafts, not invokable dependencies until authored. S5 review tools are mechanics only — the
mandatory independent cross-family reviewer is never replaced.
