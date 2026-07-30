---
name: chain-construct
status: authored
---

# chain-construct

Generic multi-step attack-chain builder. Turn a set of individually-weak observations into a
single demonstrated exploit chain whose end state proves realized impact. Domain skills
specialize this — e.g. `chain-construct-smart-contract` adds EVM/Solana primitives. Use when a
finding requires more than one step to reach impact, or when several low-severity leads may
compose into a payout-class result (RCE, auth-bypass, privilege-escalation/ATO, private-data,
funds theft).

## Method

1. **Fix the objective as an end state, not a step.** Write the impact you must demonstrate as
   a checkable predicate ("attacker balance increased by X without deposit", "attacker holds
   admin role", "victim record disclosed"). A chain is valid only when the final state
   satisfies that predicate — reachability of an intermediate step is not the objective.
2. **Map the chain head.** Identify the first thing the attacker actually controls (an input,
   an externally-callable entry point, a crafted account/message). Everything upstream of it is
   a precondition, not part of the chain.
3. **List candidate links.** For each confirmed or suspected weakness, record: what it lets the
   attacker do, what state it changes, and what precondition it needs. A link is only usable if
   its precondition is satisfiable by the attacker or by an earlier link's output.
4. **Order links by state-feeds.** Link A precedes B iff A's output state satisfies B's
   precondition. Reject any ordering that requires a precondition no earlier link (or the
   attacker) can produce.
5. **Build the minimal chain.** Prefer the shortest ordering that reaches the objective. Drop
   links that do not move state toward the predicate.
6. **Prove it, don't assert it.** Author a runnable reproduction (test/harness/script) that
   executes the chain end-to-end and asserts the objective predicate on the final state. A
   theoretical chain is a lead, not a finding, until the reproduction passes.
7. **Document preconditions honestly.** State every environmental precondition the chain needs
   (specific state, funds available, a block/time delta, a fork block number). A chain that only
   works under an unstated precondition is not portable and must say so.

## Anti-patterns

- Do NOT count a reachable intermediate step as impact — only the objective predicate on the
  final state counts.
- Do NOT assume a precondition an attacker cannot actually establish (admin keys, a
  compromised operator, an unreachable state) — that is out of scope for most programs.
- Do NOT conflate a theoretical chain with a demonstrated one — the reproduction must pass.
- Do NOT self-spawn helpers to build the chain; if you need another specialist or a dispatch,
  surface it under `## NEEDS FROM CHRONO`.

## Recording (chrono-vault)

After building a chain, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="attempt", fields={"title": "chain-construct: <objective>", "body": "chain_head=<entry>; links=<numbered>; objective_predicate=<...>; reproduced=<bool>; preconditions=<...>", "target": "<target>", "attack_class": "<class>", "source_task": "<task-id>"})`.
Record a reproduced chain as `note_type="finding"`. A memory error is logged in one line and
never blocks the work.
