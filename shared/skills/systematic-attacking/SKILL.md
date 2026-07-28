---
name: systematic-attacking
description: Use for ALL authorized offensive-security / bug-bounty work — the single method to find, chain, prove, dedup, and package the highest-value (High/Critical) findings across every domain (web/SaaS, smart-contract/DeFi, infra/cloud, LLM/AI, mobile, binary/firmware). Enforces two iron laws before any offensive action or submission: never act outside authorized verified scope, and no finding without a reproduced, negative-controlled, intrinsic-impact proof.
status: authored
---

# Systematic Attacking

## Overview

Offensive work fails in two characteristic ways: it strays **outside authorized scope**
(the act of testing is itself potentially harmful), and it **submits claims that were never
really proven** — reachability dressed as impact, a pile of lows dressed as a high, a known
composite dressed as novel. This skill is the one method that blocks both failures.

**This is the only offensive skill.** Experimental / novel-vector work is a *phase* inside it
(Phase 3b), not a sibling skill — a second file would duplicate this safety lifecycle, and the
looser copy would become the bypass path. `systematic-debugging` guards the *fix*; this skill
guards the *claim* — and adds a scope law because attacking, unlike debugging, can hurt a real
system.

**Violating the letter of this process is violating the spirit of it.** An empty gate is a
skipped gate; a skipped gate is lab noise, not a finding.

## The Two Iron Laws

Two co-equal laws. Neither is negotiable, and neither substitutes for the other.

```
IRON LAW 1 (safety): NO OFFENSIVE ACTION OUTSIDE AUTHORIZED, VERIFIED SCOPE.
IRON LAW 2 (rigor):  NO FINDING WITHOUT A REPRODUCED, NEGATIVE-CONTROLLED,
                     INTRINSIC-IMPACT PROOF.
```

- **Law 1** is enforced at Phase 0 and is cross-cutting: an ambiguous scope STOPS; every hop
  stays inside the in-scope allowlist; a genuine refusal is **terminal** and is never re-shopped
  to a looser lane. Any live / mutating / credential-using action waits for the operator gate.
- **Law 2** is enforced at Phases 5–6: a runnable PoC against the real oracle, causal negative
  controls at link *and* chain level, the G1–G4 impact bar, and a different-family reproduction —
  before anything is called a finding or scored.

## Vocabulary — one definition, never redefined downstream

Every reference doc and specialist uses **these** words. Do not redefine "finding" anywhere.

- **primitive** — a bounded attacker capability or environmental fact (from a lead, a validated
  finding used as an inner link, public/known behavior, or config). Carries **capability, not
  severity.**
- **lead** — "there may be exploitable impact here." No CVSS, **never submitted.**
- **candidate** — a lead or primitive-path whose PoC + negative control pass in a sandbox.
- **finding** — a candidate that is reproduced end-to-end, negative-controlled, clears the impact
  bar, and passes cross-family reproduction. **Only findings carry CVSS and may be submitted.**

**Finding definition (offensive-impact only, per operator):** a proven, reproducible claim of
**intrinsic** impact — loss of user/platform funds · RCE / attacker-controlled execution · direct
damage to users or services · cross-tenant data compromise at material scale · privileged /
control-plane takeover · a realized malicious capability. **Reachability, disclosure,
"could-lead-to" are NOT findings.** They are, at most, leads.

## The lifecycle — Phase 0 (preflight) + Phases 1–8

**Phase 0 is a preflight authorization gate; Phases 1–8 are the working stages** (Phase 3 splits into
3a known-class / 3b experimental) — nine stages total. Each phase names its **owner** and its **hard
gate**. Most owners are specialists; **Phase 8's owner is Chrono** — coordination + the operator
submission gate, *not* a specialist role. You MUST clear a phase's gate before the next phase. All
coordination is Chrono-brokered (see [Primitive pool](#primitive-pool)).

| # | Phase | Owner specialist(s) | Hard gate |
|---|---|---|---|
| **0** | Authorization & Scope Lock | `threat-modeler` (Chrono holds the operator gate) | **Law 1** — in-scope set + forbidden set written; ambiguous scope STOPS; no action beyond authorized until operator target-engage |
| **1** | Research & Prior-Art (**dedup**) | `research` / `large-context-analyst` | Prior audits, disclosed bugs, known-issue/CVE DBs, program history, **and our own vault** searched *before* effort — via the `chrono-dedup` plugin; refreshed pre-submit |
| **2** | Attack-Surface & Impact Model | `threat-modeler` | Pre-register the impact bar: write the HIGH/CRIT terminus thresholds *before* generating hypotheses |
| **3a** | Hypothesis Generation — known-class | `security-analyst` | Emits **leads / primitives only**, never findings |
| **3b** | Hypothesis Generation — experimental discovery | `experimental-attacker` | Emits **leads only**; earns **no** laxer verification than 3a |
| **4** | Chaining (→ `references/chain-strike-v2.md`) | `exploit-developer` (Chrono aggregates the pool) | Impact-first path to a HIGH/CRIT terminus; below-bar / out-of-scope / prior-art paths pruned |
| **5** | Proof & Negative Control | `exploit-developer` | **Law 2 pt.1** — runnable PoC in sandbox / read-only fork against the *real* oracle; link- and chain-level causal negative controls; operator gate before any live/mutating action |
| **6** | Impact Bar & Cross-Family Reproduction | `impact-validator` + a different-family lane | **Law 2 pt.2** — G1–G4; a *different model family* reproduces the written end-to-end procedure; CVSS v4 scored **once**, from the realized terminus, only here |
| **7** | Skeptic (adversarial verification) | `skeptic` | Verifies *soundness*, not just results; kills harness / mock / flaky / oracle errors; refutes prior art |
| **8** | Package & Operator-Gate | `Chrono` | De-AI / researcher-voice pass on frozen evidence; the final Submit stays a per-report operator "go" — the skill drives **up to** it, never through it |

### Phase notes

- **Phase 0 — Authorization & Scope Lock.** Write two explicit sets: the in-scope target
  allowlist and the forbidden set. Ambiguous or unstated scope is not a green light — it STOPS.
  Nothing beyond passive, authorized reasoning happens before the operator's target-engage.
- **Phase 1 — Research & Prior-Art / dedup.** Search *before* spending effort, not after. Run the
  target-scoped prior-art check through the **`chrono-dedup` plugin** (HackerOne, Immunefi, GHSA,
  CVE, OSV, program history, and our own `chrono-vault`). A `duplicate` / `likely-duplicate`
  verdict kills or demotes the lead early. This is refreshed immediately before submission.
- **Phase 2 — Attack-Surface & Impact Model.** Enumerate the surface and **pre-register** the
  HIGH/CRIT termini thresholds. Writing the impact bar *before* hypotheses is what lets Phase 4's
  search prune below-bar paths instead of scoring them after the fact.
- **Phase 3 — Hypothesis Generation (two lanes).** 3a (`security-analyst`) works the known vuln
  classes for the domain; 3b (`experimental-attacker`) generates novel / non-catalogued vectors.
  **Both lanes emit leads/primitives only.** 3b's outputs are *not* held to a lower bar — they
  re-enter the identical Phase 4–8 verification spine. This is the discipline that makes a second
  "experimental" skill unnecessary and unsafe.
- **Phase 4 — Chaining.** The owner runs [`references/chain-strike-v2.md`](references/chain-strike-v2.md)
  over the aggregated primitive pool: typed primitives (incl. environmental free edges) → a typed
  directed dependency graph → impact-first bidirectional search to the **shortest reliable** path.
  No CVSS or severity arithmetic anywhere in this phase.
- **Phase 5 — Proof & Negative Control.** Build a runnable PoC in a sandbox, synthetic replica, or
  read-only fork against the **real** oracle (not a mock). Run the link-level and chain-level
  causal negative controls from chain-strike-v2 §4. **Any** live/mutating/credential-using step
  STOPS for the operator gate.
- **Phase 6 — Impact Bar & Cross-Family Reproduction.** `impact-validator` runs the G1–G4 impact
  bar; a **different model family** independently reproduces the written procedure. CVSS v4 is
  derived **once**, from the realized terminus — never summed across links.
- **Phase 7 — Skeptic.** Adversarial verification of *soundness*: is the oracle real, is the
  harness faithful to prod, is the result stable, is the prior-art refutation honest? Kills
  flaky / mock / model-mismatch results before packaging.
- **Phase 8 — Package & Operator-Gate.** De-AI / researcher-voice pass on the frozen evidence, fit
  to the program's submission form, then hand to the operator. **The skill never clicks Submit.**

## Domain branching (Phase 3) — route, never copy

The skill is **target-agnostic**. In Phase 3 the hypothesis lane selects the domain checklist set
for the target and **routes into** the domain reference — it never copies domain content into this
skill or into chain-strike-v2. The verification back-end (Phases 4–8) is identical across domains.

| Domain | Route into (capability card) | Per-domain checklists / references (reference, never copy) |
|---|---|---|
| **web / SaaS** (+ **infra / cloud**) | `shared/capabilities/bounty/web-api-saas.md` | web + infra/cloud pattern sets in chain-strike-v2 §9–10; the card's fresh/no-auth DAST profile (authed-session + mobile are `needs_tool`) |
| **smart-contract / DeFi** | `shared/capabilities/bounty/smart-contract-web3.md` | `evm-audit-flow`, `solana-anchor-audit-checklist`, `cosmos-sdk-audit-checklist`, `cross-chain-bridge-audit`, `known-advisory-backport-check`; DeFi patterns in chain-strike-v2 §9 |
| **LLM / AI** | `shared/capabilities/bounty/ai-llm-system.md` | LLM/AI patterns in chain-strike-v2 §9; live-endpoint probing is `needs_tool` (offline transcript analysis is the live scope) |
| **mobile** | *(no dedicated card — profile of web-api-saas)* | mobile pattern set in chain-strike-v2 §9; mobile targets are `needs_tool` per the web card |
| **binary / firmware** | `shared/capabilities/bounty/binary-firmware.md` | `binary-re-pipeline`, `sandbox-provision-discipline`; card is `needs_tool` (radare2 static only) |

**Cross-domain pivots** — where the shortest path to critical usually lives — are handled in
chain-strike-v2 §10 (web SSRF→cloud IMDS→ATO; LLM injection→MCP→cloud action; mobile deeplink→web
OAuth→ATO). Inventory primitives from *every* domain the target touches.

## Safety rails → phase gates (nothing floats free)

Every rail is enforced at a named gate; none is advisory prose.

| Rail | Enforced at |
|---|---|
| authorized-scope-only · `scope_gate` · `exact_target_allowlist` | Phase 0 |
| global refusal invariant (no unauthorized-attack help; a refusal is terminal, never re-shopped to a looser lane) | Phase 0 + cross-cutting |
| operator gate before any live / mutating / credential-using action | Phase 0 (target-engage) + Phase 5 |
| `no_self_inflicted` (+ self-inflicted detector) | Phase 0 boundary + Phase 5 |
| link/chain causal negative control + `poc_reproduction` | Phase 5 |
| impact bar G1–G4 + `cross_family_reproduction` + `cvss_v4` | Phase 6 |
| prior-art / dedup (finding **and** composite) | Phase 1, refreshed pre-submit |
| final Submit = per-report operator "go" | Phase 8 (the skill stops here) |

## Bounty verification-contract binding (submission-grade by construction)

Each hard gate emits **exactly one** verification-contract field, so the skill's output *is* a
filled contract. An **empty field means a skipped gate** — the mechanical line between a finding
and lab noise.

- **Phase 0** → `scope_gate`, `exact_target_allowlist`, `no_self_inflicted` (boundary)
- **Phase 5** → `poc_reproduction`, `negative_control`, `no_self_inflicted` (verified)
- **Phase 6** → `cvss_v4`, `cross_family_reproduction`, G1–G4

## Anti-patterns (kill any chain exhibiting these)

Inherited from chain-strike v1: **forced chains** · **theoretical chains** · **duplicate-root-cause**.
Added (each blocks a characteristic false-submit): **severity laundering** (naming lows/mediums ≠ a
high) · **chain padding** (endpoint occurs without the link) · **privilege laundering** (hidden
admin/root/victim capability) · **scope laundering** (out-of-scope hop bridges the path — Law 1 +
legal) · **assumption laundering** (lab config presented as real target state) · **same-effect
double-counting** · **circular dependency** · **unreliable / race-only chain** (probability
ignored) · **model mismatch** (harness omits a prod guard/oracle/identity/OS behavior) · **duplicate
composition** · **downstream-known chain** · **unsafe proof** (validation would exceed scope, harm
bystanders, move real funds, persist, or destroy prod). The full definitions live in
chain-strike-v2 §12.

<a id="primitive-pool"></a>
## The primitive pool — how specialists coordinate

There is **no live peer-to-peer channel** between running specialist CLIs. All coordination is
**Chrono-brokered** (specialist → Chrono → specialist). The Chaining phase's primitive pool is
therefore a **Chrono-owned shared findings ledger**: each specialist writes typed primitives to it
via their outbox, Chrono aggregates, and the chaining owner (`exploit-developer`) runs
chain-strike-v2 over the pool. No new comms machinery is required or assumed.

## Quick checklist

- [ ] Phase 0: in-scope allowlist + forbidden set written; ambiguous scope STOPPED; operator target-engage obtained.
- [ ] Phase 1: prior-art + composite dedup run via `chrono-dedup` *before* effort; refreshed pre-submit.
- [ ] Phase 2: HIGH/CRIT termini pre-registered *before* hypotheses.
- [ ] Phase 3: leads/primitives only from both lanes; 3b held to the same bar as 3a.
- [ ] Phase 4: typed graph + impact-first bidirectional search; shortest reliable path; **no CVSS / no severity arithmetic**.
- [ ] Phase 5: runnable PoC vs the real oracle; five link controls + chain-level control pass; operator gate cleared for any live action.
- [ ] Phase 6: G1–G4 pass; different-family reproduction; CVSS v4 scored **once** from the terminus.
- [ ] Phase 7: skeptic verified soundness (oracle real, harness faithful, result stable, prior-art honest).
- [ ] Phase 8: de-AI'd, form-fit, handed to operator; **final Submit left to the operator**.
- [ ] Domain content **routed into** bounty/* cards + checklists, never copied here.
- [ ] Every hard gate emitted its one contract field; no empty field.
