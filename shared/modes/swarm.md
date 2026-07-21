# Swarm-v1 cross-model dispatch contract

Swarm is an opt-in dispatch shape for independent cross-model execution of the **same specialist and same objective**. It is system-wide: any canonical specialist may use it when every requested lane has a same-name native adapter and the packet passes all ordinary authorization, scope, capability, and review gates.

```bash
bin/send-task.sh TASK.md --swarm claude,gpt-codex --swarm-timeout 3600
```

## Distinction from panel and fan-out

- `single`: one ordinary model-lane task.
- `panel`: one coordinator task with several local specialist opinions and one artifact.
- `fanout`: one model runs the same specialist on several **different** assignments.
- `swarm`: several model lanes independently run the same specialist on the **same** objective; each child has its own task ID, delivery receipt, claim, contract, artifact, sidecar, and response.

`--swarm` is mutually exclusive with `--panel` and `--fanout`. Nested swarm/panel/fan-out is prohibited in v1.

## Model-role architecture

- Kimi is the narrowly authorized `experimental-attacker`: high-volume hypotheses and probing whose outputs are leads.
- Gemini is the `bounty-researcher`: grounded prior-audit, historical-exploit, incident, and taxonomy research whose outputs are leads.
- Claude and Codex are the heavy hitters: rigorous audit, implementation, reproduction, impact validation, and formal review.

A Kimi- or Gemini-only result is never a validated finding. It remains lane-only or divergent until a heavy hitter independently confirms the canonical finding and the mandatory review settles the frozen swarm bundle.

## V1 admission and scope

- Two to four unique explicit lanes; all members must pass canonical specialist, ranked-route, native-adapter, and capability checks before publication.
- `write_scope: []` only, apart from dispatcher-derived lane-isolated artifacts and member sidecars. Shared-tree implementation races require isolated worktrees and are deferred.
- `all` quorum with a bounded timeout. Missing, refused, failed, malformed, and timed-out members are explicit coverage gaps.
- A predeclared refusal surfaces and never causes dynamic family addition or refusal shopping.
- No external delivery, target contact, submission, spending, signing, broadcast, production mutation, or public release beyond the original packet's explicit operator gates.

## Parent and children

The original task ID is a non-delivered controller parent. Lane-suffixed child IDs are ordinary mailbox tasks and use the normal claim/delivery fencing. The controller pins a canonical swarm membership hash over the objective, lane set, child IDs, mode/result type, timeout, and derived artifacts. Every child echoes that hash and owns a full lane-derived `verification-contract/v1` with `dispatch_kind: swarm`.

Members must not read sibling outputs before their own artifact and sidecar are frozen. Shared filesystem isolation is procedural in v1; cryptographic or worktree isolation is future work.

## Member result

Every completed child writes a strict `swarm-member-result/v1` sidecar using the vocabulary in `shared/finding-taxonomy.md`. The finding key is exact and deterministic. Model-authored keys are evidence metadata, not semantic proof; schema/hashes can be mechanically checked, semantic honesty remains reviewable.

Malformed sidecars are coverage gaps. The reconciler never invents a key, fuzzily merges prose, or repairs a substantive verdict.

## Deterministic reconciliation

The controller groups exact finding keys into:

- `agreement`: multiple families report compatible dispositions for the exact key;
- `divergence`: the same key has conflicting disposition, severity, root cause, exploitability, or evidence;
- `lane_only`: only one lane reports the key;
- `coverage_gaps`: missing/refused/failed/timed-out/malformed/hash-invalid children.

There is no LLM in reconciliation and no majority vote. Agreement is corroboration. For bounty cross-family reproduction it additionally requires two different author families, each with its own required scope/no-self-inflicted/PoC-or-negative-control evidence.

## Mandatory review and settlement

**Every swarm requires formal review.** Swarm children and the parent default to `mandatory_review: true` regardless of a weaker source packet. Parallel agreement never settles the parent by itself because independent authors did not review one another's frozen artifacts.

The deterministic diff may freeze while review is pending. The parent remains `needs_review` until Chrono explicitly settles a review whose subject is the frozen `swarm_bundle_sha256`. Divergence, lane-only findings, or a malformed member also keep the parent in review. Fewer than two usable author families is `blocked` because no cross-model comparison occurred.

If the swarm changes implementation or code, include `vibecoding-check` in the explicit review of the frozen bundle before settlement.

## Failure semantics

- Complete-set preflight failure: publish nothing and report the exact failed lane/adapter/policy gate.
- Partial inbox publication: preserve receipts, mark the affected child and parent honestly, and never fabricate atomic success.
- Duplicate envelope/reconciler events: idempotent; a frozen diff and parent envelope are written once.
- Deadline: freeze with explicit gaps. A late child is recorded but cannot mutate the frozen bundle.
- Parent/diff failure: children retain their individual evidence; parent stays blocked or needs review.

## Bounded lead-internal orchestration

A cross-lane swarm member may not create another registered mailbox tier. Separately, an explicitly single-dispatched lead may receive a sealed `lead-orchestration-directive/v1` through `send-task.sh --subswarm-directive`. That directive authorizes only the declared native runtime children, identified as `<lane>:subNN`; they receive no mailbox task, claim, lease, outbox, or settlement authority. The lead remains the sole registered task owner and must preserve each raw child return, seal one `swarm-member-bundle/v1`, and decompose every completion, finding, gap, and tool receipt for review. `SQUAD_WORKER_POOL_ENABLED` is not part of this prompt-level native fan-out path.

## V1 exclusions

Shared-tree writes by internal members, per-child worktrees, fuzzy semantic clustering, numeric early quorum, dynamic internal members, automatic review-task creation, a registered third orchestration tier, automatic publication/submission, and failover across sibling identities.
