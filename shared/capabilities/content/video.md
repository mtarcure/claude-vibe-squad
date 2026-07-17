---
id: content/video
mode: content
title: Video / motion asset generation
capability_state: degraded-blueprint
state_reason: The generation core is the `generate_video` wrapper (`all·lane-live·metered`), but — exactly as `content/image` — the raw `higgsfield__*` provider route is `verified: no` (auth-pending) and the "Higgsfield working today" claim is unreconciled with the catalog. Conservative default until the Phase-0 wrapper-vs-raw reconciliation confirms end-to-end, then it upgrades to `lane-gated`/`live`.
state_evidence: registry rows — generate_video = `all·lane-live·metered` (chrono-media-studio wrapper `verified: yes`); Higgsfield API = `none·no` ("authentication incomplete; raw tools prohibited; wrapper only"). Same honest hold as `content/image`.
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release]
cost_note: S3 generation uses the `metered` `generate_video` wrapper (provider-billed) and needs a budget/rate-limit guard — a hit limit is a typed `needs_tool`/degraded result. `chrono-vault` is subscription lane-native. Raw `higgsfield__*` is `verified: no` and is not used.
---

**When to use:** produce a video / motion asset as a content deliverable. Media specialists are `tool_gated`
to the lane hosting the content-engineer plugin. S1–S2 collapse (short capability).

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); brief |
| **S1** Frame (concept + storyboard) | `video-director`, `brand-voice` | — | `terminology-memory` (authored) | — |
| **S3** Produce (generate + edit) | `video-director`, `video-editor` | `generate_video` (all · lane-live · metered) | — | — |
| **S4** Verify (rights + conditional truth) | `skeptic`, `brand-voice`, `asset-provenance-and-rights-auditor`, `content-verifier` | `chrono-research-arsenal` (all · lane-live · subscription) | `rights-and-provenance-gate` (authored), `consent-and-likeness-check` (authored), `claim-verification` (authored) | truth-rights overlay — **Rule-6** rights/provenance gate (machine record; non-PASS/stale subject-hash blocks) AND independent likeness/consent check (both mandatory); **conditional Rule-8** truth gate — a video carrying factual/product/efficacy claims requires `content-verifier` grounding (unverifiable load-bearing claim ⇒ `needs_tool`/non-PASS before release); privacy overlay if a real person's likeness |
| **S5** Review/Gate | `skeptic`, `operator` | — | — | review overlay; `paid_media`, `public_release` |
| **S6** Ship/Deliver (package) | `video-editor` | — | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** `generate_video` is the honest live route; the raw `higgsfield__*` provider tools are `verified: no`
(auth incomplete) and must never be cited as live — the wrapper is why this capability can generate at all. A
backup lane without the wrapper produces a TBASF blueprint and terminates `capability_gap`, never a false
success. Real-person likeness / recognizable voice or face routes to `asset-provenance-and-rights-auditor`
(never self-cleared). A video carrying factual / product / efficacy claims additionally fires the **conditional
Rule-8 truth gate** at S4 (`content-verifier` grounds the claims via `chrono-research-arsenal`; a load-bearing
unverifiable claim ⇒ `needs_tool`/non-PASS before `public_release`) — this is additive to, not a replacement
for, the independent Rule-6 rights + likeness gates; purely aesthetic / non-factual assets skip it. Same
degraded-blueprint hold as `content/image` until the Higgsfield reconciliation lands.
