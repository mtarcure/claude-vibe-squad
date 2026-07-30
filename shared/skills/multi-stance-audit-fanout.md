---
name: multi-stance-audit-fanout
status: authored
---

<!-- inspired by pashov/skills:solidity-auditor (MIT); recast Chrono-orchestrated -->

# multi-stance-audit-fanout

Stance-based audit fan-out. Eight specialist personas read the same Solidity source through
different mental models; findings are then deduplicated by group key with composite-chain
detection. Distinct from `evm-audit-flow` (tool pipeline) — this fans out *human-style review*
across audit lenses to catch logic bugs no detector finds.

**Orchestration model (read first).** This is a **Chrono-orchestrated** fan-out. Workers
NEVER self-spawn, launch a model CLI, or dispatch sub-agents — that is Chrono's job. A
security-analyst worker does NOT run the eight stances itself. Instead this skill defines (a)
the stance roster + briefs, (b) the source bundle, and (c) the dedup/promotion method, so a
worker can either **surface the fan-out as a need** (`## NEEDS FROM CHRONO: dispatch the 8
stance packets over <bundle>`) or, when acting AS the Chrono-appointed coordinator, dedup the
returned stance outputs. Chrono dispatches N stance packets on the board rail; a coordinator
role dedups and writes the single consolidated result.

## When to use

- A contract has passed `evm-audit-flow` static + symbolic passes but still needs logic-bug
  coverage no detector catches.
- The target is small enough (≤2k nSLOC) for eight readers to cover end-to-end.
- You want stance diversity (8 lenses, 1 model) cheaply, before paying for model diversity
  (a full multi-model fan-out).
- Skip when a fresh equivalent report already exists; do not duplicate.

## Stance roster

Each stance gets the SAME source bundle plus its own role brief. The eight stances are:

1. **vector-scan** — sweep known vuln classes (reentrancy, oracle manip, signature replay,
   storage collision, delegatecall hijack, slippage, sandwich, MEV).
2. **math-precision** — rounding direction, decimal scaling, fixed-point overflow, division
   before multiplication, dust accumulation, precision loss across token decimals.
3. **access-control** — role surface, two-step transfer correctness, initializer reentrancy,
   modifier ordering, bypass via internal-call routing.
4. **economic-security** — incentive design, MEV extraction, fee accrual paths, redemption
   griefing, donation attacks, rebalance arbitrage, liquidation race conditions.
5. **execution-trace** — pick the top 3 fund-flow paths, single-step from entry to settlement,
   note every state read/write/external call along the way; chase reachability not patterns.
6. **invariant** — derive invariants the protocol *should* hold (`totalSupply == sum(balances)`,
   `k` for AMMs, collateralization ratio, share-to-asset monotonicity), then look for paths
   that break each one.
7. **periphery** — ERC-20/721/777 quirks, fee-on-transfer, rebasing, missing return values,
   `safeTransfer` gaps, `permit` front-running, callback re-entry surfaces.
8. **first-principles** — ignore checklists; ask "what is this contract trying to do, and what
   would I do as the attacker if I had infinite time?" Capture novel/unnamed bug classes.

## Order of operations

1. **Bundle source (worker or coordinator).** Build a single `source.md` with every in-scope
   `.sol` behind a `### path` header and a fenced block. Skip `interfaces/`, `lib/`, `mocks/`,
   `test/`, `*.t.sol`, `*Test*.sol`, `*Mock*.sol`. Record line count.
2. **Fan out (Chrono).** Chrono dispatches one board packet per stance — stance name, the
   stance brief from the roster, the bundled source, and the output schema below. Eight
   independent workers; no worker spawns another. If you are a worker and the fan-out has not
   been dispatched, surface it under `## NEEDS FROM CHRONO` — do not attempt to launch it.
3. **Output schema per stance.** Each stance returns FINDING and LEAD entries:
   ```
   FINDING|LEAD: <Contract>.<function> — <bug-class>
   group_key: <Contract>|<function>|<bug-class>
   confidence: 0-100
   rationale: 1-3 sentences
   trace: <numbered call/state steps if applicable>
   ```
4. **Deduplicate by group_key (coordinator).** Exact-match merge first. Then merge synonymous
   bug-class tags that share the same contract/function (e.g. `slippage` ≈ `price-impact`).
   Annotate each merged finding with `[stances: N]`.
5. **Composite chain pass.** If finding A's output-state precondition feeds B AND combined
   impact is strictly worse than either alone, emit `Chain: [A] + [B]` at
   `confidence = min(A, B)`. Most reviews surface 0–2 chains.
6. **Promote LEAD → FINDING.** Promote at confidence 75 if either: (a) a complete exploit
   chain is traced in source, OR (b) `[stances: 2+]` agree even when one stance demoted. Never
   promote on stance-count alone without source-level confirmation.
7. **Hand off.** Send the deduplicated finding set to the multi-model FP-filter and then
   `impact-validator` (G1–G4) before recording — stance diversity catches different bugs than
   model diversity does, and reachability alone does not pay.

## Anti-patterns

- Do NOT self-spawn the stances — surface the fan-out to Chrono; workers never launch sub-agents.
- Do NOT inline source into stance prompts repeatedly — bundle once, reference path.
- Do NOT collapse stances into a single mega-prompt; the diversity comes from role isolation.
- Do NOT promote LEADs on stance-count alone — `[stances: 2+]` does not override a concrete
  refutation by another stance with code evidence.
- Do NOT reason about deployer intent — evaluate what the code *allows*.

## Recording (chrono-vault)

After the fan-out consolidates, the coordinator records best-effort telemetry via chrono-vault
`record` (never a gate):
`record(note_type="attempt", fields={"title": "multi-stance-audit-fanout on <target>", "body": "stance_count=8; raw_finding_count=<n>; merged_finding_count=<n>; chain_count=<n>; leads_promoted=<n>; bundle_path=<path>", "target": "<target>", "attack_class": "logic-review", "source_task": "<task-id>"})`.
Record each surviving FINDING as `note_type="finding"` with its specific `attack_class` AFTER
the impact gate. A memory error is logged in one line and never blocks the audit.
