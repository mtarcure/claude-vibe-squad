---
id: project/image
mode: project
title: Image asset generation
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release]
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

**When to use:** produce still images / graphics as a content deliverable. Media specialists are
`tool_gated` to the lane hosting the chrono-media-studio plugin. Steps S1–S2 collapse (short capability).

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` | — | memory overlay (recall); brief |
| **S1** Frame (concept) | `image-designer`, `brand-voice` | — | `terminology-memory` | — |
| **S3** Produce (generate) | `image-designer` | `generate_image` | — | paid_media |
| **S4** Verify (+ rights) | `skeptic`, `brand-voice`, `asset-provenance-and-rights-auditor` | `view_image`, `claude native vision` | `rights-and-provenance-gate`, `consent-and-likeness-check` | truth-rights overlay — Rule-6 rights gate (machine record; non-PASS/stale subject-hash blocks); privacy overlay if a real person's likeness |
| **S5** Review/Gate | `skeptic`, `operator` | — | — | review overlay; `paid_media`, `public_release` |
| **S6** Ship/Deliver (package) | `image-designer` | — | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** `generate_image` is the governed, live route. Raw `higgsfield__generate_image` remains `verified: no` and must never be used; pure image generation is restricted to the wrapper. A backup lane without the wrapper produces a TBASF blueprint and terminates `capability_gap` — never a false success. Real-person resemblance routes to `asset-provenance-and-rights-auditor` (never self-cleared).

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Design Systems & Text-to-Design (Stitch):** If layout generation or visual system updates are required, the `Stitch` extension on the Gemini lane is available (`partial` state, subscription-tier, backend may meter). Since its design write capabilities remain un-smoked, any automated design writes route through the `needs_tool` pre-approval profile.
2. **Post-Production Image Manipulation (Higgsfield):** Non-generation utility actions are approved for exploratory discovery via `models_explore` (`partial`, free), and metered manipulation via `higgsfield__upscale_image`, `higgsfield__outpaint_image`, and `higgsfield__remove_background` (`partial`, metered). Executing any paid manipulation routes through a `needs_tool:paid_media` profile requiring the `paid_media` gate and `get_cost:true` preflight.
3. **Local vision alternative (nanobanana):** `nanobanana` is installed on the Gemini lane as a `partial`, metered image model. Because it overlaps the governed `generate_image` wrapper, its usage is restricted to opt-in exploration and does not replace the wrapper.
4. **Visual Evidence Verification:** S4 visual verification utilizes `claude native vision` (yes, subscription) on the Claude lane for high-fidelity inspect-element evidence review.
5. **Figma design retrieval:** Smoked read-only figma design connector is available on the Chrono lane for visual design context. Automated lane write access is pending.
