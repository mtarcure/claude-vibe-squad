---
id: content/image
mode: content
title: Image asset generation
capability_state: degraded-blueprint
state_reason: The generation core is served by the `generate_image` wrapper (`lane-live`), but the raw `higgsfield__*` route is `verified: no` (auth-pending) and the FINAL-PLAN's "Higgsfield working today" claim is unreconciled with the catalog. Conservative default until the Phase-0 §4 wrapper-vs-raw reconciliation confirms end-to-end — then it upgrades to `lane-gated`/`live`.
state_evidence: registry rows — generate_image = `all·lane-live·metered` (api-catalog §9 chrono-media-studio wrapper `verified: yes`); Higgsfield API = `no` ("authentication incomplete; raw tools prohibited; wrapper only", §8). FINAL-PLAN §5 Phase-0.3 lists the Higgsfield reconciliation as an open honesty task.
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release]
cost_note: S3 generation uses the `metered` `generate_image` wrapper (provider-billed) and needs a budget/rate-limit guard; `chrono-vault` is subscription lane-native. Raw `higgsfield__*` is `verified: no` and is not used.
---

**When to use:** produce still images / graphics as a content deliverable. Media specialists are
`tool_gated` to the lane hosting the content-engineer plugin. Steps S1–S2 collapse (short capability).

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); brief |
| **S1** Frame (concept) | `image-designer`, `brand-voice` | — | `terminology-memory` (authored) | — |
| **S3** Produce (generate) | `image-designer` | `generate_image` (all · lane-live · metered) | — | — |
| **S4** Verify (+ rights) | `skeptic`, `brand-voice`, `asset-provenance-and-rights-auditor` | `view_image` (codex · yes · subscription) | `rights-and-provenance-gate` (authored), `consent-and-likeness-check` (authored) | truth-rights overlay — Rule-6 rights gate (machine record; non-PASS/stale subject-hash blocks); privacy overlay if a real person's likeness |
| **S5** Review/Gate | `skeptic`, `operator` | — | — | review overlay; `paid_media`, `public_release` |
| **S6** Ship/Deliver (package) | `image-designer` | — | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** `generate_image` is the honest live route; the raw `higgsfield__*` provider tools are
`verified: no` (auth incomplete) and must never be cited as live — the wrapper is why this capability can
generate at all. A backup lane without the wrapper produces a TBASF blueprint and terminates
`capability_gap` — never a false success. Voice-likeness / real-person resemblance routes to
`asset-provenance-and-rights-auditor` (never self-cleared).
