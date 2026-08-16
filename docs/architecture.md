# Vibe Squad architecture

Vibe Squad is a Markdown-first, board-native multi-model harness. The operator
talks to one coordinator, Chrono. Chrono interprets the request, chooses a
specialist and workflow, assigns write ownership, and decides what must be
reviewed. Small runtime rails then launch isolated workers, validate mechanical
contracts, observe processes, and publish results.

The default dispatch path needs no HTTP service, database, or model proxy. It is
made from Markdown packets, local files, short-lived native CLI processes, and
git worktrees.

## The intelligence boundary

Human and model judgment lives in readable, diffable files:

- Chrono's coordinator instructions
- the Project and Bounty mode documents
- capability cards and specialist briefs
- routing, review, safety, and memory guidance

There are exactly two work modes: [Project](../shared/modes/project.md) and
[Bounty](../shared/modes/bounty.md). Project contains engineering, research,
operations, outreach, and content/media capabilities. Bounty contains authorized
security research. A conversational request or advisory answer does not create a
third mode.

A capability card selects the workflow, gates, and overlays for a task. It never
selects the model. Chrono selects a specialist; the specialist's row in
[`shared/specialist-runtime-map.tsv`](../shared/specialist-runtime-map.tsv)
selects the primary CLI/profile, backup, escalation, and reviewer constraints.
Folder or mailbox names are compatibility storage labels, not model ownership.

Machinery owns facts that should not depend on interpretation: identities,
hashes, scopes, process birth, exit receipts, publication order, and registry
fences. It may validate or record a judgment that Chrono made, but it does not
invent the goal, decomposition, specialist choice, review merit, or acceptance
decision. There is no general workflow engine that replaces the Markdown
instructions.

## Runtime shape

```text
operator
   │
   ▼
Chrono in tmux ── selects mode, capability, specialist, scope, and review
   │
   ▼
Markdown task packet in departments/<namespace>/inbox/
   │
   ▼
detached board supervisor ── one git worktree per attempt
   │
   ▼
fresh codex | claude | gemini | kimi CLI
   │
   ├─ writes declared artifact
   └─ writes response envelope
            │
            ▼
controller validates outside worktree
   │
   ├─ publishes artifact first
   └─ publishes envelope last
            │
            ▼
envelope + fenced receipt publication
   ├─ supervisor / outbox watcher ── registry reconciler ── settlement
   │                                      └─ optional tmux ── attended Chrono pane
   ├─ reconciled registry ── board-notify.sh stdout ── explicit reader
   └─ outbox/queue files ── explicit read ── later reader
```

[`bin/squad`](../bin/squad) is the lifecycle interface. Its launcher creates the
`chrono` coordinator window and a `watchers/status` window. Specialists are not
standing tmux panes or permanent agents: each board dispatch starts a fresh CLI
process and ends it with the attempt. The sidebar and watchers are projections
of the board; they do not control worker execution.

## Native model transport and utility tools

All specialist model inference runs through the provider's native CLI:
`codex`, `claude`, `gemini`, or `kimi`. Codex and Claude use their approved
subscription login paths, Kimi uses its managed login, and Gemini's native CLI
is the explicit API-key exception. Profiles resolve to exact model and effort
settings through
[`shared/registries/profiles.tsv`](../shared/registries/profiles.tsv).

MCP servers are tools, not model transports. They can provide private memory,
research, browser automation, code intelligence, sequential thinking, or
governed media operations. They never proxy a specialist call to Codex, Claude,
Gemini, or Kimi. Media and other service APIs may consume their own provider
credits when an approved Project capability invokes them; that is separate from
the model lane.

Each CLI owns its utility registration, and available tools differ by lane.
[`model-lanes/lane-capabilities.tsv`](../model-lanes/lane-capabilities.tsv) is
the capability boundary; a globally installed tool is not assumed available to
every worker. The private Markdown memory vault also lives outside the public
worktree; see the [Chrono Vault guide](../plugins/chrono-vault/README.md).

## Dispatch and publication

Chrono calls [`scripts/send-task.sh`](../scripts/send-task.sh), which derives
packet frontmatter from the specialist map and hands the packet to
[`bin/send-task.sh`](../bin/send-task.sh). The hardened dispatcher validates the
mode, optional capability card, declared read/write scope, lane/profile, safety
fields, and immutable verification contract. It registers a fenced delivery
attempt, writes the packet atomically to the appropriate inbox, builds a trusted
launch context, and detaches
[`bin/board-supervisor.sh`](../bin/board-supervisor.sh).

The supervisor provisions an attempt-specific worktree, checks the canonical
specialist and lane adapter, then executes the selected native CLI with only its
packet and allowed context. The worker writes two outputs inside that worktree:
the declared `return_artifact` and a small completion envelope. Controller code
reads and validates both from outside the worker environment. Only validated
output is promoted, with the artifact published before the envelope. The
envelope is the outbox/filesystem watcher's publication marker, not a semantic
completion verdict or a receipt for a headless consumer, so observers never
treat a half-published result as complete.

[`scripts/python/registry_reconciler.py`](../scripts/python/registry_reconciler.py)
settles the delivery record from a valid response or a matching terminal
receipt. Completion observation is explicit: the default watcher fleet starts the
consolidated outbox watcher, whose best-effort live recipient is only the Chrono
tmux pane (`bin/launch-squad.sh:217-231`); a headless controller must separately
start [`bin/board-notify.sh`](../bin/board-notify.sh) and consume the target-state
lines it writes to stdout (`bin/board-notify.sh:38-55`). That stdout observer has
no persisted cursor or downtime replay and does not report `review-required`
holds, which the registry classifies as live (`scripts/python/chrono_state/registry.py:35-63`).
Outbox and queue files are
durable inputs for a later explicit read, not delivery by existence. Chrono then
decides whether to accept, manually author an ordinary continuation packet, send
for review, or surface the result to the operator.

The canonical per-path recipient, timing, and unattended behavior is the
[Completion recipient contract](../shared/protocol.md#completion-recipient-contract).
That table is authoritative if this topology summary ever drifts.

## The process/receipt fact seam

Runtime status is observed rather than copied from a label. Every board attempt
has a descriptor under `_state/board-dispatch/` binding task ID, attempt ID,
generation, PID, process group, process-start identity, command hash, launch
context, log, and receipt path. A dashboard card is `running` only when that
descriptor and context agree, the exact process identity is still live, and no
matching terminal receipt exists.

At termination, the controller publishes a fenced receipt containing the same
attempt identity, a hash of the descriptor, completion time, and terminal
outcome. A reused PID, stale generation, renamed file, mismatched command, or
unbound receipt is rejected rather than guessed around. This logic is shared by
[`scripts/python/board_process_truth.py`](../scripts/python/board_process_truth.py),
the board snapshot, cancellation, and reconciliation paths.

This seam is deliberately narrow. A process receipt proves what happened to an
attempt; it does not prove that the artifact is correct, that a review passed,
or that the engagement should be accepted. Those remain separate evidence and
judgment decisions.

## Review, authorization, and memory

Review requirements are pinned at dispatch. When independent review is
required, the runtime map and dispatcher constrain the reviewer to a different
provider family; an equal execution/review lane is invalid and fails closed;
reviewers are read-only unless Chrono serializes a later write task. A
`mandatory_review` flag is a contract to obtain review, not permission for the
worker to approve itself.

Consequential effects remain operator-gated policy, including deletion,
credential changes, public release, paid media, live outreach, and production
mutation. The ordinary worker path denies their declared category tokens at
admission; it does not ask for approval during a later tool call. `read_scope`
and `write_scope` are declarative while the worker runs, with `write_scope`
enforced when committed changes are integrated. Deletion has a separate,
file-exact Git-integration gate. The exact boundary and its residuals live in
[`shared/protocol.md`](../shared/protocol.md#held-category-authority-and-logical-scopes).

Recall and recording use the private Chrono Vault as a utility surface. Memory
can inform a task, but recalled notes are evidence to re-check, not instructions
or proof of current state. Public code, private memory, credentials, runtime
mailboxes, and generated state remain separate; see
[Private configuration](private-config.md).

## Optional support daemon

[`daemon/main.py`](../daemon/main.py) is an optional, explicitly started FastAPI
support process. It exposes health, bearer-protected read-only task views, an
event stream, utility-MCP/catalog calls, and a separate Gemini API summarizer.
`bin/squad up` does not start it, it has no task-submission route, and the board
does not depend on it. Its metered summarizer is not one of the four specialist
model lanes.

The dormant automatic-failover subsystem is retired. Operational failures surface
through the ordinary receipt and reconciliation path. If the operator chooses the
mapped backup, Chrono manually authors a new ordinary board packet; no flag,
sentinel, watcher, or daemon launches it.

## Canonical references

| Concern | Source |
|---|---|
| Coordinator behavior | [`chrono/CLAUDE.md`](../chrono/CLAUDE.md) |
| Modes and capabilities | [`shared/modes/`](../shared/modes/) and [`shared/capabilities/`](../shared/capabilities/) |
| Packet, delivery, and completion contract | [`shared/protocol.md`](../shared/protocol.md) |
| Routing decisions | [`shared/routing.md`](../shared/routing.md) |
| Specialist-to-runtime mapping | [`shared/specialist-runtime-map.tsv`](../shared/specialist-runtime-map.tsv) |
| CLI capabilities | [`model-lanes/lane-capabilities.tsv`](../model-lanes/lane-capabilities.tsv) |
| Session lifecycle | [`shared/lifecycle.md`](../shared/lifecycle.md) |
| Specialist briefs | [`departments/`](../departments/) and [`shared/specialists/`](../shared/specialists/) |
