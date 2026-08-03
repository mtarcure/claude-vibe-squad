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

**This is the only offensive _lifecycle_ skill.** It alone owns scope, severity, lead→finding promotion, and submission authority. `systematic-bug-hunting` is a subordinate, zero-authority bench-craft layer nested inside Phases 2–5: it generates candidates, holds no scope or severity, and refuses to start without a Phase 0 scope lock. Experimental / novel-vector work is a *phase* inside it
(Phase 3b), not a sibling skill — a second file would duplicate this safety lifecycle, and the
looser copy would become the bypass path. `systematic-debugging` guards the *fix*; this skill
guards the *claim* — and adds a scope law because attacking, unlike debugging, can hurt a real
system.

**Violating the letter of this process is violating the spirit of it.** An empty gate is a
skipped gate; a skipped gate is lab noise, not a finding.

## When a packet contradicts this skill

**Say so; do not resolve it silently.** The dispatching packet still wins — that is the design.
But if a packet instruction contradicts this skill, emit a `## PACKET OVERRODE SKILL` section in
your response naming both sides.

This is not hypothetical. H2 below states that a primitive **carries capability, not severity**,
and that an inert primitive is *labelled*, never deleted. For five consecutive audits Chrono's
Phase-3 packets instead demanded an impact-bar verdict per idea. Lanes obeyed the packet, killed
their own primitives, and the Chaining phase starved for want of a pool — silently, because nothing
made the contradiction visible.

No gate is added here. A reporting duty is enough: the failure was invisibility, not permissiveness.

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

## The lifecycle — owned by the MODE, not by this skill

**`shared/modes/bounty.md` owns the phase list.** This skill previously restated Phases 0-8
verbatim, which made three documents claim authority over one process — and a restated process
loses to whichever copy is most recent, which is always the packet. What follows is what this
skill uniquely owns; for phase definitions, gates and owners, read the mode.

**This skill's job is METHOD**: how to discover primitives, how to compose them, and what
evidence survives review. It is target-agnostic. Target-class specifics live in their own
checklists (`cross-chain-bridge-audit`, `cosmos-sdk-audit-checklist`,
`solana-anchor-audit-checklist`, `known-advisory-backport-check`); campaign process lives in the
mode; this lane's task lives in the packet.

## Phase numbering — three schemes exist, and they are NOT the same

Numeric phase references in this skill, in specialist briefs, in `shared/modes/bounty.md`, and in
`scripts/python/verification_contract.py` use **different numbering**. A reference like "Phase 3"
is ambiguous unless you know which scheme it belongs to. Resolve with this table before acting on any
numeric phase label:

| This skill (0–8) | Mode v3 (1–7) | Contract stage | What it actually is |
|---|---|---|---|
| Phase 0 | Phase 1 | `S0` | Scope lock, program truth, facts |
| Phase 1–2 | Phase 1–2 | `S1`–`S2` | Prior-art exclusion, planning, measured index |
| **Phase 3 / 3a / 3b** | **Phase 3** | `S3` | **Hypothesis generation and hunting — 3b is invention** |
| Phase 4 | Phase 4 | `S4` | Chaining / composition |
| Phase 5 | Phase 5 | `S5` | Proof, PoC, negative controls |
| Phase 6–7 | Phase 5 | `S6`–`S7` | Impact bar, cross-family reproduction, skeptic |
| Phase 8 | Phase 6 | — | Package, de-AI, operator submit gate |
| — | Phase 7 | — | Teardown |

**When a packet and a document disagree on a phase number, the packet wins and you report the
conflict.** Do not silently renumber, and do not assume "Phase 3" in a brief means the same stage as
"Phase 3" in the mode.


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

## Anti-patterns (do NOT PROMOTE any chain exhibiting these — banking is unaffected)

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
