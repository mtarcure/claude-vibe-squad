---
name: systematic-bug-hunting
description: Use when actually hunting for exploitable bugs at the bench inside an already-authorized engagement — reading a target, running scanners/fuzzers, sitting on a pile of odd-but-inert observations, tempted to report something "probably exploitable", or about to conclude "nothing found". Applies to every target class (web/SaaS, smart-contract, infra/cloud, LLM/agentic, binary/firmware).
status: authored
---

# Systematic Bug Hunting

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


## Overview

`systematic-debugging` guards the *fix*. `systematic-attacking` guards the *claim* and the
*campaign*. This skill guards the **hunt** — the bench work between "I have an authorized
target" and "I have a proven chain to hand back."

Hunting fails in two characteristic ways, and they are opposites:

- **False positive** — a quirk, a reachable sink, or a one-step primitive gets written up as a
  finding because it *looks* exploitable. Reachability dressed as impact.
- **False negative** — the hunter runs two tools, applies the known class list, finds nothing
  individually decisive, and reports "nothing here." The bug was there; the arsenal was not.

Both are failures of the same discipline: **evidence before assertion, in both directions.**
You may not claim a bug you have not proven, and you may not claim absence you have not earned.

**Violating the letter of this process is violating the spirit of it.** A tool you decided not
to run is a tool that did not run. A chain you narrated is a chain you did not build.

## Subordinate by construction — what this skill may NOT do

This is **not** a second offensive lifecycle, and it is not a route around one. It is the craft
layer that runs *inside* `systematic-attacking` Phases 2–5. It holds **no authority**:

| Authority | Held by | This skill |
|---|---|---|
| Scope / authorization ("may I touch this?") | `systematic-attacking` Phase 0 (Law 1), Chrono holds the operator gate | **none** — refuses to start without a written scope lock |
| Promoting lead → finding | `systematic-attacking` Phase 6 (`impact-validator`, G1–G4, cross-family repro) | **none** — terminal output is a *proven candidate*, never a finding |
| Severity / CVSS | Phase 6, scored once from the terminus | **none** — no severity arithmetic anywhere in this skill |
| Submission | Phase 8, Chrono + per-report operator "go" | **none** — this skill never reaches Submit |

If you reached this skill without a Phase 0 scope lock (in-scope allowlist + forbidden set
written, operator target-engage obtained), **STOP**. Ambiguous scope is not a green light, and
"I was following the hunting skill" is not an authorization. A genuine refusal is terminal and
is never re-shopped through this file.

**REQUIRED GOVERNING METHOD:** `systematic-attacking`. Read it before using this skill.

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

```
IRON LAW 1 (inherited verbatim from systematic-attacking Law 2):
    NO FINDING WITHOUT A REPRODUCED, NEGATIVE-CONTROLLED, INTRINSIC-IMPACT PROOF.

IRON LAW 2 (this skill's own):
    NO "NOTHING FOUND" WITHOUT AN EXHAUSTED ARSENAL.
```

Law 1 is **inherited, not restated** — deliberately. A paraphrase drifts, and the looser
paraphrase becomes the bypass. Its bench-level consequence: a PoC must assert the **terminus
predicate**, not the existence of the primitive. "An attacker could then…" is the sentence that
marks an unproven chain.

Law 2 is what makes a hunt *systematic* rather than a look-around. A negative result is a
claim, and it carries the same evidence burden as a positive one. Before you may write "no
exploitable path found," the arsenal for the target class must have actually run (see
[Tool-intensity contract](#tool-intensity-contract)), the invention operators must have been
applied, and every catalogued primitive must have been tried as a chain link. **A tool that
would not run on the host is not an exhausted tool** — containerize it, or surface `needs_tool`
to Chrono. "Couldn't run it" is not a status.

## When to use

- Any authorized bug-hunting session, from first read of the target to a proven chain.
- Especially when: the scanners came back clean · you have a pile of weird-but-inert
  observations · you have applied every known class for the domain and found nothing · you are
  about to write up something you have not run · you are under deadline and the "obvious" bug
  is tempting.

**Do not use for:** deciding scope (Phase 0), scoring severity (Phase 6), packaging or
submitting (Phase 8), or defensive code review with no attacker model (use `findings-filter` /
`security-threat-model`).

## The hunt loop — H1 → H6

Six stages. Each names its hard gate and where it nests in the campaign. You MUST clear a
stage's gate before the next. Use `sequential-thinking` throughout — one hypothesis at a time,
written down, revised in the open.

| # | Stage | Hard gate | Nests in |
|---|---|---|---|
| **H1** | Surface & impact map | Entry points, trust boundaries, and the **payout termini** written down *before* hunting | Phase 2 |
| **H2** | Primitive discovery (intensive) | Arsenal actually run + manual read of every trust boundary; **every** deviation catalogued, including inert ones | Phase 3a |
| **H3** | Hypothesis & invention | The invention operators applied **and** the known-class pass run — **independently, not in sequence**; hypotheses are falsifiable and written | Phase 3a / 3b |
| **H4** | Chaining | A concrete link ordering from an attacker-controlled head to a terminus, with every precondition satisfiable | Phase 4 |
| **H5** | Proof | Runnable PoC asserting the **terminus predicate**, link + chain negative controls, all four observable predicates | Phase 5 |
| **H6** | Hand back | Evidence bundle handed to the campaign; dedup refreshed; **this skill stops here** | Phases 6–8 |

### H1 — Surface & impact map

Enumerate entry points (what an *unprivileged attacker* actually controls), trust boundaries
(every place data or control crosses from a less-trusted to a more-trusted context), and the
**impact termini** — the end states that pay: funds theft/drain · RCE / attacker-controlled
execution · auth bypass · privilege escalation / ATO · cross-tenant private-data compromise ·
attacker-controlled agent action.

Write each terminus as a **checkable predicate** ("attacker balance increased with no deposit",
"attacker holds admin role", "attacker executes a process as the service user"). You will
assert exactly these predicates in H5. Writing them first is what lets H3–H4 prune below-bar
paths instead of rationalizing them afterwards.

**Gate:** termini written before hypotheses. A hunt with no pre-registered terminus set
converges on whatever it happens to find and calls that the goal.

### H2 — Primitive discovery (intensive)

A **primitive** is a bounded attacker capability or environmental fact. It carries *capability,
not severity*. This stage produces the pool; `chain-strike-v2` §1 types it for the graph.

Run **both** halves — they find disjoint things:

1. **The arsenal.** Every relevant tool, skill, CLI, plugin, and API for the target class —
   see the [tool-intensity contract](#tool-intensity-contract). Commodity scanners on default
   rules are the *entry fee*, not the work: write target-specific rules
   (`semgrep-rule-author`, `diff-aware-semgrep-scan`), build a purpose-shaped harness
   (`fuzzing-campaign-flow`), and point them at the trust boundaries H1 named.
2. **Manual reading.** Read the code on both sides of every trust boundary yourself. Fuzzers
   find crashes; readers find *assumptions*. Most invention operators in H3 fire on something
   a human noticed and a tool cannot express.

**Catalogue every deviation — especially the inert ones.** An observation that does nothing on
its own is not a dead end; it is **chaining ammo**, and it is the single most commonly discarded
ingredient of a critical chain. Log it with its exact preconditions so H4 can use it.

**Primitive ledger** — one row per observation, no exceptions:

| id | what it lets the attacker do | exact preconditions | state it changes | observed by (tool + command / file:line) | inert alone? | relevant termini |
|---|---|---|---|---|---|---|
| P-07 | force a 500 whose body echoes the rendered template | any unauth POST to `/preview`; `tpl` param reaches the renderer | none | manual read `render.py:88` + curl repro | yes | RCE |

"Inert alone? = yes" is a *label*, never a delete. Rows are only removed when a chain built on
them is disproven, and the disproof is recorded.

**Gate (Law 2):** arsenal run (or `needs_tool` surfaced), every trust boundary read, ledger
written. No ledger, no hunt.

### H3 — Hypothesis & invention

Known classes are the **FLOOR, not the ceiling.** They are cheap and they dedup fast — but
**invention does not queue behind them.** On a post-remediation pin (the audit's own "post
audit changes" commit, which is a common bounty target) the known-class pass is **barren by
construction**: every class the vendor imagined has been fixed, so a lane that spends its
hour there reaches invention with nothing left. Run the two **independently**; if the target
is a remediated pin, run invention **first**.

**Known-class pass.** Apply the domain checklist set routed from `systematic-attacking`'s domain
table, plus the current palette (SC: ERC-1271 revert-data confusion, precompile-shadow signature
bypass, hook access control, read-only reentrancy, durable-nonce, single-DVN forgery · Web:
`error-based-ssti`, `parser-differential-route-confusion` · AI/agentic: CBSE config-based sandbox
escape, context-stitching injection, MCP tool/schema poisoning, prompt-injection-to-RCE · Binary:
memory corruption reachable to control). Also run `known-advisory-backport-check` — a patched
class that never landed here is a real bug, not a novel one, and it is cheap.

<a id="invention-operators"></a>
**Invention pass — the operators.** "Be creative" is not a method. These twelve operators
*construct* candidate techniques from the H2 ledger. Run each against the ledger and the surface
map; each produces hypotheses, most of which die, which is the point.

| Operator | Construction | Generalizes |
|---|---|---|
| **Boundary differential** | Enumerate every *pair* of components that independently interpret the same bytes (validator vs executor, proxy vs origin, parser vs serializer, indexer vs settler). Diff their interpretations on adversarial input. | parser-differential / route confusion |
| **Oracle inversion** | Find any observable that varies with secret or privileged state — error text, status code, timing, gas, revert data, log ordering, cache state. Turn a *blocked output* into an exfiltration or confirmation channel. | error-based ("successful-errors") SSTI |
| **Inverted assumption** | Enumerate the invariants the code assumes *silently*: ordering, uniqueness, monotonicity, atomicity, idempotency, unit, sign, precision, encoding, non-reentrancy, single-execution. Construct the state that violates each. | reentrancy, replay, rounding, confusion bugs |
| **Lifecycle seam** | Attack the transitions, not the steady state: init, upgrade, migration, rollback, retry, partial failure, cleanup, shutdown. Invariants are *re-established* at seams, so they are momentarily absent. | upgrade/migration takeovers, retry double-spend |
| **Trust inversion** | Make the trusted party consume attacker-controlled *structure* rather than attacker-controlled data — config, schema, tool description, callback target, template, deserialized type. | CBSE, MCP schema poisoning, deserialization |
| **Primitive mutation** | Take a known technique and mutate exactly **one** axis: actor, channel, encoding layer, timing, unit, privilege direction (try it *downward*), or trust direction. Check whether the mutant is unrecorded. | most "new" classes, historically |
| **Cross-domain transplant** | Take a technique proven in domain A and find the structural analog in domain B (web SSRF → agent tool-call; TOCTOU → oracle update window; HTTP request smuggling → RPC batch framing). | cross-domain pivots |
| **Guard implantation** | Take a guard a *sibling* path enforces, copy it verbatim into the path that lacks it, and run the project's own test suite. If **zero tests break**, no behavior the team wrote down depends on that path being unguarded — the absence is *unmodelled*, not intended. | the "does it NEED the guard?" predicate |
| **Cross-implementation acceptance differential** | When one protocol has two implementations (EVM/SVM, v1/v2, fork/upstream, client/server), feed both the *same* wire-format input and diff what each **accepts, rejects, and how it dedups**. Divergence is unspecified behavior. | multi-impl consensus/replay splits |
| **Fix-lineage variant hunt** | Mine the vendor's own security-fix commits (`git log --grep` for advisory ids / `[REPORTED]` / fix markers), infer the predicate each fix established, then hunt siblings, clones, alternate entry points, and branches where that predicate was never applied. | incomplete-fix / N-day variants |
| **Deployed-artifact congruence** | Diff what is *deployed* against what is in source — bytecode, deployed config, init state, build flags, CI-generated code. Source review audits an artifact that may not be the one running. | source/deployment mismatch |
| **Divergence mining** | Run two model families over the same surface, then mine where they **disagree**. A disagreement localizes an unstated assumption one side made and the other did not — and the disagreement set is small and pre-filtered. | assumption discovery |

**Why guard implantation is the sharpest of these.** Mutation testing generates *weakening*
mutants, because for a correctness audience a strengthening mutant that still passes is
uninteresting. For a security audience it is the entire signal. Implanting the sibling's guard and
watching the suite stay green converts "a guard is missing here" — which is only a lexical
observation, and which commodity tooling and analysts both over-report — into evidence about
**intent**, evaluated in the developers' own language by their own CI rather than by your
judgment. Run it before promoting any missing-guard observation to a hypothesis.

**Kill ledger discipline.** A kill is a dated claim, not a permanent fact. Every kill records the
**assumption it rests on**; when that assumption is later contradicted, the kill *reopens*. Kills
resting on "only a privileged/compromised actor could do this" are the highest-risk class — they
are correct only until someone finds an unprivileged path to the same state. Do not re-walk kills
at random; re-walk the ones whose assumption just changed.

**Novelty test.** A hypothesis is a *candidate new technique* only if (a) it is absent from the
palette **and** (b) `dedup-prior-art-check` returns `novel` for the technique shape, not merely
for this target. Novelty is a dated dedup verdict, never a feeling of unfamiliarity.

**Naming duty.** If a candidate new technique survives H5, you owe it a **name**, a one-paragraph
reusable write-up (mechanism → precondition → observable → terminus), and a `chrono-vault`
record. An invention that is not written down is a one-off; written down, it becomes next hunt's
floor. This is where the moat compounds — not in owning scanners everyone owns.

**Gate:** known classes exhausted, all twelve operators applied against the ledger, hypotheses
written as falsifiable statements ("if X, then observable Y"), each tagged with its target
terminus. Hypotheses with no terminus are **banked with `terminus: unknown`**, not dropped — a capability
whose terminus has not been found is exactly what Phase 4 composes. Only a hypothesis that has been
*shown* to have no reachable terminus is closed, and it is closed as a dated `dedup-dead`/`no-terminus`
disposition that reopens if the assumption is contradicted.

### H4 — Chaining

Individually-inert primitives are the normal ingredients of a critical finding. Compose them.

**Route into the chaining method, do not restate it:** `chain-construct` (generic link ordering)
and `systematic-attacking`'s `references/chain-strike-v2.md` §1–3 (typed primitive graph +
impact-first bidirectional search). For contracts, `chain-construct-smart-contract`.

Bench rules that belong to *this* stage:

- The chain **head** is the first thing the attacker actually controls. Anything upstream is a
  precondition — state it, do not assume it.
- Every link's precondition must be satisfiable by the attacker or produced by an earlier link.
  A precondition only an admin/insider/lucky race can supply is a *stated limitation*, not a
  silent one.
- Re-walk the ledger's inert rows explicitly before declaring no chain exists. Law 2 applies to
  chains, not only to tools.
- No severity arithmetic. A chain of mediums is not a high; the *terminus* decides, once, later.

**Gate:** a written link ordering from head to terminus with every precondition satisfiable, or
an explicit, recorded "no path" that names which inert primitives were tried and why each failed.

### H5 — Proof

**The PoC asserts the terminus predicate from H1** — not the primitive, not the intermediate
state, not a screenshot of a stack trace. Run it against the *real* oracle in a sandbox,
synthetic replica, or read-only fork (`sandbox-provision-discipline`); never against a mock that
you also wrote.

- **Negative controls, link and chain level** — per `chain-strike-v2` §4. Without a control, a
  passing PoC shows correlation, not causation.
- **Stability** — repeat from a clean snapshot. One success is an anecdote.
- **All four observable predicates hold** per `multi-agent-evidence-gating`, scored from concrete signals (oracle
  match, control separation, repeat stability, harness fidelity to prod) — not from conviction.
- **Any live, mutating, or credential-using step STOPS for the operator gate.** No exceptions,
  including "it's read-only in practice."

**Gate (Law 1):** runnable PoC + passing negative controls + terminus predicate asserted. Short
of that, the output is a lead. Label it a lead and say so plainly.

### H6 — Hand back

Terminal act: hand the evidence bundle (PoC, controls, confidence rationale, ledger, chain,
limitations, negative results) to the campaign. `impact-validator` runs G1–G4, a different model
family reproduces, `dedup-prior-art-check` is refreshed, `skeptic` attacks soundness, Chrono
de-AIs and packages, and the **operator** clicks Submit.

**You do not do any of those here.** A hunter who scores their own finding has left the method.

<a id="tool-intensity-contract"></a>
## Tool-intensity contract

Law 2's teeth. "Exhausted" has a floor per target class; below it, a negative result is not
reportable. Exact executables are lane-specific — read your adapter and verify each in the live
runtime before use.

| Target class | Floor for "arsenal run" |
|---|---|
| **Smart contract** | static analyzers + custom detectors · property/invariant fuzzing · symbolic/solver pass · **fork against real state** (not a fresh deploy) · manual read of every external-call and accounting path |
| **Web / SaaS / API** | authenticated + unauthenticated crawl · SAST with target-specific rules · template/scanner sweep · request-mutation fuzzing on the live surface · source-map / client-bundle recovery · manual read of authz decision points |
| **LLM / agentic** | tool/schema surface inventory · injection corpus across every untrusted channel · MCP/tool-description poisoning probes · sandbox-escape config surfaces · transcript analysis |
| **Binary / firmware** | coverage-guided fuzzing with a real harness · symbolic exploration of reachable sinks · reachability from an attacker-controlled entry, manually confirmed |
| **All** | prior-art/dedup **before** effort · the twelve invention operators · `variant-analysis` on every confirmed defect |

Rules that make the floor real:

- **A skipped tool voids the negative result.** If it does not run on the host, run it in a
  container. If it cannot run at all, surface `needs_tool` under `## NEEDS FROM CHRONO` and
  record the gap in the output — a documented gap is honest, a silent one is a false negative.
- **Default rules are the entry fee.** The finding that pays is usually behind a rule or harness
  you wrote for *this* target. AI + off-the-shelf SAST is commodity; everyone running it finds
  the same things, and duplicates do not pay.
- **Repurpose freely.** Any API, CLI, plugin, or MCP is fair game even outside its intended use
  (a diff tool as a differential oracle, an indexer as a state-history source, a formatter as a
  parser-differential probe) — inside scope and inside the operator gates.
- **Never a substitute for reading.** The arsenal is the floor of the hunt, not the hunt.

## Evidence that survives review

Learned the expensive way across four a bridge target audits. Every item below is a real result this
pipeline got **wrong and confidently** — a passing engine, a clean census, or a reproduced exploit
that dissolved on inspection. Apply these to your own output before anyone else has to.

### Every engine needs a deliberately-false twin

A passing property is indistinguishable from a vacuous one. For each engine you run, also run a
**twin that must fail** — same harness, one assumption inverted. If the twin passes, your real
result means nothing and you must say so.

- `halmos` reporting `paths: 2` looks identical whether it proved something or explored nothing.
- A custody lane ran **five** false twins; all five failed as required, which is the only reason
  its 98,304-call negative was trustworthy.

### Fuzz campaigns need a non-vacuity gate

**Report `successfulCalls`, not just the call count.** A lane reported **6.2M and 12.3M passing
calls** with `successfulCalls == 0` — nothing was ever exercised. Two causes, both easy to hit:

- `vm.prank` rewrites `msg.sender` but **not the source of `msg.value`**, so every value-carrying
  branch reverts and the campaign silently does nothing.
- A non-vacuity check written as `invariant_` is evaluated at **depth 0**, before the campaign runs,
  so it always passes. Put it in **`afterInvariant`**.

**A call count without a non-vacuity gate is not evidence.**

### The #1 false positive is a privileged prank

Before promoting any PoC, run a **`msg.sender`-only swap control**: byte-identical calldata, only
the caller changed, asserting the unprivileged caller **reverts**. A "Critical" that drained a
victim's balance this campaign turned out to work only because the harness pranked `TSS_ROLE`.
A control that varies the *payload* does not catch this.

### Symbolic counterexamples are hypotheses

- `halmos` models `keccak256` as **uninterpreted with no injectivity axiom**, so any property
  phrased over **digests** is vacuously satisfiable and emits counterexamples that cannot exist
  on-chain. Phrase properties over **preimages**.
- `--loop` defaults to **2** and truncates silently. Set it explicitly and state what you used.
- **Reproduce every symbolic counterexample as a concrete test before believing it.**

### Settle "these are all the X" claims by census, not by reading

A source reader enumerates the paths they thought of. For any completeness claim — all value
exits, all external entrypoints, all delegatecall sites — census the **compiled runtime bytecode**
for the relevant opcodes (`CALL`, `DELEGATECALL`, `CALLCODE`, `CREATE`, `CREATE2`, `SELFDESTRUCT`)
and attribute each site to a source line via the compiler's source map. It is exhaustive by
construction and takes ~10 minutes.

**Mandatory step: stop at the CBOR metadata boundary.** Solidity appends a metadata trailer whose
bytes decode as opcodes and will produce phantom `SELFDESTRUCT`/`CALL` hits. A census that skips
this **invents findings**.

### Check call-site provenance before weaponising

For any dangerous-looking parameter, answer three questions **before** building a PoC:

1. Who actually calls this? (`grep` the call sites across all in-scope repos, and read the tests.)
2. Is the dangerous parameter attacker-controlled at **every** call site, or hardcoded / registry-sourced?
3. **Which program owns the call site?**

Twice this campaign a real, severe primitive was unreachable because its sole caller hardcoded the
dangerous argument — and once the only thing preventing exploitation lived in a **sibling bounty
program**, making a perfect exploit unpayable. Minutes of tracing, hours saved.

### A tool's issue count is not a signal

"The tool runs" and "the tool found something" are different claims. **Filter generated code**
(`*.pb.go`, `*.g.dart`, ABI bindings, macro expansions) before quoting any number: a reported
"182 gosec issues" was **182 of 182** generated-protobuf `G115` noise, zero in hand-written code.
Quote the surviving count, or quote nothing.

### Dedup against sources that actually bind

Before spending a lane on a lead, in cheapness order:

1. **Our own prior submissions** for that exact program, from the platform's authenticated report
   API — a campaign re-derived two findings we had already filed and had rejected.
2. **The vendor's own threat model / docs**, grepped for the lead's **own words** — one lead was
   named verbatim in `THREAT_MODELLING_DOC.md` and asserted by a vendor test, so it was excluded
   before it was technically wrong.
3. **Our prior campaign runs** on the same commit. **Zero submissions is not zero prior work.**

## Red flags — STOP

| Thought | What it actually means | Do this instead |
|---|---|---|
| "It's probably exploitable." | You have a primitive, not a chain. | H4 → H5. Prove it or label it a lead. |
| "Theoretically an attacker could…" | The word *theoretically* is the confession. | Build the chain, assert the terminus predicate. |
| "This looks weird — report it." | A quirk is a ledger row. | Log as a primitive; hunt the terminus it reaches. |
| "One primitive, it's inert, dead end." | You threw away the chain ammo. | Log preconditions, keep hunting, re-walk it in H4. |
| "I applied all the known classes — nothing here." | You stopped at the floor. | Run the twelve invention operators (H3). |
| "That tool won't run on this host, skipping." | Law 2 violation; your negative result is void. | Containerize it, or surface `needs_tool`. |
| "I can reason about this instead of running it." | Reasoning is not evidence when a tool can falsify. | Run the tool. Reasoning picks *which* tool. |
| "The PoC proves the primitive works." | Wrong predicate. | Assert the H1 terminus predicate. |
| "It reproduced once." | Anecdote. | Negative control + repeat from clean snapshot. |
| "This must be novel — I've never seen it." | Novelty is a verdict, not a feeling. | `dedup-prior-art-check` on the technique shape. |
| "It's a bit out of scope but it proves the point." | Law 1 violation, and legally the worst kind. | STOP. Scope questions go to Chrono/operator. |
| "Deadline's close, ship what we have." | Time pressure is exactly when the 1-in-21 becomes 0-in-21. | Ship *leads labelled as leads*, or ship nothing. |

**All of these mean: STOP and return to the stage named in the third column.**

## Common rationalizations

| Excuse | Reality |
|---|---|
| "The scanner is clean, so the target is clean." | The scanner covers what its authors anticipated. Nothing pays for finding what everyone's scanner finds. |
| "Writing a custom rule/harness costs more than it returns." | It is the only part of the pipeline that is not commodity. It *is* the return. |
| "Chaining is over-engineering; the bug is the bug." | Most criticals are compositions of individually-inert primitives. Refusing to chain is refusing the payout class. |
| "The inert observations aren't worth logging." | They are the ammo you will want in H4, when you no longer remember the preconditions. |
| "Impact is obvious, the PoC is a formality." | Obvious impact that was never reproduced is the single most common rejected submission. |
| "A mock is close enough to the real oracle." | Model mismatch — a prod guard the mock omits turns a critical into noise. Real oracle or it did not happen. |
| "I'll dedup after I finish the write-up." | Dedup *before* effort. A duplicate is unpaid work regardless of how good the write-up is. |
| "Novel work deserves a lower proof bar." | Experimental leads earn no laxer verification. Same spine, same gates. |
| "Nothing found — the target is solid." | Only after the arsenal ran, the operators fired, and every inert primitive was tried as a link. Otherwise: "not found *by this pass*", with the gaps named. |

## Quick checklist

- [ ] Phase 0 scope lock exists and is current; no action outside the allowlist.
- [ ] H1: entry points, trust boundaries, and **terminus predicates** written *before* hunting.
- [ ] H2: arsenal floor run (or `needs_tool` surfaced); every trust boundary read manually.
- [ ] H2: primitive ledger written — **every** deviation, inert rows kept with exact preconditions.
- [ ] H3: known classes + `known-advisory-backport-check` worked; **all twelve invention operators** applied.
- [ ] H3: hypotheses falsifiable, each tagged to a terminus; novelty is a dated dedup verdict.
- [ ] H4: link ordering head → terminus, every precondition satisfiable; inert rows re-walked; **no severity arithmetic**.
- [ ] H5: PoC asserts the **terminus predicate** against the real oracle; link + chain negative controls pass; stable on repeat; all four observable predicates.
- [ ] H5: operator gate cleared before any live / mutating / credential-using step.
- [ ] H6: bundle handed back; **no self-scoring, no self-dedup verdict, no submission** from this skill.
- [ ] Any surviving new technique: named, written up, recorded.
- [ ] Negative result (if any) states the arsenal run, the operators applied, and the gaps that remain.

## Recording (chrono-vault)

Record once at H6 via the `chrono-vault` `record` tool (the retired in-repo KG is not a target):

- `attempt` — a hunt that produced no proven chain. Include the arsenal actually run, the
  operators applied, the ledger size, and the named gaps. **Negative results are the most
  reusable memory the squad has** — they stop the next hunter re-running a dead pass.
- `finding` — a proven candidate handed to H6, with `target` and a real `attack_class`.
- `learning` — a surviving new technique, under its name, in reusable form.

Recording is best-effort telemetry and is never a gate: if it errors, note it in one line and
continue.
