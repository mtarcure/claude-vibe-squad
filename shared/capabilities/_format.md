# Capability file format (canonical schema)

Every `shared/capabilities/<mode>/<capability>.md` file conforms to this schema. It instantiates the
`shared/capabilities/_skeleton.md` S0–S7 spine. This doc locks the format so Phase-1b (the remaining ~27)
is mechanical. The four exemplars (`project/web-app`, `bounty/smart-contract-web3`, `content/image`,
`project/self-extension-agent-tooling`) are the reference implementations.

## Ground truth (authority for the machine columns)

`shared/registries/skill-tool-registry.tsv` (APPROVED at `b2a91d6`) is the authority for every skill's
`type` and every tool's `verified_state`/`cost_tier`. **Cite the registry, not your own judgment, for those
columns.** `shared/api-catalog.md` is the underlying evidence the registry points at. Where the registry
and a decided review resolution disagree on a value, the resolution's grounded value wins for the exemplar
and the registry row is reconciled to match (as was done for the local-CLI cost-tier row-class at
`d1f3c5f`; see the `—` note below).

## Frontmatter

```yaml
---
id: <mode>/<capability>            # matches the file path; the closed `capability:` packet value
mode: project | bounty | content | outreach | research | incident | maintenance | triage
title: <Human-readable title>
capability_state: live | lane-gated | degraded-blueprint | needs_tool   # conservative default
state_reason: <one line — why this state>
state_evidence: <registry / api-catalog / roster citation backing the state>
overlays: [review, truth-rights, impact, accessibility, privacy, memory]  # only those that apply
gates: [<operator_gate tokens>]   # public_release · paid_media · production_mutation · credential_change · delete · cleanup · live_outreach (+ manual-hold notes for offensive_execution/malware_detonation)
cost_note: <which steps are subscription / metered / free-local, + budget guard for metered>
---
```

- **`capability_state` is a conservative default now; Phase-2's `bin/validate-capabilities.sh` will DERIVE
  it** from the per-lane tool-verify. If any core-step tool is not live (`yes`/`lane-live`), the capability
  cannot be `live`. Never assert `live` without `state_reason`/`state_evidence`.

## Step blocks (S0–S7)

Steps use the skeleton spine; **count varies** (expand S3 for rich work, collapse S1–S2 for simple work).
Present them as one 5-column table:

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|

### Specialists — canonical IDs + three sentinels only
- Every specialist token is **backticked**. The validator rule: a backticked specialist token must be
  either a **canonical roster ID** (exists in `shared/specialist-runtime-map.tsv`) **or** one of exactly
  three whitelisted **backticked sentinels** — no other non-roster token is allowed. No phantom roster IDs.
- **The three sentinels** (`` `Chrono` `` / `` `operator` `` / `` `cross-family-reviewer` ``):
  - `Chrono` — the controller/orchestrator (owns S0 intake, dispatch, S7 capture-recording).
  - `operator` — the human at a gate.
  - `cross-family-reviewer` — the independent review lane (the review overlay's reviewer).
- When Chrono delegates work, name the sentinel **and** the real roster specialist(s) separately (e.g.
  `Chrono`, `triage`). Never use free phrases like "Chrono direct", "cross-family reproducer", or
  "Chrono + contributing specialists".

### Tools — one tool = one tuple = one lane
- Grammar: `` `tool` (lane · state · cost_tier) ``. **`lane` is a single value** from the closed enum:
  `claude | codex | gemini | kimi | all | local | none | unknown` (`all` = the 4 model lanes, matching the
  registry; `unknown` only for catalog-absent/unregistered tools).
- **`state`** is the registry's `verified_state`: `yes | lane-live | partial | needs-research |
  catalog-absent | no`. Only `yes` and `lane-live` (with its lane caveat) are **live-capable**; `partial`,
  `needs-research`, `catalog-absent`, and `no` fail closed → the step is `needs_tool`/degraded-blueprint.
- **`cost_tier`** ∈ `subscription | metered | unknown | —`:
  - **`subscription`** — a CLI lane's native/lane-covered operation (model inference, native CLI
    subcommands, chrono-* MCPs, Claude plugins). No paid-per-call provider, no free local binary.
  - **`metered`** — paid provider passthrough (xAI, Perplexity, the `generate_image`/`video`/`audio`
    wrappers, ElevenLabs, direct-API providers). Requires a budget/rate-limit guard; a hit limit is a
    typed `needs_tool`/degraded result, never a silent stall.
  - **`unknown`** — FAIL-CLOSED: the tool is **not resolvable to a billing model** (typically a
    catalog-absent / `needs_tool` tool, e.g. `chrome-devtools` / `playwright` / `figma` / `firebase`).
    Distinct from `—` (which is *resolved* as no-billing/public); an `unknown` cost blocks execution until
    the tool is cataloged and its billing resolved.
  - **`—`** — a public local CLI (`access: Public` in api-catalog §12: foundry, slither, mythril, echidna,
    the recon/SAST binaries). Runs locally, bills nothing. (Reconciled at `d1f3c5f`: the registry now marks
    this row-class `—`, matching the exemplars.)
- **Multiple tools in one step = multiple comma-separated tuples.** FORBIDDEN: multi-lane tuples like
  `claude/codex` (split into two tuples), slash-grouped tools sharing one tuple (`forge/cast/anvil`), and
  grouped ad-hoc CLI subcommands. Cite the registry's **exact tool name** (e.g. `claude mcp/plugin/agents`
  is one registry token = one tuple; do not invent your own grouping). No inline prose token (e.g. bold
  **WRAPPER**) — the wrapper-vs-raw distinction is carried by naming the wrapper tool + the raw-tool rule
  below, not an inline label.

### Skills — four display tokens mapped from the registry `type`
`` `skill` (<display>) ``, where `<display>` is the display token **mapped** from the registry's literal
`type` value. The mapping is 1:1 (the display tokens are not copied verbatim from the TSV):

| Registry `type` (literal) | Display token |
|---|---|
| `invokable` | `(SKILL.md)` |
| `authored-pattern-doc` | `(authored)` |
| `pattern-doc-stub` | `(stub)` |
| `pattern-doc-untyped` | `(untyped)` |

- **`(SKILL.md)`** — one of the 4 real invokable skills (chrono-vault `compact-now`/`blind-rediscovery`/
  `parity-probe`; codex-agent `sandbox-provision-discipline`). Where the registry flags the skill `stale`,
  append `— stale` as **trailing prose OUTSIDE the tuple** (e.g. `` `parity-probe` (SKILL.md) — stale ``);
  the tuple itself stays one of the four legal forms.
- **`(authored)`** — a `shared/skills/*.md` with `status: authored` (read-on-start methodology reference).
- **`(stub)`** — a `shared/skills/*.md` with `status: stub`. Read-only draft; **cannot** satisfy a required
  skill until authored + reviewed.
- **`(untyped)`** — a `shared/skills/*.md` missing `status` frontmatter. Fails closed until typed.
- **Phase-1b rule (mandatory):** read each skill's literal `type` straight from the registry TSV and apply
  the mapping above. **A skill absent from the registry is `(untyped)`.** Never promote a `stub`/`untyped`
  file to `(authored)`.

### Gate / Overlay
The operator_gate token(s) and/or the overlay firing at that step.

## Overlays (declared in frontmatter; fired at named steps)
review (S5, mandatory at `safety_level:high`/`heightened_risk`, cross-family) · truth-rights (fires at
**S4 Verify**, content/publish) · impact G1–G4 (S4→S5, bounty) · accessibility (S4, UI/media) · privacy
(any step, PII) · memory (S0 recall + S7 record). See `_skeleton.md` for triggers/owners.

## Honesty rules (enforced later by the validator; hold now by authoring discipline)
1. Every specialist ID ∈ canonical roster (or one of the 3 sentinels).
2. Every tool's `state`/`cost_tier` and every skill's `type` trace to the registry TSV (or api-catalog).
   A tool not live for its lane is `needs_tool`.
3. `capability_state` is justified by `state_reason`/`state_evidence`.
4. Offensive gates (`offensive_execution`/`malware_detonation`) are "present in runtime metadata; enum +
   validator reconciliation pending" → manual hold, never "machine-enforced".
5. **Raw-tool rule:** never claim raw `higgsfield__*` as live (`verified:yes`); it may appear ONLY as
   `verified:no` to document why the `generate_image`/`generate_video`/`generate_audio` wrapper is the live
   route.
6. Metered tools carry a cost/rate-limit note; a hit limit is a typed `needs_tool`/degraded result.
