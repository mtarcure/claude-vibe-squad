# Vibe Squad Protocol

Every dispatch is a markdown file. Scripts validate, route, and deliver; they do not replace markdown instructions. `docs/state-model.md` stages the V4 state boundary; this file remains the live actor and wire protocol.

## Task Packet Frontmatter

```yaml
---
id: TASK-YYYY-MM-DD-HHMM-<hash>
run_id: none
from: chrono
to_model: gpt-codex | claude | gemini | kimi
specialist: <canonical-specialist>
source_namespace: coding | security | content | sysmgmt | research | shared
compatibility_namespace: coding | security | content | sysmgmt | research
review_model: gpt-codex | claude | gemini | kimi | none
mandatory_review: true | false
mode: bounty | project
memory_aperture: rich | focused | cold | pool_blind | none
memory_focus: <exact canonical note target; required only with focused> | none
capability: <card slug valid for the mode, e.g. web-app> | none
capability_degradation_ack: <exact validator-derived needs_tool[:reason] | degraded-blueprint> | none
phase: <phase or none>
type: TASK
priority: low | normal | high | urgent
status: new | claimed | in-progress | done | blocked
created: <ISO timestamp>
deadline: <ISO timestamp or none>
write_scope: []
read_scope: []
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

The dispatcher contains a temporary compatibility bridge for older local packets, but new V4 Markdown uses exactly `project` or `bounty`. Legacy packets carrying `content`, `maintenance`, `incident`, `research`, `triage`, `outreach`, `none`, or `advisory` remain V3 compatibility input only; acceptance by that bridge does not make them a V4 engagement.

### V4 engagement boundary

The Markdown packet remains the live board wire format. The controller projects its identity, lane, declared
scope, workspace, and memory aperture into authenticated launch authority; the worker cannot rewrite those
authenticated fields. That is an integrity guarantee over the declaration, not an action-time filesystem
boundary. `memory_aperture` is optional for compatibility and defaults fail-closed to `cold`. `focused`
requires one `memory_focus`, which is matched exactly against canonical note `target`. Other apertures reject a
focus field. Chrono authors these fields; the operator does not manage an orchestration DSL.
The guarantee is scoped to the controller-launched lane and existing vault APIs; it does not claim containment against a hostile same-UID process reading private Markdown directly.

Continuation is manual on the live rail: Chrono authors another ordinary board packet and includes a bounded
Markdown capsule plus predecessor reference. No automatic resume/continuation caller is claimed here.

`operator_approved` remains legacy dispatch consent. It is never blanket permission for publication,
deletion, spending, account changes, or another consequential action; those decisions stay explicitly scoped.

### Held-category authority and logical scopes

The live worker model **denies declared held-category authority at admission rather than asking for consent at
action time**. `bin/board-supervisor.sh:872-880` requires authenticated `operator_gates` to equal the
controller's full `HELD_CATEGORIES` set (`scripts/python/held_action_gate.py:49`) and rejects any overlap between
that set and the worker's declared `action_scope`. This keeps all **nine** held-category tokens outside ordinary
worker launch authority; `scripts/python/tests/test_golive_integration.py:312-342` is the positive control that
the deny actually fires, with a same-payload negative control above it. It does not prove that every tool capable
of causing the same real-world effect is absent: `held_action_gate.authorize()` has no production caller, so there
is no general per-action token check or prompt. Hard Rule 6 remains the policy Chrono must apply when authoring
and routing work.

Two caveats about that admission check, because its shape is easy to overstate. First, `action_scope` has exactly
one production producer — a hardcoded literal at `scripts/python/dispatch_context_builder.py:1177` — and no
consumer anywhere reads it to grant a capability; it is type-checked, sealed into the runtime envelope, and
otherwise inert. The overlap check therefore catches a controller-side bug that began emitting a held token; it is
not a barrier an adversary is pushing against. Second, the cardinal "nine" in the paragraph above is prose and is
**not** covered by a validator. `scripts/python/tests/test_held_action_gate.py:42-73` pins exact equality among
the constant, the `operator_gate` vocabulary in `shared/lane-policy.tsv`, and the enumerated list in Hard Rule 6 of
`CLAUDE.md` — those three cannot drift. A numeral written here can, and this one already did: it read "ten", which
was **correct on the day it was written** and went stale hours later when `default_cutover` left the constant. An
unguarded number does not have to be authored wrong to become wrong.

`read_scope` and `write_scope` are logical packet and integration contracts. The default trusted worker can read
and write elsewhere in its attempt worktree. Controller integration commits only in-scope residue, rejects
committed out-of-scope paths, and leaves other dirty paths isolated. The strict Seatbelt worker boundary is an
opt-in path for untrusted-input work; the default trusted path launches on the host after a containment canary.
A sandbox protects the host from a worker; the held-category policy protects the operator from consequential
effects. They answer different threat models and neither should be described as the other.

Deletion has an additional machine gate at Git integration. The default authorized-delete set is empty. A
non-empty set comes only from the controller's authenticated verification contract, requires
`operator_approved: true`, is frozen to literal tracked files at the worker's base commit, must be inside
`write_scope`, and is checked against every committed `D` record before integration. This gate covers tracked
file deletion delivered through worker Git history; it is not a general action-time filesystem delete guard.

On the maintainer installation, the local Git remote named `public` has `pushurl = DISABLED`. That prevents an
ordinary `git push public ...` from this checkout, but it is local Git configuration outside the repository and
therefore is not a fresh-clone or server-side guarantee. Other public-release routes remain policy-held.

The provider CLI is not the approval boundary. Claude, Gemini, and Kimi trusted launches explicitly suppress
their provider consent prompts; Codex runs non-interactively with its workspace-write sandbox, and every worker
child receives a closed stdin. No provider prompt substitutes for Hard Rule 6 or for the Git deletion gate.

### Optional `capability:` field

`capability:` is **optional**. When set, its value is a capability-card slug valid for the packet's `mode` —
for example `mode: project` with `capability: web-app`. Combined with `mode` it resolves to
`shared/capabilities/<mode>/<card>.md` (`project` + `web-app` → `shared/capabilities/project/web-app.md`); the
slug is the final segment of the card's canonical `id: <mode>/<card>`, and passing the full `<mode>/<card>` id
is equivalent. Omit it (or set `none`) when a packet does not run under a specific card. The card defines the
S0–S7 workflow, `gates`, and `overlays` for that kind of work (see `shared/capabilities/_skeleton.md` +
`shared/capabilities/_format.md`; each mode file carries a `## Capabilities` index of its cards).

**Selects the workflow, never the CLI lane.** `capability:` selects which validated protocol the work
follows — the card's S0–S7 steps, gates, and overlays. It does **not** choose a model/CLI and does **not**
override `to_model`. Routing stays per-specialist: `specialist` + `shared/routing.md` +
`shared/specialist-runtime-map.tsv` decide the lane, exactly as without the field. A packet may set
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
4. `bin/send-task.sh` registers the task under the shared registry lock, advances `delivery_state` to `in-progress`, builds a signed launch context with `scripts/python/dispatch_context_builder.py build`, and detaches `bin/board-supervisor.sh detached-launch`.
5. The supervisor provisions a private git worktree under `_state/board-worktrees/<attempt-id>/` and execs a **fresh, capability-scoped CLI** for the packet's lane; that CLI reads the packet and the named specialist markdown.
6. The CLI writes the return artifact and the outbox completion envelope **inside its worktree**. The supervisor validates both, publishes the artifact first and the envelope last into the repo, and runs `scripts/python/registry_reconciler.py` to settle the registry.
7. Chrono surfaces the result to the operator after an explicit observation path reaches it; artifact publication and registry settlement alone have no human/controller recipient.

Steps 4–6 are the **board-native** transport (`bin/send-task.sh:48` defaults `SQUAD_DISPATCH_MODE=board`); it is
detailed in Delivery Contract below. There is no persistent model-lead window: the per-model lane windows were
retired at the Phase-3 cutover (`bin/launch-squad.sh:624-628`), and each dispatch spawns its own CLI instead.

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

The trace bundle must supply ordered S0–S7 evidence, current plan and canonical artifact-bundle hashes, required verification kinds, different-family plan/deliverable review records and their evidence-file frontmatter, memory recall/record receipts (usage receipts are optional telemetry), a complete action log, expected gate decisions, iteration invalidation records, and local delivery evidence. Reviews bind S2 to `plan.sha256` and S5 to `artifact_bundle_sha256`; changed subjects require fresh evidence. Project and Bounty are the only typed v1 work modes.

This is a trusted single-user filesystem contract, not cryptographic attestation. The checker validates reviewer-family, memory, and verification records for schema, file hash, identity, and current-subject binding, but cannot prove which external reviewer or MCP authored the bytes. Live acceptance therefore uses actual independent reviews and actual `chrono-vault` returns. The reconciler preserves and settles task state; it does not independently enforce a completed run's verification spine.

## Delivery Contract

Task execution and response settlement use separate state fields. Registry
`status` remains the completion/review authority; `delivery_state` is the
transport lifecycle `queued → claimed → in-progress → terminal`. **This state
machine is live and unchanged**; only the mechanism that drives it moved from
tmux keystrokes to the board supervisor.

Explicit lifecycle closure may batch already-judged tasks: `--close-task TASK-A TASK-B ... --close-reason "<what was verified for every task>"` validates the full batch before one atomic registry update, never substitutes for per-task judgment, and never batch-approves reviews.

Every new dispatch receives one immutable `delivery_attempt_id` and generation,
minted when `bin/send-task.sh` registers the task under `_state/active-tasks.json.lock`.

### Board delivery (the live rail)

`bin/send-task.sh` performs the claim itself, inline and under the registry lock, immediately before it
detaches the supervisor. It re-reads the entry, refuses to proceed unless the task is still `in-flight` /
`queued` with a matching `delivery_attempt_id` and generation, sets `delivery_state: in-progress`, stamps
`claimed_at` / `started_at` and the attempt counters, and appends a `board-claimed` plus an `in-progress`
event (`transport: board-supervisor`) to `delivery_history`. There is no keystroke step and **no
lane-authored claim** on this rail: the dispatcher is the claimant.

The supervisor then runs detached; the exact descriptor-backed Stop path remains its controller backstop,
while each fresh lane launch enforces the authenticated `budgets.timeout_seconds`. Cleanup uncertainty holds
the supervisor live for that exact Stop path and never publishes a terminal receipt. It provisions a per-attempt git worktree
(`scripts/python/worktree_isolation.py::WorktreePool.provision`, branch + directory keyed to the attempt ID),
verifies that the canonical role file, lane overlay, lane executable, and profile-derived
`selected_model_sha256` all match the authenticated authority, and execs the lane CLI.

Completion is validated before it is published. `dispatch_context_builder.py::prepare_worktree_outputs`
reads the return artifact and the response envelope **out of the worktree**, rejects structurally malformed
flat frontmatter or an empty summary, coerces the worker's status intent, and reconstructs all published
identity/pin fields from the launch authority rather than trusting or requiring the worker's copies
(`scripts/python/dispatch_context_builder.py:1600-1636,1736-1759,1968-2052`). After validating both
destinations, `publish_prepared_worktree_outputs` atomically writes the artifact
first and the envelope last, because the envelope is the outbox/filesystem watcher's publication marker.
It is not a semantic verdict or a headless-recipient receipt. In-scope code the
CLI edited is committed by the controller (`commit_worker_residue`) and integrated onto `SQUAD_BASE_BRANCH`
(`integrate_worktree_commits`); a specialist CLI edits files but never commits them itself. On successful
terminal settlement the supervisor unlinks the inbox packet it launched from, so a board task leaves no
orphan behind.

Any failure — context build, delivery start, or a supervisor status other than `launched` — routes to
`dispatch_context_builder.py blocked`, which publishes a canonical `status: blocked` artifact **and**
envelope, after which `bin/registry-reconciler.sh --task-id` settles the entry. A board dispatch that dies
therefore closes as `blocked` instead of sitting `in-flight` forever.

A dispatch that dies on one of the narrow paths that publish no blocked envelope at all cannot strand its
scope either. `registry_reconciler.py::never_launched_reason` releases a task that **registered but never
launched**: still `delivery_state: queued` with zero attempts, no `claimed_at`/`started_at`, no legacy
assigned-worker fence,
no response candidate, no return artifact, and no attempt worktree, for longer than `NEVER_LAUNCHED_GRACE`
(default 120s; the real register→launch window is sub-second). Such a task settles to `cancelled` with a
`never_launched_reason`, which drops it out of `in-flight` and therefore frees its `write_scope` for immediate
re-dispatch. Every clause must hold independently, so a task that is merely slow, carries a legacy worker
assignment, or left any residue is never auto-cancelled.

`registry_reconciler.py::mark_delivery_terminal` is the only writer of the `terminal` state. It fires from a
landed response (`response:<status>`), from a fenced board receipt
(`_state/board-dispatch/<task-id>.<attempt-id>.receipt.json`, accepted only when its `task_id`, `attempt_id`,
and generation match the registry entry — `terminal_board_receipt`), from the work-done-no-envelope backstop,
from a legacy assigned-worker lease rejection, or from swarm cancellation. Mandatory-review semantics are
unchanged by any of these.

### Retired: pane-keystroke task dispatch

`bin/send-task.sh` accepts only `SQUAD_DISPATCH_MODE=board`; `pane` is rejected before packet publication.
The legacy nudge script, receipt sender, inbox watcher, and pane `tmux send-keys` **task-dispatch** path are
removed. This does not remove the separate completion nudge: the reconciler and `bin/outbox-watcher.sh`
still make best-effort `tmux send-keys` calls to the Chrono pane. Their narrower recipient contract is stated
below. `bin/claim-task.sh` and legacy registry delivery fields remain compatibility data but have no pane
transport caller. The old scheduler, authorization/retry, and generation-advance commands are removed.
Automatic failover redispatch is unsupported; a later backup packet requires an explicit operator/Chrono
decision. `pane_delivery_attempted` and failover `accepted_at` are historical vocabulary only.

## Completion Contract

Lifecycle step 6 has **two** required outputs, not one. On finishing a task the spawned specialist CLI writes both:

1. the **`return_artifact`** named in the packet, and
2. the **outbox completion envelope** at `departments/<compatibility_namespace>/outbox/<id>-response.md`.

That means two logical outputs and, for ordinary prepared packets, two distinct files. The convenience
wrapper `scripts/send-task.sh` is a compatibility exception: it authors `return_artifact` equal to the outbox
envelope path (`scripts/send-task.sh:99-101`), so one physical envelope-shaped file serves both roles and no
separate work artifact is delivered. The publisher writes both logical outputs to that same destination
idempotently when their bytes match (`scripts/python/dispatch_context_builder.py:2341-2353`). Do not describe
that wrapper as producing a separate artifact.

**Before** declaring a task `complete`, apply the **verify-before-claiming-done** discipline (Hard Rule 8): run
the actual verification (commands/tests/re-reads) and confirm the claimed outcome — never emit a `complete`
`status` on an unverified result. On the **Claude lane** this is the invokable `verification-before-completion`
skill (`supported_lanes: claude`; codex/kimi/gemini apply the same discipline via their own means, not this
claude-only skill).

On the board rail the detached supervisor invokes `scripts/python/registry_reconciler.py` for its task after
the attempt and fenced terminal receipt finalize (`bin/board-supervisor.sh:263-278`);
`bin/outbox-watcher.sh` can invoke the same reconciler earlier if it observes `<id>-response.md` during that
window (`bin/outbox-watcher.sh:511-533`). A racing reconciliation may consume the envelope, but once the V2
receipt exists it deliberately preempts the response candidate and becomes settlement input
(`scripts/python/registry_reconciler.py:3257-3265,3545-3641`). The envelope is therefore the atomic publication
marker, not a guarantee that it was the settlement input and not delivery to a person or headless controller.

Writing only the `return_artifact` on the board rail fails completion prevalidation because the bridge reads
both sources before publishing either (`scripts/python/dispatch_context_builder.py:2010-2028`; the failure is
caught at `bin/board-supervisor.sh:2758-2779`). The detached wrapper then routes it through canonical blocked
publication (`bin/board-supervisor.sh:243-275`; `scripts/python/dispatch_context_builder.py:2382-2479`). On the
V3 compatibility rail, artifact-only completion instead depends on the preserved `work-done-no-envelope`
backstop. That weaker backstop can only use its artifact-grace branch now that persistent per-model windows are
retired (`scripts/python/registry_reconciler.py:3678-3725`). The fenced board receipt is the board rail's safety
net when no worker-authored envelope was promoted. The staged V4 contract does not treat artifact presence,
path, or `mtime` as settlement; migration of that runtime seam remains open.

The specialist CLI derives `<id>` from the packet's `id` field and `<compatibility_namespace>` from the packet's own mailbox path (`departments/<X>/inbox/<id>.md` → `<X>`), which is present for every packet even when the `compatibility_namespace` frontmatter field is omitted.

Envelope schema — frontmatter, then a summary body whose first paragraph the reconciler surfaces:

```markdown
---
id: <id>-response
in_response_to: <id>
from: gpt-codex | claude | gemini | kimi
to: chrono
type: RESULT
status: complete | needs_review | needs_human | blocked
return_artifact: <the return_artifact path>
capability_card_sha256: <exact dispatched hash> # required only when the packet carries a capability snapshot
---

One-paragraph summary of what you did (the reconciler surfaces this first paragraph).
```

### Completion recipient contract

**Canonical recipient semantics live in this table.** “Published,” “stored,” “reconciled,” “tmux accepted,”
and “written to stdout” are observable states; none means “delivered” without the named recipient. Machine
settlement and human/controller receipt are separate facts.

| path | who receives it, and when | when nobody is there | implementation evidence |
|---|---|---|---|
| **Ordinary single-task response envelope as machine publication marker** | The output bridge receives the worker envelope at attempt finalization, validates its structure/summary, reconstructs canonical metadata from launch authority, and publishes it after the return artifact. A racing watcher/reconciler may consume that outbox candidate; otherwise the later fenced V2 receipt preempts it for settlement. This path's recipients are controller machinery and any explicit file reader, not a person by default. | Publication and machine settlement can finish with no human or headless controller present. A valid envelope alone gives neither one the result; one of the observation paths below must still be attended. | `scripts/python/dispatch_context_builder.py:1600-1636,1736-1759,1968-2052,2298-2353`; `bin/board-supervisor.sh:263-278`; `scripts/python/registry_reconciler.py:1055-1104,3257-3265,3445-3641` |
| **Outbox file as stored content** | A later human/controller receives the content only when it explicitly opens or polls `departments/<namespace>/outbox/<id>-response.md`; a running outbox watcher sees it on its replay scan or next filesystem event. The file is available after the controller's artifact-first, envelope-last publication. | If nobody opens, polls, or watches the outbox, nobody receives the content. The file remains stored; existence is not delivery. | `scripts/python/dispatch_context_builder.py:2341-2353`; `bin/outbox-watcher.sh:629-652` |
| **Chrono tmux-pane nudge** | Only the live `${SQUAD_SESSION}:chrono` pane is targeted, immediately after a completion event is reconciled or observed. An attended human/controller at that pane is the intended live recipient. | If the session/window is absent, the code sends nothing. If the pane exists but is unattended, tmux success proves only that the keystrokes and Enter were accepted; it does not prove that anyone read or acted. The reconciler persists the event's notification key before attempting the nudge, so a missing/failed pane is not retried merely because it later appears. The file and registry state remain for later inspection, and reconciler-emitted events also have a durable queue record, but there is no live recipient. | `scripts/python/registry_reconciler.py:263-328,392-424`; `bin/outbox-watcher.sh:126-171,561-626` |
| **Registry-watch stdout (`bin/board-notify.sh`)** | A headless polling controller receives one line only if it explicitly starts this long-lived process **and consumes its stdout**. On the next poll (default interval: one second) it prints `task=<id> status=<registry-state> artifact=yes\|no` for a previously open task, or a newly appearing task, whose latest snapshot is in the notifier's deferred/terminal target set. These are not all successful completions: blocked, timed-out, review/rework, cancellation, and no-envelope states are also targets. `artifact=yes\|no` is an advisory file-presence lookup, not validation or receipt; because the notifier discards registry metadata and falls back to finding a task packet, a normal post-cleanup result can report `artifact=no` even when its promoted artifact exists. | There is no persisted cursor or downtime replay. If the notifier is not running, stdout has no reader, or the target state was already present when the initial snapshot was taken, nobody receives an event. `review-required` remains classified as live and produces no line merely because the lane reached that hold. The default squad launcher starts `outbox-watcher.sh` and the reconcile sweep, not this notifier. | `bin/board-notify.sh:17-55`; `scripts/python/chrono_state/registry.py:35-63`; `bin/launch-squad.sh:217-231`; packet cleanup/lookup: `bin/board-supervisor.sh:2938-2953`, `scripts/python/registry_reconciler.py:1828-1865` |
| **Durable Chrono queue record** | The reconciler appends `_state/chrono-queue.md` before attempting the pane nudge. A later session/rotation reader receives that record only when it explicitly reads the file. | With no later reader it is durable storage, not a notification. Queue persistence does not make an unattended pane delivered and does not feed `board-notify.sh`. | `scripts/python/registry_reconciler.py:239-250,392-400` |
| **Dispatching shell/session** | The send command returns after detaching the supervisor and prints a polling waiter that the caller may explicitly attach. It receives no completion callback merely because it launched the task. | If the caller does not run that waiter, consume `board-notify.sh`, inspect files, or attach to the pane, nothing re-enters or wakes the dispatching session. | `bin/send-task.sh:2495-2501,2548-2560` |
| **Legacy `RESP-*` reply** | The outbox watcher can send its filename/path context to the Chrono pane on a filesystem event. | Unlike TASK events, it has no registry-driven queue append. If the pane is absent or unattended, only the reply file remains for an explicit later read. | `bin/outbox-watcher.sh:488-491,557-626` |

These paths are complementary, not a fan-out guarantee. In particular, the pane path does not reach a
headless controller, and the registry watcher does not inject into tmux, parse envelopes, queue a durable
receipt, or settle tasks.
Call a completion “delivered” only when the named consumer above actually receives it; otherwise name the
weaker fact (`published`, `reconciled`, `queued`, `tmux accepted`, or `stdout emitted`).

A swarm parent is an explicit exception to the ordinary worker-envelope row: the reconciler/controller writes
the frozen parent artifact first and parent envelope second, without the worker output bridge
(`scripts/python/registry_reconciler.py:2935-2957,3090-3091`). That records a parent review hold; it does not by
itself promise a queue, pane, or headless event. Until an explicit consumer observes its file or registry state,
the honest claim is “stored,” not “delivered.”

The reconciler keys on the `<id>-response.md` filename and reads `status` (canonicalizing `completed`→`complete`) plus the summary body. **Panel/fan-out members never write the envelope — the coordinator
is the sole outbox writer for the parent task.**

#### The V3-compatible response status enum (one enum, four surfaces)

There is exactly one V3 response status enum. `shared/dispatch-toolkit.sh` injects it, the promotion bridge
(`dispatch_context_builder.py`) normalizes onto it, `bin/outbox-watcher.sh` presents it, and
`registry_reconciler.py::SETTLEABLE_STATUSES` settles it. Anything outside the enum canonicalizes to `""` and
fails closed — the task stays open rather than settling on a guess.

| status | who may author it | meaning |
|---|---|---|
| `complete` | worker | Finished **and verified** (Hard Rule 8). Nothing is owed. |
| `needs_review` | worker | Finished, but a reviewer/Chrono must look before it counts. Required when the packet sets `mandatory_review: true`; also used to surface a `## NEEDS FROM CHRONO`. |
| `needs_human` | worker | **Stopped pending an operator decision** — an approval, an operator gate, or the injected no-delete rule. Strictly stronger than `needs_review`: it is a question, not a deliverable. |
| `blocked` | worker | Could not proceed; no usable result. |
| `cancelled` | **controller only** | Chrono, or the reconciler's never-launched release, cancelled the task. A worker may never author this. |

`completed` is accepted as a legacy alias for `complete`. `review-required` and `work-done-no-envelope` are
reconciler **registry** states, not response statuses, and are never valid in an envelope.

#### Declared-tool failures are a `needs_tool` report, not a status

An adapter authorises tools for a lane; authorised is not callable. When a worker **attempts** a declared
tool and it fails — an auth gate, an MCP that never connected, a name absent from the live runtime — it
reports the failure so Chrono can reconcile *declared* capability against *actual* (Hard Rule 9). This reuses
the existing `needs_tool` capability-degradation vocabulary (`verification_contract.py`
`capability.derived_state`; the `needs_tool` dispatch gate above) as the **name of a report field**, and adds
**no** new envelope status — a fifth `status:` value would canonicalize to `""` and strand the task.

The worker appends a `## needs_tool` section to the response body, one entry per failed tool carrying the
tool name **as the adapter declared it**, the **literal invocation** attempted, and the **verbatim error**.
The envelope `status` is set by what happened to the *deliverable*, and the report rides alongside it: a
worker that finished via a fallback keeps `complete`/`needs_review` and attaches the report; a worker for
which the tool was essential and blocking sets `status: blocked` and attaches the report naming it. The
distinction between "noticed a gap" and "the gap stopped me" is thus carried by the existing status, never by
new vocabulary. `shared/dispatch-toolkit.sh` injects this rule into the universal Completion contract, so it
reaches every dispatch. It catches only tools a worker attempted; a declared tool never tried stays
unverified, which a periodic sweep — not this mechanism — would have to close.

#### Reconciliation pin/fence echoes

For a capability-pinned task, the envelope must echo the exact dispatched
`capability_card_sha256`; a missing or mismatched echo keeps the task open, including before cross-family review
settlement. Reconciliation compares the current card hash separately and records/surfaces
`capability_card_drift`, but drift does not rewrite the pinned ID, hash, derived state, or gates and does not by
itself block a correctly pinned response. A swarm **member** must likewise echo `swarm_spec_sha256`, and a
legacy assigned-worker task must echo its full delivery fence (`delivery_attempt_id`, `delivery_generation`,
`delivery_worker_id`, `worker_epoch`, `lease_generation`, `delivery_lane`, plus `replica_index` / `member_id`
when assigned).

On the board rail a worker does not have to hand-write these. `dispatch_context_builder.py` snapshots every
required pin/fence into the launch authority as `reconciliation_echo` — from the packet frontmatter and the
locked registry, **never from worker metadata** — and output promotion re-emits them into the published
envelope. A worker-authored value for one of these keys is discarded and replaced by the authority's, so a
stale or forged echo cannot settle a task.

### Surfacing needs to Chrono (`## NEEDS FROM CHRONO`)

A spawned worker is **not** an orchestrator. It must not spawn sub-tasks, launch a model CLI
(`claude`/`codex`/`gemini`/`kimi`), run `send-task.sh`, or coordinate with another specialist directly — its
sandbox denies model-CLI exec (the attempt fails the launch → exit 75), and cross-worker coordination is
Chrono's sole responsibility (root CLAUDE.md: Chrono is the only controller).

When a task needs something beyond the worker's scope mid-flight — a live canary/probe that requires launching
a CLI, another specialist's help, a wider write scope, a follow-up dispatch, or it is blocked on a dependency —
the worker does the work it *can* do and adds a **`## NEEDS FROM CHRONO`** section to its response body listing
exactly what it needs, returning `status: needs_review` (or `blocked` if it cannot proceed). Chrono reads
`## NEEDS FROM CHRONO` on every landed response and orchestrates it (runs the canary outside the sandbox,
dispatches the other specialist, widens scope, chains the follow-up). `shared/dispatch-toolkit.sh` appends this
rule to every dispatched brief, so it holds regardless of the per-packet body.

#### Two-blocker stop (operator-ratified)

If you hit **two consecutive blockers on the same objective** — a fix bounced, or two attempts at the same
target failed even for what looked like two different reasons — **stop retrying.** A third blind variant is not
work; it is noise, and it is the named failure mode. Read the validator / the literal error / the production
path, then either (a) proceed on the evidence you now have, or (b) return `status: blocked` (or `needs_review`
with a `## NEEDS FROM CHRONO`) whose body carries the two failures as evidence: what you tried, the **verbatim**
errors, and the hypothesis they point to. Retrying past two on one objective without new evidence is itself the
failure Chrono needs to see. (A fresh objective, or the first failure of a fresh approach, resets the count —
one blocker is just a blocker.)

This uses the existing `blocked` status; it invents no new vocabulary. It is distinct from a `## needs_tool`
report (a capability-degradation **field**, not a status — see above): when one of the two blockers is a dead
declared tool, set the status by what happened to the deliverable and attach **both** the two-blocker evidence
and the `## needs_tool` entry.

## Memory Apply Citations

When recalled memory materially informs a task, cite each consumed note by its stable `mem-…` ID in the response (for example, `Memory applied: mem-a1b2c3d4e5f6`) and retain the associated `recall_id`. Apply-feedback is optional best-effort telemetry, never a settlement gate: the loop-closing signal is captured passively by `plugins/chrono-vault/autocapture.py` (invoked by `bin/outbox-watcher.sh` when a response lands), not by a mandated per-task call, and a failed or skipped memory call must never affect task status. `record_usage(recall_id, note_id, outcome, source_task)` remains available as an opt-in tool — reserve explicit calls for high-value events: a note materially changed a decision (`used`), was clearly irrelevant (`not_useful`), or appears incorrect (`incorrect`). Never copy private note text or sensitive evidence into public packets.

## Async Rule

Senders do not block on lane-to-lane work. If a response is required, track the task ID and check/surface the outbox result later.

The staged V4 state model keeps questions separate from process status. Until P7 wires a real consumer,
`needs_human` and `## NEEDS FROM CHRONO` remain the live V3 compatibility surface described above.

## Mandatory Review Behavior

`mandatory_review: true` is a contract enforced at dispatch time, not auto-firing automation. Specifically:

### When `mandatory_review: true` is warranted — the four-trigger gate (operator-ratified 2026-08-11)

This is a **packet-authoring gate**: it binds when the packet is written, not when the work lands.
Set `mandatory_review: true` **only when one of these holds:**

1. **Blast radius** — the change touches the dispatch rail, credentials, capability projection,
   approval gates, or the publication path.
2. **An adversarial claim** — "cannot be bypassed", "fails closed", "nothing can route around it";
   the author already tried everything they thought of, so a second mind is not a double-check but
   the only check.
3. **A measurement that decides something** — counts, coverage, parity.
4. **Architecture** — a design decision with multi-release consequences.

Otherwise Chrono verifies and closes, recording gates-green, diff-within-scope, and any number
reproduced with one command.

**Why it is a gate and not a default.** The flag is free to set and costs a full lane to discharge,
so an unscoped habit of setting it forms a backlog. Calibration on 2026-08-11: of seven reviews, six
changed something material (two REJECTs, a severity flip, a paper-enforcer hole, a 675-line
arithmetic error, a stream-merge defect), while 23 tasks that closed without review bought nothing —
the flag earns its cost only on the four triggers above.

The shared review-gate that every review-overlay S5 step fires has a two-part **request → receive** discipline,
invokable on the **Claude lane** (`supported_lanes: claude`; codex/kimi/gemini apply the same discipline via
their own means): **`requesting-code-review`** — before handing off, the author confirms the work actually meets
the packet's requirements/scope; **`receiving-code-review`** — findings are weighed on merit (especially when a
comment is unclear or technically questionable) before any change is made. This loop **supplements, never
replaces**, the independent cross-family reviewer, and a claude-only skill is never a card's sole review
mechanism.

- **At dispatch:** `bin/send-task.sh` requires a `review_model` from a different provider family whenever `mandatory_review: true`; equal execution/review lanes are rejected for every review class, including `standard`. It also rejects high-safety specialists (per `shared/specialist-runtime-map.tsv`) that lack mandatory review.
- **Distinct-family review only:** Chrono routes a separate reviewer packet after the specialist's response lands. Same-lane self-review may improve the work, but it never satisfies `mandatory_review`. There is no auto-fire from the watcher; Chrono manually authors the reviewer packet.

Operators / specialists writing packets should:

1. Always pair `mandatory_review: true` with a `review_model` from a different provider family and expect a separate reviewer dispatch.
2. Treat `mandatory_review: true` as "Chrono guarantees a reviewer will see this before operator-facing surfacing happens" — not as automation.
3. If a high-safety specialist's response lands without the required review, Chrono is expected to dispatch a reviewer follow-up before treating the response as final.

### Machine-enforced block-settle (implemented)

`scripts/python/registry_reconciler.py` (invoked directly after detached board finalization, and also by
`bin/outbox-watcher.sh` when it observes a response) **enforces** the cross-family case so it cannot be silently
skipped. A task is *cross-family-review-pending* when its registry entry has `mandatory_review: true`. Its actual
execution lane comes from `to_model` (falling back to the mapped primary lane), and its review lane comes from
`review_model`. Every valid distinct-lane pair, including **gpt-codex → claude**, is held for explicit
settlement. Missing, unknown, or equal execution/review lanes fail closed as an invalid mandatory-review
contract; an author response cannot settle them.

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

To prevent infinite review-of-review regress, a task may skip a second review only after its mandatory-review binding has already passed distinct-family anti-affinity and `write_scope` is the explicit empty list with specialist `code-reviewer`, `security-analyst`, or `skeptic`. Reviewer-role tasks with an equal/missing review lane or malformed/non-empty scope remain gated. Existing lock-serialized registration is unchanged. The `work-done-no-envelope` backstop remains available only when no response candidate exists; a candidate still inside its quiescence window suppresses the backstop, and a candidate arriving after provisional settlement reopens the task until its status can be classified.

Reviewer dispatch is deliberately controller-authored: the reconciler only blocks settlement and surfaces `REVIEW-REQUIRED`; Chrono manually writes the ordinary board review packet.
