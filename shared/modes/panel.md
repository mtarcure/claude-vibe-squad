# Panel-v1 Dispatch Contract

Panel dispatch is an opt-in task shape. It is not a squad mode and does not change ordinary one-packet/one-lane dispatch.

Activate it with:

```bash
bin/send-task.sh <task-file> \
  --panel code-reviewer,test-engineer \
  --panel-policy evidence-synthesis \
  --panel-quorum all \
  --panel-timeout 900
```

Without `--panel`, `bin/send-task.sh` preserves the existing dispatch path.

## Scope and limits

- Supported lanes: `claude`, `gpt-codex`.
- Member count: two or three. The coordinator consumes the fourth thread.
- Nested panels are prohibited.
- One panel is one parent task, one failover attempt, and one canonical artifact.
- The parent task's source/compatibility namespace and coordinator specialist keep their normal routing meaning.
- Panel members must be known canonical specialists with native adapters on the selected lane.

## Flat packet fields

The dispatcher injects these fields into its working copy only:

```yaml
dispatch_kind: panel
panel_id: PANEL-<task-id-suffix>
panel_members: [code-reviewer, test-engineer]
panel_policy: evidence-synthesis
panel_quorum: all
panel_timeout_seconds: 900
panel_max_parallel: 3
panel_return_contract: lane-native-v1
panel_member_write_scope: []
```

Per-member assignments are appended to the body. The original task file is not rewritten.

## Invariants

1. Members never write `departments/*/outbox/` or `_state/failover/staging/`.
2. The coordinator is the sole canonical outbox/staging writer.
3. Members start in parallel; the coordinator does not wait between spawns.
4. Every returned, failed, refused, late, and timed-out member remains visible in the aggregation.
5. A genuine safety refusal surfaces as a result and is never retried cross-family to obtain a different safety decision.
6. Failover observes only the parent task. Children do not create attempts or publish artifacts.
7. Activity state has one writer: the coordinator.

## Coordinator lifecycle

The coordinator must implement this lifecycle in a finally-safe control flow:

1. **Validate** the member roster, adapters, lane, concurrency budget, member write scope, quorum, timeout, return artifact, and result schema.
2. **Create activity** with `bin/panel-activity.sh create`; every member begins `queued`.
3. **Spawn all members** before waiting. Transition each successfully spawned member to `running`.
4. **Collect lane-native returns** and normalize them:
   - Claude: coordinator-pull plus deterministic `_state/scratch/<task-id>/<member>.md` file return is required. Claude auto-return is not assumed.
   - Codex: native parent-message return is primary. A scratch file is optional for oversized results when the packet grants that scope.
5. **Update activity** for `done`, `failed`, `refused`, or `timed_out` members.
6. **Wait for quorum or timeout.** `all` requires every member to reach a terminal state. Numeric quorum permits aggregation after that many usable `completed` results; remaining late members become explicit coverage gaps at the deadline and never block the outbox indefinitely.
7. **Collate deterministically** by validating schemas, retaining attribution, grouping claims by subject/evidence, and identifying agreement and contradiction.
8. **Synthesize with evidence** into consensus, unique findings, unresolved conflicts, coverage gaps, refusals/failures, tools used, and limitations. Evidence strength may resolve a conflict; majority count may not.
9. **Write exactly one canonical response** as the coordinator.
10. **Close activity in a finally path** using `bin/panel-activity.sh close`. If the coordinator crashes, `sweep-stale` marks its active record stale after the configured TTL.

## Member result schema

Every lane adapter normalizes to this object:

```yaml
specialist: code-reviewer
status: completed # completed | failed | refused | timed_out
summary: Bounded summary of this member's work.
claims:
  - finding: A concrete claim.
    severity: medium # critical | high | medium | low | info | none
    evidence:
      - path/or/source reference
    confidence: high # high | medium | low
disagreements:
  - Optional explicit disagreement with another claim or premise.
tools_used:
  - Exact tool actually invoked.
artifacts:
  - In-scope non-canonical artifact, if any.
limitations:
  - Missing evidence, unavailable tool, refusal, or scope limitation.
```

Malformed results are coverage gaps, not silently repaired opinions. The coordinator may normalize syntax but may not invent evidence or change a member's substantive verdict.

## Canonical aggregate shape

The one parent response contains:

1. Panel metadata and a member completion table.
2. Consensus findings with contributing specialists.
3. Unique/minority findings with attribution.
4. Conflicts, evidence on each side, and resolution or `unresolved`.
5. Refusals, failures, timeouts, malformed returns, and resulting coverage gaps.
6. Tools and artifacts by member.
7. Overall confidence and next action.

Valid parent statuses include `completed`, `completed_with_gaps`, `needs_human`, and `failed`. Concatenation may appear as an evidence appendix, but it is not the aggregate by itself. Fake unanimity and majority-vote conflict resolution are prohibited.

## Activity protocol

Active records live at:

```text
_state/runtime/lane-activity/<task-id>.json
```

`bin/panel-activity.sh` performs atomic same-directory temporary-write plus rename updates. Records contain the parent task/lane/coordinator state, timestamps, TTL, and member transitions. `close` moves a terminal record into the `archive/` child directory. `sweep-stale` marks abandoned running records `stale` and running/queued members `timed_out`.

The future status UI is a read-only projection of these records; it must never become the activity source of truth.

## Failure semantics

- Spawn failure: mark that member `failed`; continue only if quorum remains possible.
- Tool failure: member reports the failure honestly; the coordinator does not claim tool use.
- Refusal: mark `refused`, surface it, and do not safety-shop through another family.
- Timeout/late return: mark `timed_out`; a late message cannot overwrite the already-published canonical response.
- Quorum impossible: write an honest `failed` or `needs_human` parent response, then archive activity.
- Coordinator crash: leave the active file; a later `sweep-stale` makes the failure visible.
- Outbox write failure: keep/mark activity failed or stale; never let a member publish in the coordinator's place.

