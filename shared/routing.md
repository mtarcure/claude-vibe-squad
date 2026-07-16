# Vibe Squad Routing

Chrono is the only controller and the only operator-facing voice.

```text
Operator -> Chrono -> gpt-codex | claude | gemini | kimi -> specialists
```

Markdown is the interface. Chrono writes task packets; model leads execute them; specialists are markdown role files. This document is the **narrative source of truth** for how routing works. The **machine source of truth** is `shared/specialist-runtime-map.tsv` (per-specialist rows) plus the profile/policy registries; where a specific value is in question, the TSV and registries win.

## 1. Routing principle — flat, quality-fit

Routing is chosen **per specialist on capability**, never by folder location.

- `source_namespace` — where the specialist markdown lives (`coding | security | content | content-engineer | sysmgmt | research | shared`). A **mailbox label only. It never chooses the model.**
- `compatibility_namespace` — which `departments/<namespace>/` mailbox stores the task packet.
- `to_model` — which model lead/window executes the task, taken from the specialist's row in the runtime map.
- Folder location, namespace, and mailbox never determine model choice. Two specialists in the same namespace can run on different lanes; the same capability class can span namespaces.

## 2. Per-specialist chain

Every specialist row carries a full chain, resolved from the profile registry:

- `primary_lane` + `primary_profile` — the best-fit lane for the work.
- `backup_lane` + `backup_profile` — a genuine second-best, **cross-family** on capability (different provider from primary), used on operational failover.
- `escalate_lane` + `escalate_profile` — the stronger variant/effort, engaged by `escalation_policy`.
- `review_lane` + `review_profile` — a separate reviewer lane (independent of the author; `anti_affinity: author_family` enforces this for code review).
- `throughput_lane` + `throughput_profile` + `throughput_policy` — the bulk/downshift route, gated (see §5).
- `failover_policy`, `escalation_policy` — versioned policy IDs (see §5–§6), not per-row prose.

`*_profile` values resolve through the **profile registry** to an exact model + effort + flags — e.g. `codex.sol.high`, `codex.sol.ultra`, `claude.fable.xhigh`, `claude.fable.max`, `gemini.flash.default`, `gemini.pro.deep`, `kimi.k2.7.bulk`. Claude also keeps `claude.opus.default` / `claude.sonnet.default` as **native in-lane fallback only** (`--fallback-model`), not standing lanes.

## 3. Lanes, models, and capability fit

| lane | frontier model (primary) | escalate | best-fit capability |
|------|--------------------------|----------|---------------------|
| codex | `gpt-5.6-sol` (high) | `gpt-5.6-sol` Ultra/max | implementation · tests · PoC · code review mechanics · graphics/runtime |
| claude | `claude-fable-5` (xhigh) | `claude-fable-5` max | judgment · planning · safety/security reasoning · security defense · research/synthesis/long-context · developmental content · game/level/audio design |
| gemini | `gemini-3.5-flash` | `gemini-3.1-pro-preview` (deep) | content/text · design · media/multimodal · search grounding |
| kimi | `kimi-code/kimi-for-coding` | cross-family (Fable/Sol) | **throughput-only lane — 0 primaries** |

**Kimi is the throughput-only lane.** It holds no primary assignments. It is used solely as (a) a `throughput_lane` for genuine bulk/mechanical work under the downshift gate, and (b) the `data-extraction-engineer` bulk backup. K2.7-Code is a code specialist with no independent general benchmark and a 262K context (< Fable/Sol 1M); research, synthesis, long-context, judgment, and linguistic work never route to it. `summarizer` is its one legitimate low-safety bulk primary-equivalent use.

## 4. Tool-gated media axis

`tool_gated` is an **orthogonal axis, not a fifth capability class.** Media-production specialists (image/video/audio/voice/interactive-audio and similar) are gated by which pane hosts the content-engineer plugin (higgsfield/elevenlabs), so the model is secondary and routing pins to a plugin-host lane. Where the required credential/provider is present on multiple lanes, prefer capability routing and validate tool compatibility; pin only when a required credential/provider is single-lane.

When a backup lane cannot invoke the required tools, it runs **specification-only (TBASF)**: it produces a blueprint (storyboard / SSML / EDL / event-map / code-spec), flags a clean `capability_gap` / `needs_tool`, and yields to Chrono to re-run the render on the real host. A TBASF blueprint terminates as `capability_gap`/`needs_tool`, **never `success`**.

## 5. Safety model

- **`safety_level`** (`low | medium | high`) is a **quality floor, not a complexity detector.** `high` forces the strongest profile + stricter review + `throughput.never`. Complexity escalation is separate and signal-based.
- **`heightened_risk`** (boolean) marks defense-in-depth roles: `security-analyst`, `exploit-developer`, `privacy-steward`, `threat-modeler`, `scout`, `impact-validator`, `smart-contract-engineer`, `scraping-engineer`, and the new `incident-responder`, `detection-engineer`, `software-supply-chain-engineer`, `asset-provenance-and-rights-auditor`.
- **GLOBAL safety-refusal invariant.** A genuine safety refusal on **any** lane surfaces to the operator; the same request is **never cross-family re-dispatched in either direction** (Fable-refuses → do not shop to Sol; Sol-refuses → do not shop to Fable/Gemini/Kimi). Operational blocks (overload/down/timeout) may cross-family failover; safety refusals may not. Refusals are classified by (1) structured provider/wrapper policy event, (2) typed terminal status, then (3) content heuristic **only to downgrade certainty** to `possible_refusal` + surface. A schema-valid 200-style response is terminal; short output is never treated as an operational failure.
- **`operator_gate`** — closed enum, aligned to Hard Rule 6: `delete · cleanup · credential_change · public_release · paid_media · live_outreach · production_mutation`. `production_mutation` (mutating a live production system that is not itself a public release) is **operator-ratified (2026-07-13)**. `requires_approval` in a brief is **harness tool names only** (`Write`, `Bash`, `WebFetch`, …) — domain gates live in `operator_gate`, never in `requires_approval`.
- **Downshift conjunction gate.** `throughput.downshift_gated.v1` permits the kimi bulk tier ONLY when `safety_level == low` AND no security/privacy/financial content AND a per-task Chrono bulk flag. Never a per-specialist default; `throughput.never.v1` is mandatory when `safety_level != low`, `heightened_risk`, or any `dual_use|privacy|financial` tag applies.

Policy IDs (versioned): `failover.conservative.v1` · `escalation.signal.v1` · `escalation.safety_floor.v1` (mandatory for high/heightened) · `throughput.never.v1` · `throughput.downshift_gated.v1`.

Deterministic assignment rule:
```
if safety_level==high OR heightened_risk:  escalation.safety_floor.v1 ; throughput.never.v1
elif safety_level==medium:                 escalation.signal.v1        ; throughput.never.v1
else (low):                                escalation.signal.v1        ; throughput.downshift_gated.v1 (only if no security/privacy/financial tag)
failover_policy = failover.conservative.v1   (all rows)
```

## 6. Failover — dormant, opt-in, conservative-first

`failover.conservative.v1` is the canonical policy for the built, cross-family-reviewed control plane. The implementation ships inert and remains dormant unless the operator explicitly opts in; `_state/**` and its enable sentinel are not part of a public checkout.

- When explicitly enabled, auto-failover fires **only on HARD signals**: `dispatch_ack` failure, confirmed process-exit, or a typed provider error. Ambiguous / slow / silent / missed-heartbeat / soft-or-hard-deadline → **cancel + surface, never auto-redispatch**.
- **Minimal attempt ledger** (correctness, not deferrable): `task_id, attempt_id, generation, lane, lease_owner, lease_expiry, terminal_status, effective_model_history, artifact_path, artifact_hash`. Chrono is the sole canonical outbox publisher — attempt-specific staging → content-addressed winner → atomic temp+fsync+rename, with generation fencing so a late primary cannot overwrite a backup.
- **Lease/lock** coordinates Claude's native `--fallback-model` (Fable → Opus, in-lane) with Chrono cross-family re-dispatch: cross-family only after the native chain is observed terminal; hysteresis/cooldown prevents oscillation.
- **Opus** is Claude's native fallback only (overload / in-family safety fallback), never a standing lane. Carve-out/heightened work exhausted on the in-family chain **surfaces** rather than laundering cross-family.

## 7. Dispatch contract

Every non-trivial task packet names:

- `to_model`: `gpt-codex | claude | gemini | kimi`
- `specialist`: canonical specialist name
- `source_namespace`: `coding | security | content | content-engineer | sysmgmt | research | shared`
- `compatibility_namespace`: mailbox that stores the packet
- `write_scope`: exact writable paths, or `[]`
- `review_model`: read-only reviewer lane, or `none`
- `mandatory_review`: `true | false`
- `parallel_safe`: `true | false`
- `direct_lane_work_allowed`: default `false`
- `operator_approved`: `true | false` (must be `true` for any `operator_gate` work)

### Dispatch is blocked when

- specialist is unknown or missing from the runtime map
- `to_model` or `review_model` is invalid
- `to_model` differs from the map without `model_override_reason`
- a `high` / `heightened_risk` specialist lacks mandatory review
- `mandatory_review: true` has `review_model: none`
- `review_model` equals `to_model` for mandatory review (or violates `anti_affinity`)
- `operator_gate` work has `operator_approved: false`
- write scopes overlap in-flight work

Explicit operator approval is required for every `operator_gate` action: deletes, cleanup, credential changes, public release changes, live outreach/email, paid media generation, and production mutations (Hard Rule 6).

## 8. Pointers

- Per-specialist rows: `shared/specialist-runtime-map.tsv` (machine source of truth).
- Profile/policy registries + schema: `_state/roster-redesign-2026-07-13/schema-final.md`.
- Full design rationale: `_state/roster-redesign-2026-07-13/design-v2.md` and `consult-synthesis.md`.
- Mode workflows: `shared/modes/*.md`.
