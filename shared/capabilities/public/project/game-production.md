---
id: project/game-production
mode: project
title: Game production (browser game — design · build · playtest)
overlays: [review, truth-rights, accessibility, privacy, memory]
gates: [public_release, paid_media, production_mutation]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

## Availability in a fresh clone

A zero-key checkout gets this protocol and its validation metadata as documentation; automated dispatch is `needs_tool`. To make it runnable, install and authenticate the selected model CLI, configure every MCP declared by the dispatched specialists, bind the private vault (`CHRONO_VAULT_ROOT`; Kimi also requires its exact vault context), install any required host-local binaries, and provide approved credentials plus a bounded budget for any metered provider named below. After setup, re-run the production role planner and validators on that host; availability remains subject to the narrower gaps and operator gates documented in this card.

**When to use:** design and ship a **browser game** — mechanics/experience/economy, levels/quests/narrative, and
a browser-runtime build, verified by the required visual-verify + e2e gate and a human playtest sign-off. A
**Godot** native/engine build is also in scope (`game-engineer` + the verified headless `godot` CLI). Unity and
console runtimes, and game store/console publishing, remain `needs_tool` profiles (no verified toolchain /
connector — see Notes). Distinct from `content/*` asset generation: this builds a playable game.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall); capability_state + target-runtime precheck |
| **S1** Frame (game concept + scope) | `product-manager`, `game-designer`, `architect` | `context7` | `brainstorming`, `requirements-elicitation`, `scope-decomposition` | runtime-target gate — browser and Godot-native are `live`; Unity/console remain a `needs_tool` profile |
| **S2** Design | `game-designer`, `level-narrative-designer`, `architect` | `context7`, `sequential-thinking` | `dependency-cycle-audit` | `level-narrative-designer` consumes the `game-designer` mechanics/economy contract (proposes economy changes, does not own them) |
| **S3** Produce (build browser game + art pipeline) | `game-engineer`, `technical-artist`, `frontend-engineer` | `context7`, `chrome-devtools`, `playwright`, `generate_image`, `generate_video`, `godot` | `structured-data-authoring` | generated art/video assets → `paid_media` gate + truth-rights (rights) overlay; the Godot native path builds/runs headlessly (`godot --headless`) via `game-engineer` — the GUI editor is operator-attended and NOT a lane route; Unity/console runtimes stay a `needs_tool` profile (see Notes) |
| **S4** Verify (required visual-verify + e2e gate) | `test-engineer`, `game-designer` | `playwright`, `chrome-devtools`, `view_image` | `visual-regression-baseline`, `wcag-conformance-audit` | **required acceptance gate — the game is not accepted until seen + driven** (a FAIL blocks S6 ship): (a) e2e — drive the running browser game's key loops (playwright / chrome-devtools); (b) visual verification — capture frames (take_screenshot / browser_take_screenshot), review them (view_image / lane image-read), run visual-regression-baseline vs the baseline; (c) lighthouse_audit thresholds (perf / a11y / best-practices). truth-rights overlay for generated assets; accessibility overlay |
| **S5** Review/Gate (review + playtest sign-off) | `code-reviewer`, `skeptic`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); **human playtest sign-off (`operator`) REQUIRED — automated e2e + visual verification does NOT replace human playtesting; both are required to ship**; `public_release`; `paid_media` (generated assets) |
| **S6** Ship/Deliver (release / deploy) | `game-engineer`, `devops-engineer`, `technical-writer` | `plugin:github:github`, `godot` | — | native artifact build is live on the Godot path (`godot --headless --export-release <preset> <out>`, `game-engineer`); **delivery of that artifact is NOT** — game store/console publishing stays a `needs_tool` profile (no verified connector; higgsfield `deploy_game`/`publish_game` are raw-higgsfield `verified:no`); `production_mutation` (deploy); `public_release` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

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

**Godot native/engine path (live, bounded).** `godot` (, Godot 4.7.1 at
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
  wrappers, which are `paid_media`-gated and rights-reviewed (truth-rights overlay).
- **3D asset pipeline → `needs_tool` profile.** `higgsfield__generate_3d` (,
  schema-observed / execution-unverified) produces image→3D-GLB assets + rigging; animation-clip lookup is a
  non-tool lookup step (no cataloged tool for it), not a cited child. Because `generate_3d` is `partial` (would
  fail closed) and 3D has NO governed wrapper, it is a `needs_tool` profile, NOT a live S3 tuple — and every 3D
  generation is `paid_media`-gated with a `get_cost:true` preflight. (`partial` state ratified per the
  foundation-review note-2; promote to a live tuple only after a squad-lane smoke.)

Generated art/audio assets fire the `paid_media` gate and the truth-rights (rights/provenance) overlay — an
asset carrying a real person's likeness also fires the privacy overlay. The `` skills are read-on-start
drafts, not invokable dependencies until authored.
