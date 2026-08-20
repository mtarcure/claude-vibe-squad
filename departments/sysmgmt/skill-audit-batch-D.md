---
id: TASK-2026-08-18-1710-14cfd64e-response
in_response_to: TASK-2026-08-18-1710-14cfd64e
from: claude
to: chrono
type: RESULT
status: complete
return_artifact: departments/content/outbox/TASK-2026-08-18-1710-14cfd64e-response.md
---

Batch D descriptive audit complete: all 14 content/media skills exist and were read in full, all nine fields assessed per skill. Headline pattern: the batch is a uniform 20–21-line template set (no `description:` frontmatter on any), registered as "read-on-start methodology reference; never invoke as a tool", with a declared consumer for every skill via gemini-lane adapter projections — but **no instruction path anywhere tells any specialist to actually read them**, claude-lane adapters for the same specialists project different or no skills, and one skill plus the live audio-assets capability card both cross-reference the retired `voice-consistency-audit`. The two game-audio skills (`interactive-audio-design`, `audio-event-map-authoring`) are the best-constructed; most of the rest is general craft competence whose verify steps assume human ears/calibrated monitors no lane has, with no measurable proxy (ffmpeg/ffprobe) ever named. `subagents: 0` — worked solo; parallel tool batching only.

# Batch D skill audit — content & media production (14 skills)

**Scope**: `accessible-media-authoring`, `audio-event-map-authoring`, `audio-layering-techniques`, `audio-production-basics`, `color-grading-basics`, `color-theory`, `composition-rules`, `music-production-basics`, `sonic-branding`, `sound-design-principles`, `video-post-production`, `video-production-principles`, `voice-performance-direction`, `interactive-audio-design`. **All 14 present** under `shared/skills/` — none absent.

Per packet firewall, `departments/sysmgmt/skill-library-audit.md` matched my reference grep but was deliberately **not read** (prior assessment).

## Facts common to all 14 (stated once, not repeated per row)

- **Form**: every file is 20–21 lines: frontmatter (`name:` + `status: authored` only — **no `description:` on any**, confirming the packet's fact for this whole batch), a one-line purpose, 5–6 Steps, 3 Acceptance bullets. Template-uniform to the point of reading as one authoring pass; git first-adds are two bulk commits, `806ef4e5` 2026-07-13 ("auto-snapshot: before TASK-2026-07-13-1427 dispatch") and `b808d1b7` 2026-07-25 ("A4 orphan triage + owner wiring").
- **Wiring**: none of the 14 appears in `.claude/skills/` or `.agents/skills/` (both hold only the offensive-security/audit set). None is in `_retired/`. So none is invocable as a Skill-tool skill in any live runtime — consistent with their registry classification.
- **Registry**: each has a row in `shared/registries/skill-tool-registry.tsv` typed `authored-pattern-doc`, scope `all`, usage "read-on-start methodology reference; never invoke as a tool", department `content`.
- **Declared consumers**: gemini-lane adapters project them via `capability_skills` frontmatter (`model-lanes/gemini/.gemini/agents/*.md`), sourced from `model-lanes/specialist-lane-capabilities.v1.json` (names verified present in that JSON). Full map: accessibility-engineer→accessible-media-authoring; interactive-audio-designer→audio-event-map-authoring+interactive-audio-design; sound-designer→audio-layering-techniques+audio-production-basics+sound-design-principles; music-composer→audio-production-basics+music-production-basics+sonic-branding; voice-narrator→audio-production-basics+voice-performance-direction; video-editor→color-grading-basics+video-post-production; video-director→video-production-principles; image-designer→color-theory+composition-rules.
- **Reachability gap (systemic)**: the projection block in the gemini adapters sits inside an **HTML comment**, the adapter body instructs reading only the canonical brief ("Read that file at task start") and never the skill files, and the canonical briefs do not name these skills (checked `sound-designer.md`: zero mentions of its three projected skills). The registry's declared "read-on-start" usage therefore has **no instruction that triggers the read**. A declared consumer exists for every skill; a *reaching* consumer likely does not.
- **Lane asymmetry**: claude-lane adapters exist for all 8 consumer specialists but do **not** project batch D — claude `sound-designer.md` has no skills declaration at all; claude `interactive-audio-designer.md` projects `skills: ["interface-ambiguity-check"]` instead of the two audio skills gemini projects. Batch D is effectively gemini-lane-declared only.
- **Systemic effectiveness ceiling**: nearly every skill's verification step assumes human perceptual verification ("multiple playback systems", "calibrated reference", "verify against the references") that no lane can perform, and none names a measurable proxy (ffmpeg `ebur128`/`loudnorm` for LUFS, ffprobe for export specs, ffmpeg `waveform`/`vectorscope` filters for scopes) even where one exists. As methodology prose that's survivable; as Acceptance gates it makes the PASS conditions unverifiable by the executing agent.

---

## 1. accessible-media-authoring

1. **WHAT** — Author alt-text, timed captions, and full transcripts for generated or third-party media; triggers when a media deliverable is about to ship without accessibility artifacts.
2. **CLARITY** — Executable as a checklist except its first step: "Perceive the asset (multimodal ingest); if it can't be perceived, request it or report `capability_gap`" — no tool or route for ingest is named, and no lane natively ingests audio.
3. **EFFECTIVENESS** — The Acceptance section does the real work as a review rubric: "Missing alt-text/captions/transcript is a PASS-blocker, not a warning" is an enforceable house gate. Steps 2–4 restate standard a11y practice.
4. **SAFETY** — Nothing destructive or outward-facing. Safety-positive anti-fabrication rule: "never invent content" / "No transcript/alt content invented for media that could not be perceived."
5. **USEFULNESS** — accessibility-engineer (gemini projection, paired with `wcag-conformance-audit`); natural slot is the verify stage of any media deliverable.
6. **OVERLAP** — No external coverage of *media* a11y. Nearest neighbors: `chrome-devtools-mcp:a11y-debugging` (web DOM, not media artifacts) and the designer brief's "design tokens, Figma fidelity, a11y" (UI, not captions/transcripts). Live sibling `wcag-conformance-audit` owns measurement; the split is clean.
7. **REDUNDANCY** — A capable model writes decent alt-text unaided. Earns its place through two house rules: the PASS-blocker gate and the `capability_gap`/never-invent vocabulary. Thin but real.
8. **IMPROVEMENT** — Name the actual perception path per lane (which runtime can ingest audio/video, and the fallback when none can); step 1 is currently unexecutable for audio on every lane.
9. **UNKNOWN** — Whether any dispatch has ever read it (no read-instruction exists anywhere); whether multimodal audio ingest is live on any lane.

## 2. audio-event-map-authoring

1. **WHAT** — Author the typed game-event → audio-cue contract (`audio-event-map.json`) that hands an interactive-audio design to the engine; triggers at the game-audio → engine handoff.
2. **CLARITY** — Most concrete of the batch. Vaguest step: "Record memory/voice-count/streaming budgets and loop/loudness/format requirements" — no units, no engine, no source for what the budgets should be.
3. **EFFECTIVENESS** — Steps 2–3 do the real work: "define the cue, transition/cancellation behavior, parameter IDs, and units/ranges" plus "Specify a missing-cue fallback for every event so the runtime never silently fails" actually define the contract's field set.
4. **SAFETY** — None. Nothing destructive, credential-touching, or outward-facing.
5. **USEFULNESS** — Strongest consumer story in the batch: interactive-audio-designer (gemini projection), and the capability card `shared/capabilities/project/audio-assets.md` names it at both S1 and S3.
6. **OVERLAP** — No external plugin. In-repo duplication instead: the canonical brief `departments/content/specialists/interactive-audio-designer.md:58` restates the entire acceptance list — "schema version; unique/stable event and parameter IDs; transition/cancellation behavior; units/ranges; missing-cue fallback; middleware/runtime target; memory/voice-count/streaming budgets; loop/loudness/format requirements; and test scenarios" — so the same contract lives in the brief, the skill, and the capability card.
7. **REDUNDANCY** — This is house-contract knowledge, not general competence: `audio-event-map.json` is a repo-invented artifact. But since the brief already carries the identical acceptance list, what the skill adds over the brief is only step ordering.
8. **IMPROVEMENT** — An actual JSON Schema file. The "typed contract" exists only as prose in three homes; none is machine-checkable, and no example instance exists anywhere in the repo.
9. **UNKNOWN** — Whether an `audio-event-map.json` has ever been produced by any dispatch (none found in the tracked tree; `_state` excluded from search).

## 3. audio-layering-techniques

1. **WHAT** — Build a composite sound from sub/body/transient/texture layers without masking or phase cancellation; triggers during SFX asset design.
2. **CLARITY** — DAW-operator language throughout. Vaguest: "Align transients and check phase/polarity between layers; correct cancellation before it reaches the mix" — no lane has a tool that can do this, and "Reference the composite mono and at low volume" is unexecutable for a text agent.
3. **EFFECTIVENESS** — No step does real work in our runtime: the procedure assumes a human at a DAW mixing stems, while our sounds come out of `generate_audio`/ElevenLabs whole, not as layers the agent combines. As generation-prompt guidance it is not framed that way.
4. **SAFETY** — None.
5. **USEFULNESS** — sound-designer (gemini projection) is the declared consumer, but the workflow mismatch above means no identified *realistic* consumer as written.
6. **OVERLAP** — None external; no plugin or wired skill touches audio mixing. Hands off cleanly to siblings ("hand the final mix decision to `sound-design-principles`/`audio-production-basics`" — both live).
7. **REDUNDANCY** — Frequency-slotting, phase checks, and mono referencing are general audio-engineering competence any capable model already has. No house rule, gotcha, gate, or tool-surface knowledge. Adds nothing as written.
8. **IMPROVEMENT** — Rewrite against the actual tool surface: either prompt-level layering guidance for generation routes, or concrete ffmpeg (`amix`, `aeval`, polarity-invert null test) recipes that make phase/mono checks executable.
9. **UNKNOWN** — Whether ffmpeg (or any audio tool) is actually on the host for the lanes that would use this; whether any composite-sound task has ever been dispatched.

## 4. audio-production-basics

1. **WHAT** — The shared capture→edit→mix→master chain (gain staging, ordered mixing, loudness-targeted mastering) under any audio deliverable; triggers whenever audio is produced or finished.
2. **CLARITY** — Vaguest step: "Verify on multiple playback systems and in mono" — impossible for an agent and no measurement alternative named. Best discipline line: "Master to the target loudness standard (e.g. streaming/broadcast LUFS)… state the target, don't guess."
3. **EFFECTIVENESS** — The two load-bearing rules are the mix ordering ("balance first (levels, pan), then corrective/creative EQ and dynamics, then space… in that order") and the stated-LUFS mastering target. The latter is genuinely machine-checkable via ffmpeg `ebur128` — which the skill never names, so as written its Acceptance ("no clipping or true-peak overs") cannot be verified in-lane.
4. **SAFETY** — None.
5. **USEFULNESS** — Widest projection in the batch: music-composer, sound-designer, and voice-narrator (gemini). Slot: the finishing step of any audio asset.
6. **OVERLAP** — None external.
7. **REDUNDANCY** — Gain staging, LUFS, true-peak limiting are general competence. The house value would be naming *our* per-platform loudness targets; it doesn't. What remains is the "state the target, don't guess" discipline — a house rule, but one sentence's worth.
8. **IMPROVEMENT** — Name the measurement command (ffmpeg `loudnorm`/`ebur128`) and a house delivery-target table so all three Acceptance bullets become checkable.
9. **UNKNOWN** — Whether any deliverable has ever gone through this chain; whether ffmpeg is present on the executing hosts.

## 5. color-grading-basics

1. **WHAT** — Correct-then-stylize video grading verified on scopes (white balance, shot matching, skin-tone/broadcast-legal protection); triggers at video finishing.
2. **CLARITY** — Vaguest: "set white balance, exposure, and contrast using scopes (waveform/vectorscope), not guesswork" — no tool that renders a scope is named; and "Verify on a calibrated reference" is unavailable to any lane (the escape hatch "note assumptions when calibration is unavailable" is honest).
3. **EFFECTIVENESS** — None of the steps execute on our surface: grading happens inside generation models or an NLE we don't drive. Residual value is as a review rubric for generated footage — "Match shots within a scene so cuts don't jump in brightness or color" is checkable by inspection.
4. **SAFETY** — None.
5. **USEFULNESS** — video-editor (gemini projection). Our video-editor brief is "video trim/edit/captions" — grading is adjacent but not evidenced in any workflow.
6. **OVERLAP** — No external plugin grades video. The look/mood layer is owned upstream by the higgsfield MCP's generation workflows ("Before building any multi-step, made-to-brief video… call get_workflow_instructions first"), where the "creative look" is a prompt property, not a grade.
7. **REDUNDANCY** — Correct-before-grade, skin-tone protection, and broadcast-legal ranges are general colorist competence. No house rule, gate, or tool knowledge. Adds nothing as written.
8. **IMPROVEMENT** — Reframe as consistency review of AI-generated footage (shot-match across cuts — the house's actual recurring problem) and name the executable path: ffmpeg ships `waveform` and `vectorscope` filters that would make step 1 real.
9. **UNKNOWN** — Whether any in-house grading (vs. look-baked-in generation) has ever occurred.

## 6. color-theory

1. **WHAT** — Choose and justify a palette by mechanism (harmony relationship, named roles, contrast, tokens); triggers at palette/design-system work.
2. **CLARITY** — Most executable of the visual trio. Vaguest: "Account for color meaning/culture and color-vision deficiency" — no method, checker, or reference named.
3. **EFFECTIVENESS** — Step 2 (relationship + named roles "primary/accent/surface/text, not just a hex") and step 5 (tokens with light/dark values) do the real work; step 3 correctly delegates measurement: "hand off measurement to `wcag-conformance-audit`" (live sibling).
4. **SAFETY** — None.
5. **USEFULNESS** — image-designer (gemini projection); also generically useful to designer/frontend work, though those surfaces bring their own guidance (see overlap).
6. **OVERLAP** — Real collision with the wired session skill `dataviz`, whose trigger text claims "choosing chart colors… a color formula with a runnable validator… categorical colors, sequential / diverging palette" — for the data-viz slice, `dataviz` is strictly stronger (it has a validator). The `frontend-design` plugin ("distinctive, production-grade frontend interfaces… avoids generic AI aesthetics") covers UI palette selection in practice.
7. **REDUNDANCY** — Harmony systems, CVD, and no-hue-only signaling are general competence (the latter is WCAG 1.4.1). Earns a marginal place via the `wcag-conformance-audit` handoff and the tokens-not-hexes house discipline.
8. **IMPROVEMENT** — Bind step 5 to the house token format/home (the designer specialist owns "design tokens" — name the actual file/format) so "expressed as reusable tokens" means one specific thing.
9. **UNKNOWN** — Whether a canonical design-token home exists in this repo to bind to.

## 7. composition-rules

1. **WHAT** — Arrange elements in a frame for a named focal point, explicit structure, and reading path; triggers on layout/frame design for images or layouts.
2. **CLARITY** — Vaguest: "Control visual weight and balance so nothing competes with the focal point unintentionally" — pure judgment with no check attached.
3. **EFFECTIVENESS** — One step has teeth: "Verify the composition holds at the delivery size and on the busiest real content, not just the ideal mock." The rest restates rule-of-thirds textbook material.
4. **SAFETY** — None.
5. **USEFULNESS** — image-designer (gemini projection); plausible slot is composition language while authoring generation prompts — which the skill never mentions.
6. **OVERLAP** — Partial collisions on three sides: `frontend-design` plugin ("Create distinctive, production-grade frontend interfaces with high design quality") for web layout; `figma:figma-generate-design` for layout inside Figma; and wired `visual-verify` ("seen, driven, and measured" acceptance) already institutionalizes the step-5 real-content check for UI.
7. **REDUNDANCY** — Rule of thirds, golden ratio, whitespace, proximity: general competence. Its one distinctive rule (survive real content and target crop) is owned by `visual-verify` where it matters. Adds nothing beyond that.
8. **IMPROVEMENT** — Retarget to what image-designer actually does: composition vocabulary that steers image *generation* (framing/camera terms diffusion models respond to) — that would be house tool-surface knowledge no generic text provides.
9. **UNKNOWN** — Whether any image-designer dispatch has consulted it (not determinable from the repo).

## 8. music-production-basics

1. **WHAT** — Take a musical idea to a finished track (brief, arrangement, sound selection, mix with headroom); triggers on music asset production.
2. **CLARITY** — Vaguest: "Verify against the references and the delivery format" — an agent cannot listen and no measurable proxy is named.
3. **EFFECTIVENESS** — Step 1 does the real work in our pipeline: "Define the brief: genre, tempo, mood, reference tracks, and where the music will be used (length/format)" — that is exactly the spec a generation route (Lyria/`generate_audio`) consumes. Steps 2–4 assume DAW production we don't perform.
4. **SAFETY** — Safety-positive rights line: "clear any sampled/recognizable material for rights before use" / "Samples/recognizable material are rights-cleared, not assumed free" — though it names no gate or owner (contrast sound-design-principles, which names `rights-and-provenance-gate`).
5. **USEFULNESS** — music-composer (gemini projection).
6. **OVERLAP** — Generation itself is owned by the higgsfield MCP ("generate_audio… as the core tools for image, video, and audio creation"). The mix/master steps hand off to `audio-production-basics` explicitly, so sibling overlap is managed.
7. **REDUNDANCY** — Arrangement arcs and frequency separation are general competence; the rights line duplicates gates that already exist at capability-card level. Earns a marginal place only via step 1's brief-field list.
8. **IMPROVEMENT** — Convert into a music-brief spec aligned to the live generation route's actual parameters, and point the rights line at the named gate/specialist (`rights-and-provenance-gate` / asset-provenance-and-rights-auditor).
9. **UNKNOWN** — Whether the music generation route is live at nonzero budget (vault memory on media routes is disputed on exactly this point).

## 9. sonic-branding

1. **WHAT** — Design a brand's audio identity — logo/mnemonic, motifs, variation system, usage rules; triggers on a brand-audio engagement.
2. **CLARITY** — Vaguest: "Ensure originality and clearance — no derivative of a protected mnemonic" — no method exists on any lane to check audio originality, and none is suggested.
3. **EFFECTIVENESS** — Steps 3–4 carry the deliverable: "Define a system: variations for different lengths/media (app, ad, hold music, UI), all traceably from the core" plus written usage rules. Step 1's attribute→sonic-quality mapping "with a rationale, not a vibe" is good discipline.
4. **SAFETY** — Publish-adjacent subject matter but no publishing step; rights handled by flag only: "flag rights concerns for review" (no named gate or owner).
5. **USEFULNESS** — music-composer (gemini projection). No brand-audio engagement is evidenced anywhere in the repo; the consumer is declared but the workflow is hypothetical.
6. **OVERLAP** — None external. The brand-voice specialist ("operator voice consistency check") owns brand consistency for *prose* only; no plugin or wired skill touches sonic identity.
7. **REDUNDANCY** — Sonic-branding frameworks are general competence. No house rule, gotcha, gate, or tool knowledge beyond the generic "flag for review". Adds nothing tool-specific.
8. **IMPROVEMENT** — Point its rights/clearance flag at the actual named gate (`rights-and-provenance-gate`) and specialist (asset-provenance-and-rights-auditor) instead of an unnamed "review".
9. **UNKNOWN** — Whether a sonic-branding engagement has ever been requested or is anticipated (no evidence either way).

## 10. sound-design-principles

1. **WHAT** — Intent-driven sound design for UI/film/games — each sound's function, envelope, and family consistency; triggers when designing a set of sounds.
2. **CLARITY** — Vaguest: "Ensure sounds read against the target playback context (small speakers, noisy rooms, spatial mix)" — unmeasurable in-lane, no proxy named.
3. **EFFECTIVENESS** — Steps 1 and 3 shape a real spec ("State what each sound must communicate (event, affordance, feedback, mood) and to whom"; "families of sounds that feel related and distinguishable") — like music-production, it works as prompt-spec discipline rather than as a production procedure.
4. **SAFETY** — Strongest rights language in the audio set, correctly routed: "never self-clear a recognizable voice or copyrighted sample; flag for `rights-and-provenance-gate`" (live sibling).
5. **USEFULNESS** — sound-designer (gemini projection).
6. **OVERLAP** — None external; internal cross-reference (`rights-and-provenance-gate`) is live and non-duplicative.
7. **REDUNDANCY** — Envelope-fits-event and sonic-family thinking are general competence; earns a marginal place via the named rights gate and the function-first spec framing.
8. **IMPROVEMENT** — Fold in the actual generation route's controllable parameters (what ElevenLabs SFX generation can and cannot control) so steps map to executable knobs; the gemini sound-designer adapter itself says the route is "blueprint-only unless… receipts".
9. **UNKNOWN** — Whether the SFX generation route is live (adapter description says blueprint-only pending receipts; not probed here).

## 11. video-post-production

1. **WHAT** — The edit-to-delivery pipeline (assembly, cut, audio finish, titles/grade, per-platform export); triggers when a rough edit must become a finished deliverable.
2. **CLARITY** — Vaguest: "Refine the cut for pacing and continuity… remove what doesn't earn its place" — judgment without method; and "verify the render before shipping" names no check (ffprobe would be the obvious one).
3. **EFFECTIVENESS** — Step 5 is the one our video-editor can actually execute: "Export to each platform's spec (resolution, codec, aspect, loudness); verify the render" — that is real ffmpeg work. Steps 1–4 are NLE-craft prose.
4. **SAFETY** — None destructive; ship-adjacent, but the publish gate is owned by capability cards/operator gates, not this file.
5. **USEFULNESS** — video-editor (gemini projection, alongside `platform-compliance`); aligns with the video-editor brief ("video trim/edit/captions").
6. **OVERLAP** — The assembly end is owned by the higgsfield MCP's made-to-brief workflows ("a narrated explainer or story video, an ad / commercial, a UGC / talking-head video… call get_workflow_instructions first"). Titles overlap house ffmpeg-typography practice (recorded in vault memory, not in any skill). Sibling cross-refs (`narrative-pacing`, `audio-production-basics`, `color-grading-basics`) are all live.
7. **REDUNDANCY** — Cutting craft is general competence. Earns a marginal place via the platform-export-spec step — but that step is not operationalized (no ffprobe, no spec table), and `platform-compliance` (projected beside it) likely owns the spec half.
8. **IMPROVEMENT** — Name the verification tool (ffprobe against a per-platform spec table) and reference `platform-compliance` explicitly instead of leaving "each platform's spec" unsourced.
9. **UNKNOWN** — Whether a house platform-spec table exists (inside `platform-compliance` or elsewhere) — not read in this batch.

## 12. video-production-principles

1. **WHAT** — Pre-production shot planning — shot language, coverage, continuity (180° rule), lighting; triggers before any video is generated or shot.
2. **CLARITY** — Vaguest: "Plan lighting and framing to direct attention and set mood consistently across setups" — we operate no lights; the mapping of this vocabulary onto generation prompts is nowhere stated.
3. **EFFECTIVENESS** — Step 1 does real work and maps directly onto the video-director's actual job (per-shot generation briefs): "Derive the shot list from the script/brief: what each shot must show and why it earns screen time." Coverage/continuity steps still apply conceptually to multi-shot AI video but are framed for a film set.
4. **SAFETY** — None.
5. **USEFULNESS** — video-director (gemini projection, beside `narrative-pacing`).
6. **OVERLAP** — The templated version of exactly this is owned by the higgsfield MCP: "Before building any multi-step, made-to-brief video from a user request — a narrated explainer or story video, an ad / commercial, a UGC / talking-head video, a podcast… call get_workflow_instructions first." The skill's generic shot-planning duplicates what those workflow instructions deliver per-format.
7. **REDUNDANCY** — Shot language and the 180° rule are film-school general competence. The house's *actual* recurring shot-to-shot problem — character/set drift across generated shots — is recorded in vault memory and appears in no skill, including this one. As written, adds nothing house-specific.
8. **IMPROVEMENT** — Rewrite for AI shot generation: continuity across generated shots (character consistency, prompt token position, what the shot SHOWS front-loaded), which is where house experience actually exists.
9. **UNKNOWN** — Whether any video-director dispatch produced a shot-list artifact (none found in tracked tree).

## 13. voice-performance-direction

1. **WHAT** — Direct a human or synthesized voice read — intent definition, script markup, direction passes, take continuity; triggers on narration/VO production.
2. **CLARITY** — Vaguest: "Direct in passes (intent → energy → nuance); give specific, actionable notes, not 'do it better'" — presumes an iterating performer; how passes map onto TTS regeneration parameters is unstated.
3. **EFFECTIVENESS** — Step 2 is the step that does real work and survives into a TTS prompt: "Mark the script for delivery: emphasis, pace, pauses, tone shifts, and pronunciation of tricky terms."
4. **SAFETY** — Strong, correctly-routed consent gate: "never direct a synthesized clone of a real person's voice without cleared consent; flag for `consent-and-likeness-check`" (live sibling). Acceptance repeats it: "Voice-likeness consent is verified, never self-cleared."
5. **USEFULNESS** — voice-narrator (gemini projection, beside audio-production-basics).
6. **OVERLAP** — None external — ElevenLabs generates voices but nothing else covers *direction*. One **dead cross-reference**: step 4 says "coordinate `voice-consistency-audit`" — that skill now lives at `shared/skills/_retired/voice-consistency-audit.md`. The live capability card `shared/capabilities/project/audio-assets.md:26` cites the same retired name ("`voice-consistency-audit` (stub)"), so the dangling pointer exists in two live homes.
7. **REDUNDANCY** — Script markup and the consent gate are the earners (house gate + concrete artifact); the human-session direction-passes content doesn't map to our surface.
8. **IMPROVEMENT** — Fix the retired `voice-consistency-audit` reference (and its twin in the audio-assets card) — either to a live successor or by inlining the continuity check; then map "passes" onto actual TTS regeneration parameters (e.g. ElevenLabs stability/similarity).
9. **UNKNOWN** — Whether anything replaced `voice-consistency-audit` after retirement (no live successor found by name).

## 14. interactive-audio-design

1. **WHAT** — Design the interactive layer over generated audio for games — adaptive-music states, SFX pools, ducking rules, per-cue budgets; triggers on game-audio design work.
2. **CLARITY** — Concrete for its domain. Vaguest: "Derive audio states from the game state model (menu, explore, combat, etc.)" — assumes a game-state-model artifact exists and is findable; no source named.
3. **EFFECTIVENESS** — Steps 1–5 genuinely constitute the method (states → stem layers with transition behavior → randomized SFX pools → deterministic ducking "as deterministic parameters, not vibes" → per-cue trigger/parameter/budget). Step 6's handoff split (rendering to audio specialists, integration to `game-engineer`) matches the live roster. With audio-event-map-authoring, the best-constructed skill in the batch.
4. **SAFETY** — Safety-positive: "never self-clear voice-likeness."
5. **USEFULNESS** — interactive-audio-designer (gemini projection; note the claude adapter for the same specialist projects `interface-ambiguity-check` instead — lane asymmetry). Capability card audio-assets S1 names it explicitly.
6. **OVERLAP** — Pairs with `audio-event-map-authoring` without duplicating it (design vs. contract). No external plugin covers adaptive game audio.
7. **REDUNDANCY** — Adaptive-audio patterns (vertical layering, horizontal re-sequencing, round-robin) are general game-audio competence, but the handoff topology — who renders, who integrates, and the `audio-event-map.json` contract between them — is house knowledge. Clearest earner of the 14.
8. **IMPROVEMENT** — Resolve the three-home duplication: the state/budget/acceptance language now lives in this skill, the canonical brief (line 58), and the capability card; declare which home wins.
9. **UNKNOWN** — Whether any game project has ever exercised it (no game-audio artifacts found in the tracked tree).

---

## Domain coverage gaps

Looking at the set against the actual roster and workflows, the batch covers **classical craft theory** while the house's **actual media workflow — generation — has no skills at all**:

- **No generation-workflow skill for any modality.** The specialists' real work is driving `generate_image`/`generate_video`/`generate_audio`/ElevenLabs, yet no skill covers prompt-spec authoring, iteration loops, or route selection. The batch's two most "effective" steps (music brief fields, shot-list derivation) are generation-brief authoring smuggled inside DAW/film-set procedures.
- **No shot-continuity/character-consistency skill** — the house's documented recurring video failure (character drift, token position, ash-tone) lives only in vault memory; `video-production-principles` is the natural home and doesn't mention generation.
- **No measurable media-QA skill** — nothing teaches ffprobe/ffmpeg `ebur128`/scope-filter verification, so every audio/video Acceptance gate in the batch is unverifiable in-lane. A single "media verification with ffmpeg" skill would give five of these skills their missing teeth.
- **No captions/subtitle production mechanics** — video-editor's brief says captions; `accessible-media-authoring` says what good captions are; nothing says how to produce/time them on our surface.
- **No rights-clearance workflow skill** — three skills flag rights three different ways (named gate / unnamed "review" / bare "clear rights"), while asset-provenance-and-rights-auditor exists as a specialist. The inconsistency suggests a missing shared skill the three would reference.
- **No localization/dubbing skill** despite localization-specialist in the same roster; no podcast/short-form skill despite the higgsfield podcast workflow and social-strategist existing.
- **Inverted coverage**: game audio (a workflow with no evidenced project) gets the two best skills; the generation pipeline (the evidenced daily workflow) gets zero.

## What surprised me

1. **The declared read path is instruction-free.** Every skill has a declared consumer via projection, and the registry says "read-on-start" — but no adapter body or canonical brief ever instructs reading `shared/skills/<name>.md`, and gemini's projection block is inside an HTML comment. Declared ≠ reaching, in exactly the Rule-9 sense.
2. **Lane asymmetry in projections**: gemini projects batch D to its media specialists; the claude adapters for the same specialists project nothing (sound-designer) or different skills (interactive-audio-designer → `interface-ambiguity-check`).
3. **The retirement swept sources out from under live references twice over**: `voice-performance-direction` (step 4) and the live capability card `audio-assets.md:26` both cite retired `voice-consistency-audit`; and — outside this batch but observed live — the claude editor adapter running *this very task* declares `skills: ["cite-properly", …, "writing-skills"]`, both of which exist only under `shared/skills/_retired/` (no live file; `writing-skills` plausibly superseded by the superpowers plugin skill, `cite-properly` with no visible successor).
4. **Template uniformity**: 14 files, two bulk commits, 20–21 lines each, identical structure, zero `description:` frontmatter — this is one authoring pass wearing fourteen names, and its quality ceiling (good Acceptance rubrics, unexecutable verify steps) is uniform in the same way.
5. **The audio-event-map contract has three prose homes and zero schema** — for a "typed" contract, no JSON Schema and no example instance exists anywhere in the tracked tree.

## Method / evidence

- Read all 14 files in full (one parallel batch); confirmed presence/absence in `.claude/skills/`, `.agents/skills/`, `shared/skills/_retired/`.
- Existence-checked every cross-referenced sibling: live — `wcag-conformance-audit`, `rights-and-provenance-gate`, `narrative-pacing`, `consent-and-likeness-check`; retired — `voice-consistency-audit`.
- Mapped consumers via `capability_skills` in `model-lanes/gemini/.gemini/agents/*.md`, verified skill names present in `model-lanes/specialist-lane-capabilities.v1.json`, cross-checked claude-lane adapters, `shared/registries/skill-tool-registry.tsv` rows, and `shared/capabilities/project/audio-assets.md`.
- Checked canonical briefs (`sound-designer.md`, `interactive-audio-designer.md`) for skill-name mentions; checked git first-add commits for provenance.
- Vault: one `recall` performed (5 notes returned; media-route and roster notes informed context; two returned notes are flagged `disputed` and were treated as contested). `record` + `record_usage` telemetry executed after this artifact was written.
- `subagents: 0` — solo, with batched parallel tool calls.

## needs_tool

None — every declared tool I attempted worked (`Read`, `Bash`/shell, chrono-vault `recall`/`record`/`record_usage` via MCP).
