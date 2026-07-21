# Vibe Squad Protocol

Every dispatch is a markdown file. Scripts validate, route, and deliver; they do not replace markdown instructions.

## Task Packet Frontmatter

```yaml
---
id: TASK-YYYY-MM-DD-HHMM-<hash>
run_id: none
from: chrono
to_model: gpt-codex | claude | gemini | kimi
specialist: <canonical-specialist>
source_namespace: coding | security | content | content-engineer | sysmgmt | research | shared
compatibility_namespace: coding | security | content | content-engineer | sysmgmt | research
review_model: gpt-codex | claude | gemini | kimi | none
mandatory_review: true | false
mode: bounty | project | content | maintenance | incident | research | triage | outreach | none
capability: <card slug valid for the mode, e.g. web-app> | none
capability_degradation_ack: <exact validator-derived needs_tool[:reason] | degraded-blueprint> | none
phase: <phase or none>
type: TASK
priority: low | normal | high | urgent
status: new | claimed | in-progress | done | blocked
created: <ISO timestamp>
deadline: <ISO timestamp or none>
write_scope: []
read_context: []
return_artifact: <path>
success_criteria: []
out_of_scope: []
parallel_safe: true | false
direct_lane_work_allowed: false
operator_approved: true | false
model_override_reason: none
parent_msg_id: none
---
```

The dispatcher contains a temporary compatibility bridge for older local packets, but new markdown must use the fields above.

### Optional `capability:` field

`capability:` is **optional**. When set, its value is a capability-card slug valid for the packet's `mode` —
for example `mode: project` with `capability: web-app`. Combined with `mode` it resolves to
`shared/capabilities/<mode>/<card>.md` (`project` + `web-app` → `shared/capabilities/project/web-app.md`); the
slug is the final segment of the card's canonical `id: <mode>/<card>`, and passing the full `<mode>/<card>` id
is equivalent. Omit it (or set `none`) when a packet does not run under a specific card. The card defines the
S0–S7 workflow, `gates`, and `overlays` for that kind of work (see `shared/capabilities/_skeleton.md` +
`shared/capabilities/_format.md`; each mode file carries a `## Capabilities` index of its cards).

**Selects the workflow, never the model lead.** `capability:` selects which validated protocol the work
follows — the card's S0–S7 steps, gates, and overlays. It does **not** choose a model lead and does **not**
override `to_model`. Routing stays per-specialist: `specialist` + `shared/routing.md` +
`shared/specialist-runtime-map.tsv` decide the lane, exactly as without the field (FINAL-PLAN §1 — "optional
`capability:` selects gates/workflow, **never a model lead**; routing stays per-specialist"). A packet may set
`capability:` on any `to_model` lane; the field changes the *protocol*, not the *router*.

**Enforcement level (live).** When `capability:` is present and not `none`, `bin/send-task.sh` requires a strict
slug (or exact `<mode>/<slug>` ID), resolves it only beneath `shared/capabilities/<mode>/`, and calls the canonical
capability validator. A malformed, mode-mismatched, missing, or validator-failing card blocks dispatch. The
dispatcher surfaces the validator-derived state. A `needs_tool` (including a typed reason) or
`degraded-blueprint` snapshot is held unless the packet explicitly carries
`capability_degradation_ack: <exact-derived-state>`; acknowledgement permits the bounded degraded task, it does
not promote the card.

For an allowed capability dispatch, the delivered packet and active-task registry receive an immutable snapshot:
`capability_id`, `capability_card_path`, `capability_card_sha256`, `capability_derived_state`, and
`capability_gates`. These keys are dispatcher-owned and source packets may not pre-populate them. The card's
SHA-256 is computed over the same bytes validated at dispatch. Capability/tool claims in the author packet are
validated **before** `shared/dispatch-toolkit.sh` appends registry-derived status guidance; injected cross-lane
backticks are context, not author claims, and are not fed back through predispatch validation. Registry `no` /
`needs-research` / `catalog-absent` / `needs_tool` states remain hard gates, while a `yes` tool's lane mismatch is
surfaced as a warning rather than blocking a legitimate cross-lane reference.

**Enforcement DESIGN direction (Tier-4 follow-on — NOT built now).** Remaining narrative gates may become hard
stops through a broader machine-enforcement layer, all subscription-free and deferred to a dedicated hardening
task: Claude **hooks** (a `PreToolUse` hook to
enforce a packet's `write_scope` and block an unapproved `git push`; a `Stop`/`PostToolUse` hook to enforce the
two-output Completion Contract so finished work can't settle without its outbox envelope), **`--json-schema` /
`--output-format json`** for machine-checked gate records (impact G1–G4, the Rule-6 rights gate, reconciler
envelopes), and **`--max-budget-usd`** to enforce the metered ceilings each card's `cost_note` already promises.
None of these is active today — treat them as the intended hardening roadmap, not a current guarantee.

## Lifecycle

1. Chrono writes a task body.
2. `scripts/send-task.sh` adds frontmatter from the model map.
3. `bin/send-task.sh` validates safety and writes to `departments/<compatibility_namespace>/inbox/`.
4. Inbox watchers nudge the `to_model` window with the absolute task packet path.
5. The model lead reads the packet and named specialist markdown.
6. The model lead writes the response to the return artifact/outbox.
7. Chrono surfaces the result to the operator.

`source_namespace` selects the specialist markdown. `compatibility_namespace`
selects the mailbox folder. Shared specialists do not have a `departments/shared`
mailbox; Chrono chooses the mailbox namespace that matches the active workflow.

### Dispatcher filesystem threat boundary

The local dispatcher is designed for the squad's trusted, single-user control
plane: Chrono authors packets, `launch-squad.sh` creates the mailbox topology,
and no untrusted or concurrent process may rename or replace `departments/`, a
mailbox directory, or its `inbox/` while dispatch is running.

Within that boundary, `bin/send-task.sh` rejects NUL bytes and non-canonical task
IDs, allowlists every `compatibility_namespace` before using it as a path
component, rejects existing symlinked mailbox components before creation, and
requires the physical inbox to equal the expected directory below the resolved
`VAULT_ROOT`. A symlinked prefix in the configured root itself is allowed (for
example macOS `/tmp` resolving to `/private/tmp`).

The Bash `check → mktemp → copy → rename` sequence is not an atomic
`openat`/`O_NOFOLLOW` security primitive. A hostile local process that can mutate
the mailbox tree between those operations is outside the supported threat model.
If Vibe Squad gains untrusted packet authors, shared filesystem writers, or a
multi-user mailbox, dispatch must move to a directory-descriptor-relative,
no-follow publisher before that environment is supported.

### Dispatcher-pinned verification contract v1

For Project and Bounty, `bin/send-task.sh` owns `author_family`, `verification_contract`, and `verification_contract_sha256`; author packets may not pre-populate them. The author family comes only from the executing `to_model` lane. The dispatcher combines the validated capability snapshot and runtime-map gates, derives `verification-contract/v1`, serializes it as UTF-8 canonical JSON (`sort_keys`, compact separators, no NaN), and stores the lowercase SHA-256 beside the object.

The exact object/hash pair is injected into every dispatched packet and persisted in the locked active registry. A `verification-run/v1` manifest must echo both. The checker trusts in this order: active registry identity under shared lock; registry object validation and recomputed hash; registry lane-to-author-family pin; all packet echoes; then the manifest echo and manifest/contract identities. A mismatch at any layer is `verification_contract_integrity` / `OPERATOR=3`. Same-task registration includes the contract hash in dispatch identity, so a changed contract cannot silently replace the original.

The trace bundle must supply ordered S0–S7 evidence, current plan and canonical artifact-bundle hashes, required verification kinds, different-family plan/deliverable review records and their evidence-file frontmatter, memory recall/usage/record receipts, a complete action log, expected gate decisions, iteration invalidation records, and local delivery evidence. Reviews bind S2 to `plan.sha256` and S5 to `artifact_bundle_sha256`; changed subjects require fresh evidence. Project and Bounty are the only typed v1 profiles.

This is a trusted single-user filesystem contract, not cryptographic attestation. The checker validates reviewer-family, memory, and verification records for schema, file hash, identity, and current-subject binding, but cannot prove which external reviewer or MCP authored the bytes. Live acceptance therefore uses actual independent reviews and actual `chrono-vault` returns. The reconciler preserves and settles task state; it does not independently enforce a completed run's verification spine.

## Delivery Claim Contract

Task execution and response settlement use separate state fields. Registry
`status` remains the completion/review authority; `delivery_state` is the
transport lifecycle `queued → claimed → in-progress → terminal`.

Every new dispatch receives one immutable `delivery_attempt_id` and generation.
Before sending a pane prompt, `bin/nudge-task.sh` obtains a locked authorization
for the oldest nonterminal task on that lane and persists its retry count and
next-attempt timestamp. Redeliveries reuse the same task and attempt IDs, follow
the bounded schedule, and never release a later same-lane task while the head is
claimed or in progress. Watcher startup replays queued inbox files, making a
crash between authorization and pane submission recoverable without an
unbounded loop.

The delivered prompt begins with the mandatory lane action:

```bash
bin/claim-task.sh TASK-ID ATTEMPT-ID
```

That command atomically records both the `claimed` and `in-progress` transitions
under `_state/active-tasks.json.lock`. Repeating the current claim is idempotent;
a stale attempt/generation or a non-head task is rejected. A valid response (or
the explicit work-done-without-envelope backstop) marks delivery `terminal` and
releases the next same-lane task without changing mandatory-review semantics.

Pane submission is only `pane_delivery_attempted`. It proves that the transport
accepted keystrokes, not that the model accepted work. Only the lane-authored
claim receipt may set failover `accepted_at`; therefore pane delivery alone does
not suppress the watchdog's dispatch-ack failure path. A failover generation is
also fenced in the active registry before its packet is submitted, so an older
generation cannot claim after the handoff.

## Completion Contract

Lifecycle step 6 has **two** required outputs, not one. On finishing a task the model lead writes both:

1. the **`return_artifact`** named in the packet, and
2. the **outbox completion envelope** at `departments/<compatibility_namespace>/outbox/<id>-response.md`.

**Before** declaring a task `complete`, apply the **verify-before-claiming-done** discipline (Hard Rule 8): run
the actual verification (commands/tests/re-reads) and confirm the claimed outcome — never emit a `complete`
`status` on an unverified result. On the **Claude lane** this is the invokable `verification-before-completion`
skill (`supported_lanes: claude`; codex/kimi/gemini apply the same discipline via their own means, not this
claude-only skill).

`bin/outbox-watcher.sh` watches for `<id>-response.md` and `scripts/python/registry_reconciler.py` reconciles the active-task registry and nudges Chrono from it. Writing only the `return_artifact` leaves the task `in-flight`: the reconciler's `work-done-no-envelope` path is a **backstop** (it flags settled-but-unenveloped work after a grace period once the lane goes idle), not the primary path. Emitting the envelope is what makes reconciliation instant and deterministic.

The lane derives `<id>` from the packet's `id` field and `<compatibility_namespace>` from the packet's own mailbox path (`departments/<X>/inbox/<id>.md` → `<X>`), which is present for every packet even when the `compatibility_namespace` frontmatter field is omitted.

Envelope schema — frontmatter, then a summary body whose first paragraph the reconciler surfaces:

```markdown
---
id: <id>-response
in_response_to: <id>
from: gpt-codex | claude | gemini | kimi
to: chrono
type: RESULT
status: complete | needs_review | blocked
return_artifact: <the return_artifact path>
capability_card_sha256: <exact dispatched hash> # required only when the packet carries a capability snapshot
---

One-paragraph summary of what you did (the reconciler surfaces this first paragraph).
```

The reconciler keys on the `<id>-response.md` filename and reads `status` (canonicalizing `completed`→`complete`) plus the summary body. For a capability-pinned task, the envelope must echo the exact dispatched
`capability_card_sha256`; a missing or mismatched echo keeps the task open, including before cross-family review
settlement. Reconciliation compares the current card hash separately and records/surfaces
`capability_card_drift`, but drift does not rewrite the pinned ID, hash, derived state, or gates and does not by
itself block a correctly pinned response. Use `needs_review` when the packet sets `mandatory_review: true`, and
`blocked` if the work could not be finished. **Panel/fan-out members never write the envelope — the coordinator
is the sole outbox writer for the parent task.**

## Memory Apply Citations

When recalled memory materially informs a task, cite each consumed note by its stable `mem-…` ID in the response (for example, `Memory applied: mem-a1b2c3d4e5f6`) and retain the associated `recall_id`. Close the apply loop with `record_usage(recall_id, note_id, outcome, source_task)`, using `used`, `not_useful`, or `incorrect` to distinguish memory that helped from memory that did not; never copy private note text or sensitive evidence into public packets.

## Async Rule

Senders do not block on lane-to-lane work. If a response is required, track the task ID and check/surface the outbox result later.

## Mandatory Review Behavior

`mandatory_review: true` is a contract enforced at dispatch time, not auto-firing automation. Specifically:

The shared review-gate that every review-overlay S5 step fires has a two-part **request → receive** discipline,
invokable on the **Claude lane** (`supported_lanes: claude`; codex/kimi/gemini apply the same discipline via
their own means): **`requesting-code-review`** — before handing off, the author confirms the work actually meets
the packet's requirements/scope; **`receiving-code-review`** — findings are weighed on merit (especially when a
comment is unclear or technically questionable) before any change is made. This loop **supplements, never
replaces**, the independent cross-family reviewer, and a claude-only skill is never a card's sole review
mechanism.

- **At dispatch:** `bin/send-task.sh` validates that `review_model` is set when `mandatory_review: true`, and rejects high-safety specialists (per `shared/specialist-runtime-map.tsv`) that don't carry `mandatory_review: true`.
- **Same-family review (specialist's primary lane and reviewer's lane share a model family — e.g., gpt-codex specialist with claude reviewer where the specialist already has Claude available as an in-lane tool):** the specialist is expected to run the review IN-LANE before declaring done. Most current `mandatory_review: true` packets land this way (e.g., gpt-codex/ai-engineer responses commonly include "Mandatory Claude review completed twice").
- **Cross-family review (specialist and reviewer don't share lane access — e.g., claude/architect with gpt-codex reviewer where claude has no native gpt-codex tool):** Chrono dispatches the reviewer manually after the specialist's response lands. There is no auto-fire from the watcher today; Chrono reads the response and decides whether to follow up with a reviewer dispatch.

Operators / specialists writing packets should:

1. Always pair `mandatory_review: true` with a `review_model` that the specialist's lane can actually invoke in-lane. If the lanes don't share a family, expect a follow-up dispatch.
2. Treat `mandatory_review: true` as "Chrono guarantees a reviewer will see this before operator-facing surfacing happens" — not as automation.
3. If a high-safety specialist's response lands without evidence of in-lane review, Chrono is expected to dispatch a reviewer follow-up before treating the response as final.

### Machine-enforced block-settle (implemented)

`scripts/python/registry_reconciler.py` (run by `bin/outbox-watcher.sh` when a response lands) **enforces** the cross-family case so it cannot be silently skipped. A task is *cross-family-review-pending* when its registry entry has `mandatory_review: true`, a `review_model` that is a real lane, and an **actual executing lane** (`to_model`, after dispatch override validation; falling back to the specialist's mapped primary lane) that cannot run that review in-lane. The only in-lane-capable cross-lane pair today is **gpt-codex → claude** (a Codex lane can invoke Claude directly), which is exempt and settles normally as same-family; every other cross-lane pair (for example claude → gpt-codex) is enforced. An indeterminate executing lane fails **closed**.

For a pending task, automatic behavior is deliberately limited to **flag, hold, and surface**:

- the task's own response does not reconcile to `complete`; the registry remains `review-required` and emits one `REVIEW-REQUIRED` queue line per hold/required-lane transition;
- reviewer response files have **no automatic settlement authority**. Their text, frontmatter verdict, filename order, and filesystem timestamps are never parsed to decide registry completion. Malformed, ambiguous, nonterminal, conflicting, or late review files therefore cannot false-settle a task;
- after reading a satisfactory final review and confirming that no blocking finding remains, Chrono explicitly settles the held task under the registry flock:

  ```bash
  python scripts/python/registry_reconciler.py \
    --settle-review TASK-... \
    --review-ref departments/<namespace>/<outbox|archive>/TASK-...-response.md
  ```

  The review path is audit provenance only. The command requires an existing in-vault mailbox response, a held cross-family task, and a landed subject response in `complete` or `needs_review`; it is lock-serialized, idempotent for the same task/reference, rejects conflicting references, records `review_settled_by: chrono-explicit`, and emits one `REVIEW-SETTLED` audit line. Task lanes must not invoke this controller capability themselves. If a review is blocked, incomplete, malformed, or ambiguous, Chrono does not run the command and the task stays open.

To prevent infinite review-of-review regress, a task is exempt from cross-family enforcement only when `write_scope` is the explicit empty list and its specialist is exactly `code-reviewer` or `security-analyst`. Reviewer-role tasks with missing, malformed, or non-empty scope remain gated. Existing lock-serialized registration is unchanged. The `work-done-no-envelope` backstop remains available only when no response candidate exists; a candidate still inside its quiescence window suppresses the backstop, and a candidate arriving after provisional settlement reopens the task until its status can be classified.

Still parked (not implemented): **auto-firing** the reviewer dispatch itself. The reconciler blocks settle and surfaces `REVIEW-REQUIRED`, but a human/Chrono still dispatches the actual review packet. Auto-dispatch from the watcher (detect response landing + lane mismatch → send the reviewer task) remains a future enhancement.
