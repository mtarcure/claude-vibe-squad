---
name: bounty
version: 2.0
primary_mode_namespace: security
status: active
phases: 9
---

# Mode: Bounty

For authorized bug bounty and vulnerability research. Chrono owns target selection, safety gates, dispatch,
review, and operator-facing decisions. Bounty is one of the two work modes; its offensive domains are the
four `bounty/*` Capability cards, and its working method is the single authoritative offensive skill,
**`systematic-attacking`**.

## The one offensive skill + two iron laws

All offensive work runs through **`systematic-attacking`** — the registered offensive skill at
`shared/skills/systematic-attacking/SKILL.md` (skill-tool-registry row: `skill · authored`; read-on-start).
It is one target-agnostic skill that finds highest-value (High/Critical) bugs across every domain, chains
primitives to catastrophic impact, and stops submitting duplicates. Experimental/novel work is a **phase
inside** it, never a looser sibling skill (a second file becomes the bypass path). The four `bounty/*` cards
are its domain branches and cite it at their S2 (attack-surface) and S4 (chaining/impact) steps. Two co-equal
iron laws:

```
IRON LAW 1 (safety): NO OFFENSIVE ACTION OUTSIDE AUTHORIZED, VERIFIED SCOPE.
IRON LAW 2 (rigor):  NO FINDING WITHOUT A REPRODUCED, NEGATIVE-CONTROLLED,
                     INTRINSIC-IMPACT PROOF.
```

**One vocabulary — never redefined downstream:**
- **primitive** — a bounded attacker capability or environmental fact. Carries *capability, not severity*.
- **lead** — "there may be exploitable impact here." No CVSS, never submitted.
- **candidate** — a lead/primitive-path whose PoC + negative control pass in a sandbox.
- **finding** — a candidate reproduced end-to-end, negative-controlled, clearing the impact bar, passing
  cross-family reproduction. **Only findings carry CVSS and may be submitted.**

**Finding = intrinsic impact only** (operator-locked): proven, reproducible loss of user/platform funds,
RCE / attacker-controlled execution, direct damage to users or services, cross-tenant data compromise at
material scale, privileged/control-plane takeover, or a realized malicious capability. **Reachability,
disclosure, "could-lead-to" are NOT findings.**

## Capabilities (the four offensive domain branches)

`capability_state` is **derived** and machine-checked by `bin/validate-capabilities.sh` (not hand-set), so
this index stays honest by construction. Cards live in `shared/capabilities/bounty/`. All are
heightened-risk and gated on operator target-engage + a per-report final-Submit "go".
`systematic-attacking` **routes into** these cards for its domain checklists — it never copies them.

| Capability | State | When |
|---|---|---|
| [Web API / HTTP-surface vulnerability research](../capabilities/bounty/web-api-saas.md) | `live` | authorized research against an HTTP API / SAST-accessible web surface |
| [Smart-contract / web3 vulnerability research](../capabilities/bounty/smart-contract-web3.md) | `live` | authorized research against EVM / Solana / Cosmos contracts |
| [LLM / AI-system vulnerability research](../capabilities/bounty/ai-llm-system.md) | `live` | authorized LLM/AI research — attack design + offline analysis |
| [Binary / malware / firmware vulnerability research](../capabilities/bounty/binary-firmware.md) | `needs_tool` | binary/malware/firmware — RE/emulation toolchain not cataloged; isolation required |

## Phase lifecycle (recovers Research + Skeptic; each phase names its owner + hard gate)

This lifecycle **is** the offensive spine of `systematic-attacking` (`shared/skills/systematic-attacking/SKILL.md`,
Phases 0–8); the skill is assigned on the primary lane of every offensive owner in the capsource
(`exploit-developer`, `experimental-attacker`, `security-analyst`, `threat-modeler`, `impact-validator`,
`skeptic`). Each phase below maps to the same-numbered skill phase.

| Phase | Name | Owner specialist(s) | Hard gate |
|---|---|---|---|
| **0** | Authorization & Scope Lock | Chrono + `threat-modeler` | **Law 1** — in-scope set + forbidden set written; ambiguous scope STOPS; no action beyond authorized until operator target-engage |
| **1** | Research & Prior-Art (**dedup**) | `research`, `bounty-researcher`, `large-context-analyst` | target's prior audits, disclosed bugs, CVE/known-issue DBs, program history, **and our own vault** searched *before* effort; refreshed before submission |
| **2** | Synthesis → Attack-Surface & Impact Model | `threat-modeler`, `security-analyst` | pre-register the impact bar — write the HIGH/CRIT terminus thresholds *before* generating hypotheses |
| **3** | Hypothesis Generation (2 lanes) | `security-analyst` (known-class) · `experimental-attacker` (discovery) | emits **leads/primitives only**, never findings; discovery earns no laxer verification |
| **4** | Chaining (**chain-strike v2**) | `exploit-developer` (Chrono aggregates the primitive pool) | impact-first path to a HIGH/CRIT terminus; below-bar/out-of-scope/prior-art paths pruned |
| **5** | Proof & Negative Control | `exploit-developer`, `test-engineer` | **Law 2 pt.1** — runnable PoC in sandbox/read-only fork against the *real* oracle; link- and chain-level causal negative controls; operator gate before any live/mutating action |
| **6** | Impact Bar & Cross-Family Reproduction | `impact-validator` + a different-family lane | **Law 2 pt.2** — G1–G4; a *different model family* reproduces the written procedure; CVSS v4 scored **once**, from the realized terminus, only here |
| **7** | Skeptic (adversarial verification) | `skeptic` | verifies *soundness*, not just results; kills harness/mock/flaky/oracle errors; refutes prior art |
| **8** | Package & Operator-Gate | Chrono, `technical-writer`, `vibecoding-check` | de-AI/researcher-voice pass on frozen evidence; the final Submit stays a per-report operator "go" — the skill drives up to it, never through it |

**Domain branching (Phase 3):** the hypothesis lane selects a domain checklist set — web/SaaS ·
smart-contract/DeFi · infra/cloud · LLM/AI · mobile — by routing into the four `bounty/*` cards plus the
existing audit-checklist skills. The verification back-end (Phases 4–8) is identical across domains.

**Chaining = chain-strike v2** (the Phase-4 reference inside `systematic-attacking`): inventory typed
*primitives* (not "findings"), including environmental free-edges (flash loans, permissionless deploy,
public mempool, open self-signup, public buckets, unauth deeplinks); build a **typed dependency graph**
(each edge names a falsifiable proof obligation — `REQUIRES`/`SUPPLIES`/`CROSSES_BOUNDARY`/`CHANGES_STATE`/
`AMPLIFIES`/`INVALIDATES_GUARD`/`REACHES_TERMINUS`); search **impact-first bidirectional** (backward from an
authorized HIGH/CRIT terminus + forward from observed primitives → shortest reliable intersection); prove
**link- and chain-level causal negative controls**; run **chain-level dedup** (a known/reported/patched
*composite* is a duplicate even when the individual bugs look novel); stop once the shortest path realizes a
program-recognized HIGH/CRIT unless an added link proves *materially greater realized blast radius*. No CVSS
until the full chain reproduces; CVSS is re-derived from the realized terminus, **never summed**;
`[new discovery] N/A` links are forbidden.

## Bounty tooling (fail-closed by construction)

- **Authenticated platforms → CDP browser-harness.** Authed recon/scope on bounty platforms drives the
  operator's already-authenticated Chrome over the raw CDP port (attach to the existing session; read open
  tabs only — never spawn fresh tabs/Chromes, never route through chrome-devtools-mcp/playwright-mcp which
  launch their own browsers).
- **SAST → docker-isolated.** Untrusted-target static analysis runs in isolated containers; the local CLI
  toolchain (below) is run against clones/forks, never against a live target's control plane.
- **Scope → fail-closed `scope_gate` + `exact_target_allowlist`.** Ambiguous scope STOPS (Phase 0); a hop
  onto an out-of-scope asset is scope-laundering (Law 1 + legal) and is pruned, never bridged.

### Local CLI toolchain (use by default — do not rediscover)

Specialists have shell access and MUST use it, not just grep:
- **Go:** `gosec -severity=medium`, `staticcheck`, `golangci-lint`, `semgrep --config=p/gosec --config=p/golang`, `osv-scanner --lockfile go.mod`, `go test -race`, `go test -fuzz`.
- **EVM:** `slither`, `aderyn`, **`myth`** (Mythril — NOT `mythril`), `semgrep`, Foundry (`forge`/`cast`/`anvil`/`chisel` fork-and-replay + auth-fuzz), `echidna`, `medusa`, `halmos`, **ItyFuzz** (pinned Linux container `vibe-ityfuzz:nightly`; native Apple-Silicon build fails on Z3), **solodit-mcp** (Cyfrin Solodit precedent DB — guarded, live after operator relaunch). Skips: Manticore (archived); HexStrike (dedicated-VM-only). **Mock harnesses are BLIND to valuation — fork the REAL oracle/registry.** Halmos/Z3 can't prove staking/recursive-valuation math (fuzz those).
- **Rust/Solana:** `cargo-audit`, `clippy`, `cargo-geiger`, `cargo-fuzz`, `anchor`, `solana`.
- **General:** `trivy`, `grype`, `gitleaks`/`trufflehog` (secret scan is operator-gated for a target org).

**Apply the domain audit-checklist skills on task start** (they encode the classes that convert):
- Blockchain L1 / bridge / appchain → domain branch `blockchain-l1`; skills `cross-chain-bridge-audit`, `cosmos-sdk-audit-checklist`, `known-advisory-backport-check`.
- Solidity/Rust contracts → domain branch `smart-contract`; skills `solana-anchor-audit-checklist` (Solana/Anchor), `known-advisory-backport-check` (forked deps).
- Chaining/terminus discipline is provided by `systematic-attacking`'s chain-strike v2 reference (the old `chain-impact-rescore` skill is folded into it).

**Dynamic testing is mandatory for logic/nonce/reorg/concurrency bugs** — extract the logic into a hermetic
harness (mock RPC + latest/safe/finalized heads), run `-race`, include a negative control. Static
isolation-review misses shared-predicate and concurrency bugs (it wrongly killed a real finalized-nonce bug
for 5 waves until dynamic testing caught it).

## Phase 8 — Capture Learnings

After final review, Chrono records through chrono-vault `record`: every verified finding whether submitted
or not, each KILL and why that attack class did not pan out, and reusable process learnings. All
bounty-derived notes use `sensitivity: restricted` and retain source-task and evidence provenance. Outbox
auto-capture ingests response verdicts as `candidate` notes; this phase deduplicates and curates, promoting
reviewed candidates to `verified` rather than creating parallel memory.

## Dispatch Notes

- Bounty work does not imply one model lead. Chrono dispatches each specialist per
  `shared/specialist-runtime-map.tsv` on capability; see `shared/routing.md` for the model.
- PoC and harness mechanics route to codex (`gpt-5.6-sol`) with claude (`claude-fable-5`) review;
  judgment/security-reasoning (`security-analyst`, `threat-modeler`, `impact-validator`, `scout`) is
  claude-primary with codex backup.
- Grounded prior-audit / historical-exploit / weakness-taxonomy research routes to **Gemini**
  (`bounty-researcher`, Google Search grounding). Kimi is not a bounty-research primary (its only primary is
  the allowlisted `experimental-attacker`); it takes research work only as throughput/backup.
- Report wording routes to the assigned writer's lane (`technical-writer` = claude/Fable).
- **`panel` / `swarm` / `triage` are dispatch mechanics, not modes** — invoke any under this mode when the
  work shape calls for it (mechanics described in `shared/routing.md`).
- **Safety-refusal invariant:** a genuine safety refusal on any lane surfaces to the operator and is NEVER
  cross-family re-dispatched in either direction. The offensive specialists here (`security-analyst`,
  `exploit-developer`, `scout`, `impact-validator`, `smart-contract-engineer`, `threat-modeler`,
  `experimental-attacker`, `reverse-engineer`) run under heightened-risk defaults — a refused request is
  never shopped to a more permissive lane.

## Gates

- Operator approval before engaging a target, touching authenticated scope, contacting a program, or writing
  private bounty details to durable public-facing files.
- **Submission gate (operator-ratified 2026-07-14):** Chrono/specialists MAY drive the full submission
  workflow — navigate the authed platform session, fill the report form, attach the PoC, stage everything —
  up to but NOT including the final Submit click. The **final Submit click is a hard per-report gate
  requiring explicit operator "go"** (irreversible; costs a submission fee + reputation). Staging the form
  without submitting needs no separate approval.
- **Pre-submit G1–G4 gate (`impact-validator` owns it):** no finding is submitted unless it clears G1
  impact-realized · G2 third-party-reproduced · G3 dedup'd · G4 in-scope defended-boundary, plus its
  per-class add-on — any FAIL is no-submit. Full gate: `departments/security/specialists/impact-validator.md`
  → "Pre-Submit Gate (G1–G4)".
- **PoC reproduction gate (before ANY submission):** the PoC author is not the validator. A
  **different-model-family agent** must independently **reproduce the runnable PoC from scratch** (clone/run
  fresh, confirm it passes AND that the harness faithfully maps to the real in-scope code file:line), and
  **multiple models must concur** (the cross-family reproducer + `skeptic` + `impact-validator`). Chrono
  coordinates the fan-out and reads the verdicts — Chrono does NOT run the PoC itself. A PoC only counts as
  reproduced when ≥2 model families have independently run it and agreed it proves the claim.
- Mandatory multi-model review for exploitability, impact, privacy, auth, and final report claims.
- No destructive testing, rate-limit abuse, persistence, credential use, or out-of-scope probing.
- Run `vibecoding-check` before the final operator summary.

## Swarm / sub-swarm mechanics (proven — `--subswarm-directive`)

Big-swarm it: a lead spawns native structured subagents *within one dispatch* via
`bin/send-task.sh --subswarm-directive <core.json> --subswarm-assignment '<lane>:subNN=<objective>' …`
(per-dispatch, no relaunch). **The lead alone seals one `swarm-member-bundle/v1` and decomposes it
exhaustively into `subswarm-review-subjects/v1`** — one `subswarm-review-item/v1` per member, every declared
member present, no sampling. **Chrono / the reconciler then coordinates the per-subject cross-family review**
(one `finding-review/v1` verdict per subject) and settlement. Every security/divergent sub-finding is a
mandatory review subject; a bundle that hides or samples one is rejected.

- **Lane status:** subagent-orchestration is **proven-runnable today only on gpt-codex**; supported but not
  yet exercised end-to-end on Claude/Gemini; **Kimi is single-lane / lead-brokered** (its subagents hold no
  MCP — route Kimi's MCP work through the main lane). Do **not** claim a Kimi sub-swarm.
- **Role architecture:** **Kimi = experimental-attacker** (bold, high-volume, everything-is-a-LEAD);
  **Gemini = bounty-researcher** (grounded); **Claude + Codex = heavy hitters + independent
  validation/skeptic**. Same-family subagents are coverage, not independent corroboration — cross-family
  independence lives between leads/lanes. A Kimi- or Gemini-only result is never a validated finding until a
  heavy hitter independently confirms it and the mandatory review settles the frozen bundle.
- **Cross-lane `--swarm`** (independent lane children + deterministic `swarm_diff` alignment, not a vote)
  remains the mechanism for genuine cross-family corroboration on the *same* objective. Namespace is only the
  mailbox; each specialist routes to its best-fit model per `shared/routing.md`.
