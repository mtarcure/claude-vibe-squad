---
name: blind-rediscovery
description: Operational checklist + helper for blind-rediscovery fan-out work. Splits per-target dossiers into _blind/ (voice-readable, no prior-finding refs) and _curated/ (operator-only, prior findings + comparisons). Use when running Stage 3 hypothesis exploration on a target with prior chrono work.
type: skill
---

# Blind rediscovery — operational checklist

When chrono runs blind rediscovery (e.g. "does v1.3 reproduce findings from a prior daemon run?") the validation signal IS voice independence. If a fan-out voice reads a Stage N dossier that names prior findings by ID/class, the experiment is invalid.

This skill operationalizes the `_blind/` vs `_curated/` split codified in `CLAUDE.md` "Dossier authoring convention" so the discipline becomes a checklist, not just prose.

## When to use

- Running Stage 3 hypothesis exploration on a target with EXISTING saved findings
- Validating a v1.3 system pass against legacy daemon work from a predecessor project
- Any case where "did the voices arrive at this independently?" is the core question

## When NOT to use

- Resuming a known finding for PoC drafting (Stage 4) — voices need the prior work
- New target with no prior chrono history — there's nothing to contaminate
- Bulk-mechanical refactor / lint pass — no judgment, no voice independence to preserve

## Directory layout

For a target with the slug `<target>`. The casing is load-bearing: `dispatch_context_builder.
enforce_blind_floor()` keys the dispatch-level floor on exactly this path, and the maintainer's
volume is case-insensitive, so a lowercase `chrono/` here would resolve locally and fail on a
case-sensitive filesystem.

```
$CHRONO_VAULT_ROOT/Chrono/dossiers/<target>/
├── _blind/                          # fan-out voices CAN read this
│   ├── stage-1-scope-<date>.md
│   ├── stage-2-codebase-map-<date>.md   # NO prior-finding refs
│   └── ...
├── _curated/                        # ONLY brain + operator read this
│   ├── prior-findings.md            # F1, F2, etc — the saved work
│   ├── stage-3-synthesis-<date>.md  # comparison-with-prior happens here
│   └── methodology-notes.md
├── raw-voices/                      # raw fan-out outputs (also voice-readable)
└── _resume.md                       # session-resume index, brain-readable
```

## What the dispatcher already guarantees

Since 2026-08-17 the `_blind/` directory is not only a convention — it is enforced. When a packet
declares `target: <target>` and that dossier has a `_blind/` directory, `build_context` forces
`memory_aperture: cold` for every role whose specialist brief declares `blind_discovery: true`,
regardless of what the packet asked for. The briefs under `departments/*/specialists/` and
`shared/specialists/` are the roster; grep them for the key rather than trusting a list copied
into prose. See `shared/protocol.md` § The
blindness floor.

`target:` is free text and stays free text — the floor reads dossier slugs *out of* whatever the
field contains (`examplechain/<target>@0000aaaa`, `<target> / example-chain-node @ 1111bbbb`, `Target`),
so it fires on the live packet convention without the packet having to change vocabulary. A
`target:` that names no blinded dossier leaves the aperture alone; it is never a dispatch error.
Naming the dossier slug plainly is still the clearest thing to write.

That covers vault recall. It does **not** cover the two contamination paths below — dossier prose
that names prior findings, and web search for prior art. Those remain the author's job, which is
what the rest of this checklist is for. Set `target:` on every blind-rediscovery packet; the floor
is target-scoped and has nothing to key on without it.

## Pre-fan-out checklist

Before assembling the fan-out brief, verify ALL of:

- [ ] Every packet in the blind stage declares `target: <target>` so the dispatch-level floor applies

- [ ] `_blind/` exists; voice-readable dossiers live there
- [ ] `_curated/` exists; prior-findings + comparison docs live there
- [ ] `_blind/stage-N-*.md` files contain NO references to: prior finding IDs (`fnd_*`), prior attack classes (e.g. "stale BRIDGE_PROVIDER_ROLE"), or prior PoC sketches
- [ ] `_blind/stage-N-*.md` files DO contain: scope manifest, codebase map (architectural only), program rules, in-scope vuln class taxonomy
- [ ] Brief explicitly tells voices to read ONLY `_blind/` paths
- [ ] Brief explicitly forbids reading `_curated/` paths (use exact `Do NOT read /path/to/_curated/` framing)
- [ ] Brief forbids web search for prior art on the target (prior submissions on the target platform, GitHub issues, etc.)

## Post-fan-out synthesis (where contamination is allowed)

After voices return their independent outputs, the synthesis stage IS allowed to read `_curated/` for comparison. Synthesis dossier lives in `_curated/`, not `_blind/`. Synthesis includes:

- Convergence table: which targets did N voices independently surface?
- Comparison to prior findings: did voices rediscover F1 / F2 etc.?
- Minority report: single-voice insights worth preserving
- Contamination notes: any `_blind/` content that accidentally hinted at priors

## If contamination is discovered mid-pass

If a voice's output reveals it had access to prior-finding hints (the "GPT-5.5 explicit caveat" pattern from 2026-04-30 Dexalot Stage 3):

1. Flag in the synthesis dossier — that voice's contaminated targets cannot count as independent rediscovery
2. The voice's INDEPENDENT targets (those not in priors) still count
3. Score system-validation against the clean independent targets only
4. Patch the `_blind/` dossier authoring for next pass; update this checklist if the leak path was novel

## Authoring rule for new stage dossiers

Every new dossier in `_blind/` should pass this self-check:

> "If a voice reading this dossier had no other knowledge of the target, would they end up with the same priors as a voice that has access to my full prior-findings file?"

If yes — the dossier is contaminated. Move the prior-finding refs to `_curated/`.

## Cross-references

- `CLAUDE.md` "Dossier authoring convention — `_blind/` vs `_curated/`" section
- `feedback_chrono_blind_rediscovery_methodology` (auto-memory) — durable rule
- `docs/phase9-cleanup-2026-04-30.md` — Dexalot Stage 3 contamination case study
- `plugins/chrono-vault/skills/fan-out/SKILL.md` — when fan-out vs single-dispatch
