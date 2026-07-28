# chain-impact-rescore

**Offensive vulnerability chaining.** Not a post-hoc rescore — a hunting method. Every finding is a **primitive** (a capability granted to an attacker), never a terminus. The job is to chain primitives *forward* until they reach real terminal impact — funds moved, users harmed, code executed, permanent freeze — and to keep going even after you hit a "critical."

## Core stance
- A defense that kills a finding **in isolation** often falls when a *separate* primitive forces its precondition. Isolation-review misses chains by construction.
- "It halts / it leaks / it crashes / it forges *this* one thing" is a **link, not a terminus.** Keep asking: *what does this enable next?*
- Assume the gap exists. Instead of "can I break defense D?", ask "**what would have to be true** for D to fail?" — then hunt for a primitive that makes it true.

## Method
1. **Inventory primitives.** List every finding, near-miss, hardening note, defense-caveat, self-inflicted quirk, AND every reachable known-CVE capability. For each, write the raw capability, not the severity: *"can crash a node with an unauthenticated tx"*, *"can bend block Time as a validator"*, *"fail-open accept when a chain lookup is unavailable"*, *"can lower a quorum threshold"*, *"can read X"*.
2. **Forward-chain each primitive (offensive).** For every primitive — *including criticals* — enumerate what it unlocks:
   - *Halt/DoS* → what window does stopping (these) node(s) open? shift an attestation/consensus quorum? freeze a time-sensitive path (oracle staleness, liquidation, governance timeout, unbonding)? crash *which* nodes to change *who* decides?
   - *Time/ordering bend* → which security check trusts it (expiry, staleness, timeout, sequencing)? does bending it replay, evict, or bypass?
   - *Fail-open / missing-check* → what forces the precondition (a state, a race, a resource-exhaustion primitive, a config default)?
   - *Info leak / read* → what does knowing it unlock (a key, a nonce, a target, a bypass)?
   - *A forged/critical action* → what's the *next* link? one forged signature → drain which vaults, across which chains, up to what cap? push past "critical" to **maximal realized damage**.
3. **Compose (cross-chain).** Build the dependency graph: does primitive A satisfy primitive B's precondition? A self-inflicted or "needs-privilege" quirk becomes an attacker weapon when another primitive supplies the missing capability. Try A→B, B→A, and A+B→new.
4. **Verify each link atomic.** Each link must be independently achievable at the required privilege (prefer no-privilege). Note where a link demands escalation and whether an earlier link supplies it.
5. **Re-score the terminus.** The chain's severity is its *endpoint*, not any single link — a chain of mediums/lows routinely terminates in a critical. State the terminal impact concretely (whose funds, how much, how repeatable).

## Chain even the criticals
Finding a critical is the *start* of a chain, not the end. A signature forge, a halt, an unauthorized mint — each is a powerful primitive. Ask what a second critical composes into: does the halt let you win the race the theft needs? does the forge on chain A let you drain chain B? does the mint let you pass a collateral check elsewhere? The best submissions are often "critical A, and it also unlocks B and C."

## Terminal-impact gate (feeds impact-validator G1)
A chain is submittable only when it **ends** in funds-moved / secret-read / user-data-accessed / code-executed / permanent-freeze at the required (ideally no-) privilege. If it ends in "could/halt/leak," it is not done — either find the next link or record exactly which link breaks and why (a cited broken chain is a valid, honest result). Known/public/dep-CVE *primitives* are fine as **inner links** even though they're dedup-dead as standalone submissions — the novelty lives in the composition and the terminus.
