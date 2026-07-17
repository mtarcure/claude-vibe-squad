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

`panel` and `loop-operator` are **execution mechanisms**, not capabilities — either can be invoked inside
any protocol step, but neither is a capability of its own.

Routing stays **per-specialist on capability** (`shared/routing.md §1/§7`). A capability selects the
workflow/gates only; it **never** selects a model lead. `source_namespace`/folder never choose a model.

---

## The S0–S7 spine

Every protocol names these typed steps. **Step count varies** — a rich capability expands a step into
several (bounty's Produce becomes recon → analysis → PoC → variant-hunt); a simple one collapses S1–S2
into a one-line brief. What is standard is the **typed step contract**, not the number of rows.

| Step | Name | What it does | Typical owners |
|---|---|---|---|
| **S0** | Intake / Admit | Define goal, scope, and safety class; **precheck `capability_state`** (verify each step's tools resolve to `verified: yes` on the executing lane); recall prior work. | Chrono direct, or `triage` |
| **S1** | Frame | Establish the target/contract for the work (requirements · OSINT + scope · brief). | `product-manager` · `scout` · `editor` (mode-specific) |
| **S2** | Design / Plan | Design the solution + the dispatch plan; enumerate the gates the work will hit. | `architect` · `threat-modeler` · strategist + `planner` |
| **S3** | Produce | **The distinctive core** — build · analyze→PoC · generate · curate. This step is what makes one capability different from another. | the capability's domain implementation specialists |
| **S4** | Verify | Exercise + validate the produced artifact (tests, domain checks, evidence). | `test-engineer` · domain validators |
| **S5** | Review / Gate | Independent review + operator gate hard-holds before anything irreversible. | reviewers + operator |
| **S6** | Ship / Deliver | Produce the terminal artifact (package · submit · publish · install · deploy). | `technical-writer` · `devops-engineer` (mode-specific) |
| **S7** | Capture | Record durable learnings/evidence to memory. | `memory-curator` + `chrono-vault` |

A per-capability step row carries: `step_id` (`<capability>/S<n>-<name>`), `specialists`,
`tools_by_lane`, `skills`, and `gate`.

---

## Overlays (attach at named steps — NOT steps or capabilities)

Overlays are the mandatory cross-cutting controls the old design tried to model as separate "packs." They
attach at a named step of any protocol whenever their trigger condition holds:

| Overlay | Attaches at | Trigger | Owners |
|---|---|---|---|
| **Review** | S5 | `safety_level: high` or `heightened_risk` (mandatory); **cross-family** (author-family excluded; `anti_affinity: author_family` for code review). Machine-enforced settle via `registry_reconciler`. | `code-reviewer`, `skeptic` |
| **Truth / Rights** | S4→S5 | content / any publish | `content-verifier` (Rule-8 truth) + `asset-provenance-and-rights-auditor` (Rule-6 rights) — each emits a machine-readable gate record; non-PASS/stale-hash blocks |
| **Impact (G1–G4)** | S4→S5 | bounty submission | `impact-validator` (G1–G4) + cross-family PoC-reproduction gate; final Submit = per-report operator "go" |
| **Accessibility** | S4 | UI / media deliverable | `accessibility-engineer` (conformance) |
| **Privacy** | any step | PII / personal data present | `privacy-steward` |
| **Memory** | S0 (recall) + S7 (record) | always on | `chrono-vault` |

---

## `capability_state` (per capability; derived, not hand-set)

Each capability declares a state that the Phase-2 validator will **derive** from a per-lane tool-verify
pass against `shared/api-catalog.md` (a tool citation is valid only at `verified: yes` for the executing
lane):

- **`live`** — every core-step tool is verified on the executing lane; the capability runs end-to-end.
- **`lane-gated`** — live only on specific lane(s) (e.g. ElevenLabs child tools = Claude-only; context7 /
  firecrawl / GitHub plugin = Claude-only); the protocol pins those steps to the capable lane.
- **`degraded-blueprint`** — a core tool is `verified: no` / absent, so the step produces a spec/blueprint
  (TBASF) and terminates `capability_gap` rather than a false success.
- **`needs_tool`** — a required connector is unverified/absent (e.g. `chrome-devtools`/`playwright`/
  `figma`/`firebase` have no verified catalog row today; no analytics connector for measured SEO impact).

The validator auto-downgrades the state when a tool fails to resolve — the field is computed, never
asserted by hand. No phantom roster IDs: every `specialists` entry must exist in
`shared/specialist-runtime-map.tsv`.

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
(`reverse-engineer`) are **present in the runtime map but absent from the `routing.md §5` closed enum**.
Capabilities that touch them must be marked **"manual authorization hold; enum + validator reconciliation
pending"** — never "machine-enforced," never "the gate doesn't exist." (Reconciliation is a Phase-0/§4
honesty task.)

---

## How a capability file uses this

1. Copy the S0–S7 spine; expand/collapse steps for the capability's real shape.
2. Fill each step's `specialists` (canonical names only), `tools_by_lane` (+ `cost_tier`), `skills`
   (distinguish invokable `SKILL.md` from authored `shared/skills/*.md` pattern-docs), and `gate`.
3. Attach the overlays whose triggers apply.
4. Declare `capability_state` (the validator will confirm/derive it).
5. Frontmatter: `id`, `mode`, `capability_state`, `gates`, `overlays`.

Per-capability files are authored in Phase 1; this skeleton is the contract they conform to.
