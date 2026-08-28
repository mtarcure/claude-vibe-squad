# Capability protocol skeleton (canonical template)

Every capability under a Mode is a **step-by-step protocol** that instantiates this shared skeleton, so
each one reads as the same recognizable working routine. This file is the template + contract; the
per-capability files (`shared/capabilities/<mode>/<capability>.md`) fill it in. It is a spec, not an
executable — the `capability_state` deriving validator (`bin/validate-capabilities.sh`) is a later
Phase-2 step.

Derived by abstracting the two most-developed existing flows: `bounty` (12-phase, `shared/modes/bounty.md`)
and `project` (8-phase, `shared/modes/project.md`).

---

## The model (locked)

**`Mode → Capability → Protocol`.** A **Mode** is operator intent + lifecycle + terminal artifact + safety
gates. A **Capability** is one distinctive routine inside a mode, expressed as a protocol. `variant`,
`pack`, and `profile` are **retired** — web-app, game-production, image, authorized-red-team, and
self-extension are all just Capabilities-with-protocols under their Mode.

`loop-operator` is an **execution mechanism**, not a capability — it can be invoked inside
any protocol step, but is not a capability of its own.

Routing stays **per-specialist on capability** (`shared/routing.md §1/§7`). A capability selects the
workflow/gates only; it **never** selects a model lead. `source_namespace`/folder never choose a model.

---

## The S0–S7 spine

Every protocol names these typed steps. **Step count varies** — a rich capability expands a step into
several (bounty's Produce becomes recon → analysis → PoC → variant-hunt); a simple one collapses S1–S2
into a one-line brief. What is standard is the **typed step contract**, not the number of rows.

| Step | Name | What it does | Typical owners |
|---|---|---|---|
| **S0** | Intake / Admit | Admit the task, validate capability state/scope, and pin the dispatcher-owned verification contract. | Chrono direct, or `triage` |
| **S1** | Understand / Recall | Establish the target and requirements, then perform the required memory recall and bind its receipt/usage coverage. | `product-manager` · `scout` · `editor` (mode-specific) |
| **S2** | Design / Plan | Design the solution and dispatch plan, enumerate gates, hash the plan, and obtain the mandatory different-family plan review. | `architect` · `threat-modeler` · strategist + `planner` |
| **S3** | Produce | **The distinctive core** — build · analyze→PoC · generate · curate. This step is what makes one capability different from another. | the capability's domain implementation specialists |
| **S4** | Verify | Exercise and validate the produced artifact with admission-derived verification kinds and hash-bound evidence. | `test-engineer` · domain validators |
| **S5** | Review / Hold | Obtain the mandatory different-family deliverable review, evaluate gates, and hold anything stale or irreversible. | reviewers + operator |
| **S6** | Local Deliver | Produce a local package/report only in v1; external delivery and Bounty submission remain hard stops. | `technical-writer` · `devops-engineer` (mode-specific) |
| **S7** | Record / Clean | Record durable learning with final-bundle-bound receipts and clean declared ephemeral resources. | `memory-curator` + `chrono-vault` |

A per-capability step row carries: `step_id` (`<capability>/S<n>-<name>`), `specialists`,
`tools_by_lane`, `skills`, and `gate`.

S5 rejection routes through the I-loop to S2 for plan changes or S3 for artifact changes. Any changed plan or artifact hash invalidates prior verification, reviews, gates, delivery, and S7 close evidence; stale hashes never count toward completion. Rich capabilities may still expand any typed step into multiple domain-specific rows—the typed proof contract does not remove that richer expansion rule.

---

## Overlays (attach at named steps — NOT steps or capabilities)

Overlays are the mandatory cross-cutting controls the old design tried to model as separate "packs." They
attach at a named step of any protocol whenever their trigger condition holds:

| Overlay | Attaches at | Trigger | Owners |
|---|---|---|---|
| **Review** | S5 | Packet `review_triggers` per `shared/protocol.md` § Mandatory Review Behavior (the enforced home for the four change-level triggers and their cardinality); **cross-family** (author-family excluded; `anti_affinity: author_family` for code review). `safety_level` remains an execution-quality floor, never the change-level trigger. Machine-enforced settle via `registry_reconciler`. | `code-reviewer`, `skeptic` |
| **Truth / Rights** | S4→S5 | content / any publish | `content-verifier` (Rule-8 truth) + `asset-provenance-and-rights-auditor` (Rule-6 rights) — each emits a machine-readable gate record; non-PASS/stale-hash blocks |
| **Impact (G1–G4)** | S4→S5 | bounty submission | `impact-validator` (G1–G4) + cross-family PoC-reproduction gate; final Submit = per-report operator "go" |
| **Accessibility** | S4 | UI / media deliverable | `accessibility-engineer` (conformance) |
| **Privacy** | any step | PII / personal data present | `privacy-steward` |
| **Memory** | S0 (recall) + S7 (record) | always on | `chrono-vault` |

---

## `capability_state` (per capability; zero-key default with a derived ceiling)

Each capability declares what a zero-key/default checkout can run. The validator also derives a
configured-host ceiling from the tool registry, but a ceiling is not fresh-install proof: a role that needs
an unconfigured MCP server, private vault binding, provider credential, authenticated subscription session,
or host-only executable is `needs_tool` until that prerequisite is supplied.

- **`live`** — the zero-key checkout admits every required role and runs the core path end-to-end.
- **`lane-gated`** — the zero-key checkout runs only on named lane(s), with no undone private setup on them.
- **`degraded-blueprint`** — the zero-key checkout can actually produce a spec/blueprint (TBASF) and then
  terminates `capability_gap`; merely having a blueprint fallback on a configured host is insufficient.
- **`needs_tool`** — fresh-install admission or a core step requires setup the downloader has not done. The
  reason names the missing MCP/vault/auth/local-binary/provider prerequisite and the configured-host ceiling.

The validator auto-downgrades overclaims when a registry tool fails to resolve; it does not upgrade a
conservative zero-key declaration merely because the maintainer registry is green. No phantom roster IDs:
every `specialists` entry must exist in `shared/specialist-runtime-map.tsv`.

---

## `cost_tier` (per tool within a step)

Every tool in a step carries a cost class so a protocol's metered exposure is visible up front:

- **`subscription`** (flat-rate, **default**) — the 4 CLI lanes (Claude, Codex, Gemini, Kimi). Launch rails
  unset paid API-key env vars so subscription auth is preferred. Use for volume.
- **`metered`** (pay-per-token, **opt-in, guarded**) — the configured direct-API providers (xAI/Grok,
  DeepSeek, OpenAI API, Gemini/Google API, Perplexity, ElevenLabs, Higgsfield). Rules: prefer the
  equivalent subscription-lane tool where one exists; choose a metered provider only where its capability
  is **unique or materially better**; every metered step carries a cost/rate-limit note + a budget guard;
  **hitting a rate/budget limit is a typed `needs_tool`/degraded result, never a silent stall.**

---

## Offensive-gate note (honesty)

`operator_gate` tokens `offensive_execution` (`red-team-operator`) and `malware_detonation`
(`reverse-engineer`) are in the closed vocabulary and controller-held set. Capabilities that touch them must
say that the **declaration hold is enforced at worker admission**: the supervisor denies a worker whose
authenticated `action_scope` declares either category. Admission authenticates declarations; it does not
remove underlying tool capability or provide a per-action gate.

---

## How a capability file uses this

1. Copy the S0–S7 spine; expand/collapse steps for the capability's real shape.
2. Fill each step's `specialists` (canonical names only), `tools_by_lane` (+ `cost_tier`), `skills`
   (distinguish invokable `SKILL.md` from authored `shared/skills/*.md` pattern-docs), and `gate`.
3. Attach the overlays whose triggers apply.
4. Declare `capability_state` (the validator will confirm/derive it).
5. Frontmatter: `id`, `mode`, `capability_state`, `gates`, `overlays`.

Per-capability files are authored in Phase 1; this skeleton is the contract they conform to.
