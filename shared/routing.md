# Vibe Squad Routing

Chrono is the only controller and the only operator-facing voice.

```text
Operator -> Chrono -> gpt-codex | claude | gemini | kimi | grok -> specialists
```

Markdown is the interface. Chrono writes task packets; model leads execute them; specialists are markdown role files. This document is the **narrative source of truth** for how routing works. The **machine source of truth** is `shared/specialist-runtime-map.tsv` (per-specialist rows) plus the profile/policy registries; where a specific value is in question, the TSV and registries win.

## 1. Routing principle — flat, quality-fit

Routing is chosen **per specialist on capability**, never by folder location.

- `source_namespace` — where the specialist markdown lives (`coding | security | content | sysmgmt | research | shared`). A **role/specialist-location label. It is not the mailbox (see `compatibility_namespace` below) and never chooses the model.**
- `compatibility_namespace` — which `departments/<namespace>/` mailbox stores the task packet.
- `to_model` — which model/CLI vehicle executes the task, taken from the specialist's row in the runtime map. Each dispatch spawns a fresh CLI of that model; there are no persistent lane windows.
- Folder location, namespace, and mailbox never determine model choice. Two specialists in the same namespace can run on different lanes; the same capability class can span namespaces.

## 2. Per-specialist chain

Every specialist row carries a full chain, resolved from the profile registry:

- `primary_lane` + `primary_profile` — the best-fit lane for the work.
- `backup_lane` + `backup_profile` — a genuine second-best, **cross-family** on capability (different provider from primary).
- `escalate_lane` + `escalate_profile` — the stronger variant/effort, engaged by `escalation_policy`.
- `review_lane` + `review_profile` — a separate provider-family reviewer lane. Every `mandatory_review: true` packet must preserve `anti_affinity: author_family`; same-lane self-review never satisfies it.
- `throughput_lane` + `throughput_profile` + `throughput_policy` — the bulk/downshift route, gated (see §5).
- `failover_policy`, `escalation_policy` — versioned policy IDs (see §5–§6), not per-row prose.

`*_profile` values resolve through the **profile registry** to an exact model + effort + flags — e.g. `codex.sol.high`, `codex.sol.ultra`, `claude.fable.xhigh`, `claude.fable.max`, `gemini.flash.default`, `gemini.flash.high`, `kimi.k2.7.bulk`. Claude also keeps `claude.opus.default` / `claude.sonnet.default` as **native in-lane fallback only** (`--fallback-model`), not standing lanes.

## 3. Lanes, models, and capability fit

| lane | frontier model (primary) | escalate | best-fit capability |
|------|--------------------------|----------|---------------------|
| codex | `gpt-5.6-sol` (high) | `gpt-5.6-sol` Ultra/max | implementation · tests · PoC · experimental probing · code review mechanics · graphics/runtime. Offensive-security specialists lead with `gpt-daybreak-blue-latest` (`model_specialty: cyber`) and fall back to sol. `gpt-6-astra` is available and unbound: independent measurement puts it at parity with sol on general intelligence and +2 on coding agents at 2.5x the rate, and Codex runs both at the same 272k context |
| claude | `claude-fable-5` (xhigh) | `claude-fable-5` max | judgment · planning · safety/security reasoning · security defense · research/synthesis/long-context · developmental content · game/level/audio design |
| gemini | `gemini-3.8-flash-medium` | `gemini-3.8-flash-high` (high) | content/text · design · media/multimodal · large-context analysis · **search grounding (live · OAuth-backed — Google Search grounding, first-class Rule-8 route)** |
| kimi | `kimi-code/k3` (high, thinking) | `kimi-code/k3-256k` | allowlisted primaries (summarization and blank-advisor parity); otherwise throughput-only |
| grok | `grok-4.6` (default) | `grok-4.6` (same model; no higher grok tier is bound) | `smokey` advisor; escalate route for `research` and `bounty-researcher`. Native X/Twitter search, subscription-backed. `read_file` ceiling ~25k tokens — use shell or paged ingest for large documents |

**Live-launcher model binding.** For every lane, the board attests the resolved
`shared/registries/profiles.tsv` row and passes that row's `model_id` as the native CLI's exact `--model`
argument. There is no lane-specific alternate model pin: selected profile, attested model, and launched model
remain aligned for Codex, Claude, Gemini, and Kimi.

**Kimi is deny-default as a primary, with a narrow allowlisted primary set.** `shared/lane-policy.tsv` carries
`primary_default kimi deny` plus **two** operator-ratified `primary_exception` rows:

- `summarizer` (`kimi.k3.high`) — low-risk summarization of supplied documents only; Claude review remains required before consequential use.
- `kestrel` (`kimi.k3.max`) — advisory-only blank-model parity across all five families (`sol`/codex, `fable`/claude, `vega`/gemini, `kestrel`/kimi, `smokey`/grok). MCP work is lead-brokered on Kimi, and Codex is the cross-family reviewer.

For those roles Kimi is a real primary, not a downshift. Outside the allowlist it remains a **gated throughput
lane** and the data-extraction bulk backup: `kimi.k2.7.bulk` → `kimi-code/kimi-for-coding-highspeed`, marked
`usage: throughput-only` in the profile registry and admissible only under the §5 downshift conjunction gate.
Kimi has no native dollar/effort ceiling, so every metered Kimi-mediated child call — on a primary row as much
as a throughput one — requires an external numeric budget ceiling; never route unbounded metered work to Kimi.

**Gemini owns grounded bounty research.** `bounty-researcher` performs cited prior-audit, historical-exploit, incident, and taxonomy recon. Its outputs feed attack lanes but remain leads until heavy-hitter validation.

**Deep six-round research is a typed large-context handoff, not generic search grounding.** Gemini-primary `research` and `bounty-researcher` keep grounded live search local, while substantive six-round investigations route to Gemini-primary `large-context-analyst`. When that role runs on its Claude backup, it may invoke `/ultra-research` only after a current slash-command discovery probe passes; a present-but-undiscoverable legacy plugin is `needs_tool`, never live availability.

**Claude and Codex are the heavy hitters and finding authorities.** Claude is judgment/security-reasoning primary; Codex is implementation, tracing, PoC, and test primary. They back up and review one another under anti-affinity. Agreement from any models is corroboration, not formal review.

The machine-enforced lane defaults, narrow primary exceptions, adapter templates, heightened-role set, and routing vocabulary live in `shared/lane-policy.tsv`. Markdown defines the policy; validators read that data and enforce it.

## 4. Tool-gated media axis

`tool_gated` is an **orthogonal axis, not a fifth capability class.** Media-production specialists (image/video/audio/voice/interactive-audio and similar) are gated by which lane's CLI is configured with the chrono-media-studio plugin (higgsfield/elevenlabs), so the model is secondary and routing pins to that plugin-host lane. The gate is the lane CLI's own MCP configuration, not a tmux pane: a board-spawned specialist gets a role-scoped MCP surface that `scripts/python/lane_capability_enforcement.py` narrows from the lane's configured servers down to the set its adapter declares, so a plugin the host lane does not carry is simply absent from the spawn. Where the required credential/provider is present on multiple lanes, prefer capability routing and validate tool compatibility; pin only when a required credential/provider is single-lane.

When a backup lane cannot invoke the required tools, it runs **specification-only (TBASF)**: it produces a blueprint (storyboard / SSML / EDL / event-map / code-spec), flags a clean `capability_gap` / `needs_tool`, and yields to Chrono to re-run the render on the real host. A TBASF blueprint terminates as `capability_gap`/`needs_tool`, **never `success`**.

## 5. Safety model

- **`safety_level`** (`low | medium | high`) is a **quality floor, not a change-level review detector.** `high` forces the strongest profile + `throughput.never`; packet review is derived separately from `review_triggers`. Complexity escalation is separate and signal-based.
- **`heightened_risk`** (boolean) marks defense-in-depth roles. The complete machine-readable role set lives in `shared/lane-policy.tsv`; it includes the security, exploit, incident, privacy, provenance, reconnaissance, supply-chain, and experimental-attacker roles that require the high-safety floor.
- **GLOBAL safety-refusal invariant.** A genuine safety refusal on **any** lane surfaces to the operator; the same request is **never cross-family re-dispatched in either direction** (Fable-refuses → do not shop to Sol; Sol-refuses → do not shop to Fable/Gemini/Kimi). An operational block (overload/down/timeout) may inform a later, manually authored operator/Chrono board packet to the backup lane; no automatic redispatch exists. Refusals are classified by (1) structured provider/wrapper policy event, (2) typed terminal status, then (3) content heuristic **only to downgrade certainty** to `possible_refusal` + surface. A schema-valid 200-style response is terminal; short output is never treated as an operational failure.
- **`operator_gate`** — closed policy enum whose machine vocabulary lives in `shared/lane-policy.tsv`; Hard Rule 6 in `CLAUDE.md` states the corresponding policy set, and `scripts/python/tests/test_held_action_gate.py` requires both to equal the admission-time controller set. `production_mutation` (mutating a live production system that is not itself a public release) is **operator-ratified (2026-07-13)**. `requires_approval` in a brief is **harness tool names only** (`Write`, `Bash`, `WebFetch`, …) — domain gates live in `operator_gate`, never in `requires_approval`. Ordinary worker admission keeps all controller-held category tokens out of `action_scope`; this is not a per-tool-call approval mechanism. See `shared/protocol.md` § Held-category authority and logical scopes.
- **Downshift conjunction gate.** `throughput.downshift_gated.v1` permits the kimi bulk tier ONLY when `safety_level == low` AND no security/privacy/financial content AND a per-task Chrono bulk flag. Never a per-specialist default; `throughput.never.v1` is mandatory when `safety_level != low`, `heightened_risk`, or any `dual_use|privacy|financial` tag applies.

Policy IDs (versioned): `failover.conservative.v1` · `escalation.signal.v1` · `escalation.safety_floor.v1` (mandatory for high/heightened) · `throughput.never.v1` · `throughput.downshift_gated.v1`.

Deterministic assignment rule:
```
if safety_level==high OR heightened_risk:  escalation.safety_floor.v1 ; throughput.never.v1
elif safety_level==medium:                 escalation.signal.v1        ; throughput.never.v1
else (low):                                escalation.signal.v1        ; throughput.downshift_gated.v1 (only if no security/privacy/financial tag)
failover_policy = failover.conservative.v1   (all rows)
```

## 6. Failover — signal and surface; redispatch is manual

`failover.conservative.v1` names the backup choice and conservative signal policy. The dormant automatic-failover subsystem is retired; there is no enable flag, sentinel, watcher, or alternate dispatch route.

- HARD signals (`dispatch_ack` failure, confirmed process exit, or a typed provider error) are evidence to surface, not a dispatch trigger. Ambiguous / slow / silent / missed-heartbeat / deadline observations also surface and never select or launch a backup.
- The ordinary board descriptor, receipt, and registry fences retain process and publication evidence; no parallel attempt ledger exists.
- After the native Claude fallback chain is observed terminal, the operator may direct Chrono to author a new ordinary board packet using the mapped backup. That packet passes the same dispatch, scope, gate, and review checks as any other task.
- **Opus** serves two distinct roles, and conflating them is what made this line wrong. `claude.opus.default` (default effort, `native-fallback` flag) is the in-family overload/safety fallback and never a standing lane. `claude.opus5.high` / `.max` / `.xhigh` are `usage: primary` in the registry and are the standing primary route for 13 of 71 specialists, including `architect`, `incident-responder` and `impact-validator`. Carve-out/heightened work exhausted on the in-family chain **surfaces** rather than laundering cross-family.

## 7. Dispatch contract

Every non-trivial task packet names:

- `to_model`: `gpt-codex | claude | gemini | kimi | grok`
- `specialist`: canonical specialist name
- `source_namespace`: `coding | security | content | sysmgmt | research | shared`
- `compatibility_namespace`: mailbox that stores the packet
- `write_scope`: exact writable paths, or `[]`
- `review_model`: read-only reviewer lane, or `none`
- `mandatory_review`: `true | false`
- `review_triggers`: explicit subset of `blast_radius | adversarial_claim | deciding_measurement | architecture` (the gate that defines these is `shared/protocol.md` § Mandatory Review Behavior — its one home)
- `parallel_safe`: `true | false`
- `direct_lane_work_allowed`: default `false`
- `operator_approved`: `true | false` (must be `true` for any `operator_gate` work)

### Dispatch is blocked when

- specialist is unknown or missing from the runtime map
- `to_model` or `review_model` is invalid
- `to_model` differs from the map without `model_override_reason`
- `mandatory_review` disagrees with the packet's validated `review_triggers`
- `mandatory_review: true` has `review_model: none`
- normalized `review_model` equals `to_model` for mandatory review, or otherwise violates distinct-family `anti_affinity`
- a deletion manifest is present without `operator_approved: true`; for other held categories, `operator_approved` records policy consent but does not grant ordinary worker action-time authority
- write scopes overlap in-flight work

Explicit operator approval is required by policy for every `operator_gate` action enumerated by Hard Rule 6. Ordinary worker admission denies declared held-category authority; deletion alone also has the file-exact integration gate described in `shared/protocol.md`.

## 8. Pointers

- Per-specialist rows: `shared/specialist-runtime-map.tsv` (machine source of truth).
- Mode workflows: `shared/modes/*.md`.

## 9. Dispatch shape

- **Single:** one specialist, one lane, one task and artifact.

Every board dispatch is a single packet with its own registry record, artifact, response, and verification
contract. Cross-lane comparison is controller-authored as multiple ordinary single packets. When those packets
must prove they answered the same frozen question, the controller may stamp the same general
`swarm_spec_sha256` provenance pin on each; the pin creates no parent record, child transport, or synthetic diff.

## 10. Selection discipline (which specialist, not just which lane)

After choosing the specialist, choose its execution lane by the ranked-availability rule owned by
`chrono/CLAUDE.md` § Dispatch.

The dispatcher enforces the map; the recurring failure is *selecting* the wrong specialist. These rules are canonical (the full task-shape table lives in `shared/specialists/triage.md`):

1. **Pick the most specific specialist for the task shape** — never a generalist by default. A generalist absorbing specific work starves the specific role and loads a weaker-fit prompt.
2. **Never route review / audit / verify work to an implementer.** Review belongs to `code-reviewer`, `skeptic`, `impact-validator`, `vibecoding-check`, or `content-verifier` (or the packet's `review_model`). An implementer reviewing lacks the reviewer's adversarial + `anti_affinity: author_family` discipline.
3. **`systems-engineer` is not the Codex-lane default.** Per its own brief it fires for genuine low-level / cross-arch / SIMD / runtime work only (~5% of coding work). Default general implementation to `backend-engineer`, infra/tool-wiring to `devops-engineer`, persistence to `database-engineer`, hot-paths to `performance-optimizer`, docs to `technical-writer`, review to `code-reviewer`/`skeptic`.
4. **Deliberately fan across all four models.** Gemini owns grounded research (`bounty-researcher`, Google Search grounding), `large-context-analyst`, content/text, and tool-gated media; Kimi owns the allowlisted `summarizer` and `kestrel` primaries plus bulk throughput under the downshift gate; Codex owns `experimental-attacker` breadth (leads only), and Claude and Codex remain the heavy hitters that cross-review one another. Concentrating on two lanes wastes the roster and the cross-family independence that review depends on.
