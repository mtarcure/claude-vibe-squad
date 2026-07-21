---
name: rule6-rights-gate
description: Hard Rule 6 pre-publication rights gate — check licensing/provenance AND likeness/voice consent over a generated or third-party media asset before publish/use, and emit the machine-readable gate record. Use at the S4 Verify step of content/image, content/video, content/audio-assets (or any asset headed for publication).
type: skill
---

# Rule-6 Rights Gate

Fuses `rights-and-provenance-gate` + `consent-and-likeness-check` into one invokable pre-publication gate over a
media asset. It binds the decision to an immutable asset hash, checks licensing/provenance + real-person
likeness/voice consent, and emits a machine gate record. It uses non-legal language and never adjudicates fair
use / de-minimis; a material unresolved check is a HOLD, not a PASS.

## Procedure
1. **Bind the decision** to an immutable `subject_id` / `subject_hash` / `subject_version` and a versioned
   checklist. A modified asset (new hash) requires a NEW gate record — a prior PASS does not carry over.
2. **Provenance + licensing**, each with evidence: license/provenance, usage-terms fit (channel / territory /
   duration), trademark, watermark / C2PA markers, and music match. Record "identified match/similarity" in
   non-legal language; do NOT decide de-minimis or fair use, and never assert infringement from similarity alone.
3. **Likeness + consent:** detect real-person likeness — voice, face, or persona. Require documented consent
   scope on file, OR confirm the asset is synthetic-generic (no identifiable person). Confirm the intended use
   (channel / territory / duration) falls within the consent granted.
4. **HOLD on any material unresolved check** — a lookup/verification tool not wired, an unconsented real-person
   likeness, an unresolved license — is `HOLD`, never PASS on uncertainty. Do not self-clear a likeness.
5. **Route** PII / biometric processing to `privacy-steward` (likeness work may need both; neither is legal
   counsel). Genuinely legal-uncertain items surface to a human / counsel, not adjudicated here.
6. **Emit the gate record** (see below).

## Machine gate record (emit this)
```
rule6_rights_gate:
  result: PASS | HOLD | FAIL
  subject_hash: <hash>               # decision is bound to this exact asset version
  assurance: <full | restricted>     # restricted when reverse-image / registry / C2PA lookups are unavailable
  checklist:                         # each item: evidenced | held
    license_provenance: <...>
    usage_terms_fit: <...>
    trademark: <...>
    watermark_c2pa: <...>
    music_match: <...>
    likeness_consent: <...>
  unresolved: [<items>]              # any material item here forces HOLD
  privacy_handoff: <yes|no>          # yes if PII/biometric processing is involved
  reviewer: <role>
  timestamp: <iso>
  override: <fields, if a human override was recorded>
```

## When to invoke
- The S4 Verify step of `content/image`, `content/video`, `content/audio-assets` — any asset (generated or
  third-party) headed for publication/use.

## When NOT to invoke
- Purely internal, non-published scratch assets with no real-person likeness and no third-party material — but
  when in doubt, run it.
- As legal advice — it produces a risk record for a human/counsel, not a legal determination.

## Acceptance
- Decision is hash-bound; every checklist item is evidenced or HELD. No PASS on a material unresolved check.
- No infringement asserted from similarity alone; legal uncertainty is surfaced, not adjudicated.
- Any real-person likeness has consent on file or is HELD; consent scope matches intended use; privacy/biometric
  handoff made where processing is involved.

## Notes — sources + cross-lane discovery (honest)
- **Sources fused:** `shared/skills/rights-and-provenance-gate.md` + `shared/skills/consent-and-likeness-check.md`
  (both retained as authored pattern-docs and as the `(authored)` card citations until a discovery-smoke
  promotes card wiring).
- **Discovery is UNVERIFIED.** Filesystem-present under the neutral `.agents/skills/` root that claude / codex /
  kimi layered discovery is expected to read; per-lane discovery has NOT been smoke-verified → registry row is
  `partial`, not `yes`. Filesystem presence is not invocation proof.
- **Gemini** does not read `.agents/skills/`; it needs its own copy via `gemini hooks migrate` / agentskills.io
  (follow-up, not done here).
- Distinct from `privacy-steward` (PII/data-flow) and `asset-provenance-and-rights-auditor` (the heightened-risk
  role that owns clearance) — this skill is the media S4 self-gate + record emitter. Not yet wired into card S4
  tuples (follow-on).
