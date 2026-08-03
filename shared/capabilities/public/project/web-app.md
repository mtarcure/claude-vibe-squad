---
id: project/web-app
mode: project
title: Web application (browser UI / SaaS)
overlays: [review, accessibility, privacy, memory]
gates: [public_release, production_mutation, credential_change]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** build, refactor, or ship a browser-facing application or SaaS UI. Native iOS/Android is a
`needs_specialist` profile (no native mobile role/toolchain exists) — responsive/PWA work stays here.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall); capability_state precheck |
| **S1** Frame (requirements) | `product-manager`, `architect` | — | `brainstorming`, `requirements-elicitation`, `scope-decomposition` | — |
| **S2** Design | `architect`, `ui-engineer`, +`threat-modeler` if auth/PII | `context7` | `dependency-cycle-audit` | design integration via `figma` = squad-lane `needs_tool` profile; privacy overlay if PII |
| **S3** Produce (build) | `ui-engineer`, `frontend-engineer`, `web-builder`, `backend-engineer`, `database-engineer` | `context7`, `chrome-devtools`, `playwright` | `structured-data-authoring` | — |
| **S4** Verify (required visual-verify + e2e acceptance gate) | `test-engineer`, `accessibility-engineer` | `playwright`, `chrome-devtools`, `view_image` | `wcag-conformance-audit`, `visual-regression-baseline`, `behavior-preservation-test` | **required acceptance gate — built UI is not accepted until seen + driven** (a FAIL blocks S6 ship): (a) e2e key user journeys pass (playwright / chrome-devtools drive the app); (b) visual verification — capture screenshots (take_screenshot / browser_take_screenshot), review them (view_image / lane image-read), run visual-regression-baseline vs the baseline; (c) lighthouse_audit thresholds (perf / a11y / best-practices); (d) wcag-conformance-audit. + accessibility overlay |
| **S5** Review/Gate | `code-reviewer`, `skeptic`, `cross-family-reviewer` | `codex review`, `claude --from-pr` | — | review overlay (mandatory cross-family when security-touching) — review tools are MECHANICS ONLY, never replacing the independent cross-family reviewer; `public_release`; +privacy/security if auth/PII |
| **S6** Ship/Deliver | `devops-engineer`, `technical-writer` | `plugin:github:github` | — | deploy/release/credential steps are `devops-engineer`-owned (S3 builders incl. `web-builder` hand off the built site — authoring only, no deploy authority); deploy = `needs_tool:auth` profile — target selector: Vercel primary / Firebase fallback / Cloudflare edge / Codex Sites (deferred); `credential_change` for login; `public_release` + `production_mutation` per deploy; domain/DNS separately approved; stays `needs_tool` until an authenticated smoke + preview→rollback rehearsal produce evidence |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** Live scope = the browser-testable build + acceptance surface: `chrome-devtools` + `playwright`
 drive navigate/inspect/interact/UI-QA on an app under test. They
**spawn a fresh Chrome** — NOT the authenticated raw-CDP `:9222` session — which is exactly right for
acceptance testing / no-auth web work. **S4 is a required acceptance gate, not optional tooling** — the built
UI is not accepted until it is captured/seen (screenshots reviewed via `view_image` / lane image-read +
`visual-regression-baseline` vs baseline), driven (e2e key journeys via `playwright`/`chrome-devtools`),
audited (`lighthouse_audit` perf/a11y/best-practices), and WCAG-checked; a FAIL blocks the S6 ship.

**Needs-tool profiles (NOT part of the live claim):**
- **Design integration via `figma` → squad-lane `needs_tool`**.
- **Deploy → `needs_tool:auth` profile, owned by `devops-engineer`.** Operator-ratified boundary: `web-builder` (and the other S3 builders) author and build only — every deploy/DNS/hosting/secret/credential step routes to `devops-engineer`, which holds the production gates; the handoff artifact is the built site + deployment requirements. Target selector, explicit operator choice per release (NOT auto-failover between providers): **Vercel** primary, **Firebase** fallback, **Cloudflare** Workers/Pages (edge/specialized, OAuth-available), **Codex Sites** deferred (session-live, every deployment URL is production). `credential_change` for login; every deploy is `public_release` + `production_mutation`; domain/DNS separately gated. Stays `needs_tool` until an authenticated smoke + a preview→rollback rehearsal produce evidence — never flipped live on faith. (See `_state/audit-2026-07-17/deploy-rec/`.)

Native iOS/Android stays `needs_specialist` (no native mobile role/toolchain). The `` skills are
read-on-start drafts, not invokable dependencies until authored. S5 review tools are mechanics only — the
mandatory independent cross-family reviewer is never replaced.
