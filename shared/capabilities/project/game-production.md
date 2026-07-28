---
id: project/game-production
mode: project
title: Game production (browser game — design · build · playtest)
capability_state: live
state_reason: Live for the browser-game surface — mechanics/experience/economy + level/quest/narrative authoring (judgment) and browser-game build, verified at S4 by the SAME required visual-verify + e2e gate as web-app (`chrome-devtools`/`playwright` `claude·yes·subscription` drive the running browser game, capture frames, run `visual-regression-baseline`). The **Godot** native-engine path is now tool-available: `godot` is registry-verified (`claude·yes·—`, headless CLI) and projected onto `game-engineer`, so engine build/export is a cited route rather than a `needs_tool` profile. **Unity/console runtimes remain `needs_tool`** (no verified toolchain) and **game deploy/publish remains `needs_tool`** (no verified connector). Automated e2e + visual verification does NOT replace human playtesting; a human playtest sign-off is a required S5 gate.
state_evidence: registry rows — chrome-devtools/playwright = `claude·yes·subscription`, view_image = `codex·yes·subscription`, generate_image/generate_video = `all·lane-live·metered` (chrono-media-studio wrapper; raw higgsfield = `verified:no`, prohibited), context7 = `claude·lane-live`, sequential-thinking/chrono-vault = `all·yes·subscription`, plugin:github:github = `claude·lane-live`, godot = `claude·yes·—` (local-cli, `chrono-canary:2026-07-26` godot-4.7.1 at `/opt/homebrew/bin/godot`, projected onto `game-engineer` as `preferred`/`host-PATH`); visual-regression-baseline/wcag-conformance-audit = `authored`. No Unity/console/game-deploy/`deploy_game`/`publish_game` tool is registry-verified → those profiles stay `needs_tool`. Roster IDs game-designer/level-narrative-designer/game-engineer/technical-artist are canonical.
overlays: [review, truth-rights, accessibility, privacy, memory]
gates: [public_release, paid_media, production_mutation]
cost_note: subscription lane-native for the core loop — the browser MCPs (`chrome-devtools`/`playwright`) drive a locally-run fresh Chrome (no per-call billing), and `context7`/`sequential-thinking`/`chrono-vault`/github plugin are lane-native. Generated art/audio assets via the `generate_image`/`generate_video` wrappers are `metered` (paid-media, provider-billed) and used ONLY when the game ships generated assets — each needs a budget/rate-limit guard (a hit limit is a typed `needs_tool`/degraded result) plus the `paid_media` gate + rights overlay. The Godot engine CLI is a free local binary (cost `—`, no provider billing). The remaining native/deploy toolchains (Unity, console SDKs, store publishing) are catalog-absent (`unknown` cost) → `needs_tool`.
---

**When to use:** design and ship a **browser game** — mechanics/experience/economy, levels/quests/narrative, and
a browser-runtime build, verified by the required visual-verify + e2e gate and a human playtest sign-off. A
**Godot** native/engine build is also in scope (`game-engineer` + the verified headless `godot` CLI). Unity and
console runtimes, and game store/console publishing, remain `needs_tool` profiles (no verified toolchain /
connector — see Notes). Distinct from `content/*` asset generation: this builds a playable game.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); capability_state + target-runtime precheck |
| **S1** Frame (game concept + scope) | `product-manager`, `game-designer`, `architect` | `context7` (claude · lane-live · subscription) | `brainstorming` (SKILL.md), `requirements-elicitation` (authored), `scope-decomposition` (authored) | runtime-target gate — browser and Godot-native are `live`; Unity/console remain a `needs_tool` profile |
| **S2** Design (mechanics · experience · economy + levels/narrative) | `game-designer`, `level-narrative-designer`, `architect` | `context7` (claude · lane-live · subscription), `sequential-thinking` (all · yes · subscription) | `dependency-cycle-audit` (authored) | `level-narrative-designer` consumes the `game-designer` mechanics/economy contract (proposes economy changes, does not own them) |
| **S3** Produce (build browser game + art pipeline) | `game-engineer`, `technical-artist`, `frontend-engineer` | `context7` (claude · lane-live · subscription), `chrome-devtools` (claude · yes · subscription), `playwright` (claude · yes · subscription), `generate_image` (all · lane-live · metered), `generate_video` (all · lane-live · metered), `godot` (claude · yes · —) | `structured-data-authoring` (authored) | generated art/video assets → `paid_media` gate + truth-rights (rights) overlay; the Godot native path builds/runs headlessly (`godot --headless`) via `game-engineer` — the GUI editor is operator-attended and NOT a lane route; Unity/console runtimes stay a `needs_tool` profile (see Notes) |
| **S4** Verify (required visual-verify + e2e gate) | `test-engineer`, `game-designer` | `playwright` (claude · yes · subscription), `chrome-devtools` (claude · yes · subscription), `view_image` (codex · yes · subscription) | `visual-regression-baseline` (authored), `wcag-conformance-audit` (authored) | **required acceptance gate — the game is not accepted until seen + driven** (a FAIL blocks S6 ship): (a) e2e — drive the running browser game's key loops (playwright / chrome-devtools); (b) visual verification — capture frames (take_screenshot / browser_take_screenshot), review them (view_image / lane image-read), run visual-regression-baseline vs the baseline; (c) lighthouse_audit thresholds (perf / a11y / best-practices). truth-rights overlay for generated assets; accessibility overlay |
| **S5** Review/Gate (review + playtest sign-off) | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); **human playtest sign-off (`operator`) REQUIRED — automated e2e + visual verification does NOT replace human playtesting; both are required to ship**; `public_release`; `paid_media` (generated assets) |
| **S6** Ship/Deliver (release / deploy) | `game-engineer`, `devops-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription), `godot` (claude · yes · —) | — | native artifact build is live on the Godot path (`godot --headless --export-release <preset> <out>`, `game-engineer`); **delivery of that artifact is NOT** — game store/console publishing stays a `needs_tool` profile (no verified connector; higgsfield `deploy_game`/`publish_game` are raw-higgsfield `verified:no`); `production_mutation` (deploy); `public_release` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Live scope = the **browser-game** surface plus the **Godot native/engine build path** (bounded — see
the Godot note below): design (mechanics/experience/economy) + level/quest/narrative authoring are judgment
work, and the browser build is verified at S4 by the same required
visual-verify + e2e gate as `project/web-app` (`chrome-devtools`/`playwright` drive the running game in a fresh
Chrome, capture frames, and run `visual-regression-baseline`). `game-designer` owns the mechanics/experience/
economy contract; `level-narrative-designer` consumes it (owns level pacing/quest/reward placement, proposes —
does not own — global economy); `game-engineer` implements the runtime; `technical-artist` owns the art pipeline.

**Human playtesting is a required gate (S5), not a tool.** Automated e2e + visual regression prove the game
*runs and looks right*; they do NOT prove it *plays well*. A human playtest sign-off (`operator`) is mandatory
before ship — both the automated S4 gate and the human playtest must pass.

**Godot native/engine path (live, bounded).** `godot` (`claude · yes · —`, Godot 4.7.1 at
`/opt/homebrew/bin/godot`, `chrono-canary:2026-07-26`) is projected onto `game-engineer`, so a Godot project can
be built, run, and exported from a lane. Bounds: **headless only** (`godot --headless`) — the GUI editor is
operator-attended and is not a lane route; the S4 visual-verify + e2e gate is written against the *browser*
runtime, so a native build's verification is a per-task design (`chrome-devtools`/`playwright` do not drive a
native window), and the S5 human playtest sign-off is required exactly as for the browser path. Producing an
export artifact is live; **delivering** it to a store/console is not (see below).

**Needs-tool / needs-specialist profiles (NOT part of the live claim):**
- **Unity / console runtimes → `needs_tool`/`needs_specialist`.** No Unity toolchain and no console SDK are
  cataloged; neither the browser-runtime claim nor the Godot claim extends to Unity or console targets until a
  real toolchain is registry-verified. (Godot is no longer in this profile — see the Godot note above.)
- **Game deploy / publish → `needs_tool`.** No verified game-publishing connector exists; the higgsfield
  `deploy_game`/`publish_game` tools are raw-higgsfield (`verified:no`, wrapper-only rule) and are NOT a live
  route. GitHub-hosted static delivery of a browser build uses the verified github plugin, but store/console
  publishing is `needs_tool`.
- **Generated game creation via raw higgsfield game tools → prohibited.** Raw `higgsfield__*` game-creation
  tools are never live (`verified:no`); the honest generated-asset route is the `generate_image`/`generate_video`
  wrappers (`all·lane-live·metered`), which are `paid_media`-gated and rights-reviewed (truth-rights overlay).
- **3D asset pipeline → `needs_tool` profile.** `higgsfield__generate_3d` (`claude·partial·metered`,
  schema-observed / execution-unverified) produces image→3D-GLB assets + rigging; animation-clip lookup is a
  non-tool lookup step (no cataloged tool for it), not a cited child. Because `generate_3d` is `partial` (would
  fail closed) and 3D has NO governed wrapper, it is a `needs_tool` profile, NOT a live S3 tuple — and every 3D
  generation is `paid_media`-gated with a `get_cost:true` preflight. (`partial` state ratified per the
  foundation-review note-2; promote to a live tuple only after a squad-lane smoke.)

Generated art/audio assets fire the `paid_media` gate and the truth-rights (rights/provenance) overlay — an
asset carrying a real person's likeness also fires the privacy overlay. The `(stub)` skills are read-on-start
drafts, not invokable dependencies until authored.
