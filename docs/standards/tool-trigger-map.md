# The Tool/Skill TRIGGER map — when to reach for what

Canonical, dispatch-invariant reference. Lives at exactly one level and is pointed to from
root `CLAUDE.md` (`## Canonical Sources`); it is **never** copied into the specialist briefs.
Placement is argued in the note at the foot of this file, from Part 0 of
`docs/standards/instruction-layer-standard-and-rubric.md`.

The layer already says these capabilities *exist*; this file says **when reaching for one is the
right move**, so a capability is used by a checkable trigger rather than by inclination.

**Reading rule.** Every entry states an observable **TRIGGER** you can evaluate *right now* — a
count, a state, an about-to-do — plus a **Not when** boundary naming the near-miss that should
*not* fire it. Scan for the row whose `Trigger` matches your *now*; if none matches, no reach is
indicated. This map answers **when**. It never claims a tool is live — availability on your lane
is your L4 capability projection's to confirm in the live runtime (Hard Rule 9).

---

## The map

### When you are stuck

**Reach for:** `superpowers:systematic-debugging`
- **Trigger (fires when):** you have hit **two consecutive blockers on the same objective** — the
  worker two-blocker stop condition. Its **canonical definition and required response live at
  `shared/protocol.md` § Two-blocker stop** (operator-ratified); that section owns the rule, and this
  row is only the tool-reach view of it.
- **Not when:** the *first* failure of a fresh approach — one blocker is just a blocker; or a
  failure on a *different* objective (that resets the count).
- **Then:** STOP patching. Read the validator / the literal error / the production path before
  touching code again. Form one hypothesis, prove it, then fix. A third blind variant is the named
  failure mode, not progress.
- **Availability:** claude-lane skill; confirm in your runtime. Off-lane, apply the discipline manually.

### When you are about to build or design something

**Reach for:** `superpowers:brainstorming`
- **Trigger (fires when):** you are about to enter plan mode, or the request is "let's build /
  design / add X" and the shape is not yet pinned — more than one reasonable design exists and none
  is agreed.
- **Not when:** the task packet already pins scope, interface, and acceptance. **A scoped board
  specialist packet is not a brainstorm** — this fires mostly for Chrono and operator-facing
  "let's build X" turns, rarely for a dispatched worker.
- **Then:** explore intent / requirements / design *before* writing a plan or code.

**Reach for:** `superpowers:test-driven-development`
- **Trigger (fires when):** you are about to write implementation code for a feature or bugfix whose
  output is checkable.
- **Not when:** a pure spike/exploration, or a non-code deliverable (a design doc, this map).
- **Then:** write the failing test first; let it drive the implementation.

### When a decision has many moving parts

**Reach for:** `sequential-thinking` MCP
- **Trigger (fires when):** a decision depends on **3+ interacting constraints whose deduction ORDER
  matters**, and you cannot hold the whole chain correct in one pass — e.g. a placement that must
  satisfy invariance AND no-duplication AND a validator pin simultaneously.
- **Not when:** a linear task, or a multi-step task whose steps do **not** interact — those you just
  do (and batch the independent ones into one round-trip). Step count alone is not the trigger;
  *interaction* is.
- **Then:** externalise the reasoning stepwise so an ordering error becomes visible instead of silent.
- **Availability:** MCP; confirm in runtime. On Kimi, MCP is lead-brokered (subagents don't inherit it).

### When you are about to assert an external fact

**Reach for:** the research arsenal — `perplexity_search`, `xai_search`,
`firecrawl_scrape|crawl|parse`, `arxiv_search` (documented in `shared/tool-catalog.md`).
- **Trigger (fires when):** you are about to put a **load-bearing external fact** into the
  deliverable — a version number, an API contract, a vendor claim, a "current best practice", a CVE,
  a paper result — that you cannot verify from the repo or your own context, **and being wrong would
  change the deliverable.** Also the **Hard-Rule-8 grounding gate:** any citation or provider claim
  that will appear in output must be grounded by a live retrieval, never asserted from memory.
- **Not when:** the fact is already in the repo (read it — the repo is source of truth), or it is
  not load-bearing (do not burn a metered call on trivia), or you are exploring freely (fine, but
  label it unverified rather than citing it).
- **Then:** pick by fact-type — `arxiv_search` for papers, `perplexity_search`/`xai_search` for
  current web/news, `firecrawl_*` for a specific page/site — and cite the result.
- **Availability:** metered keys; confirm via the L4 projection and apply the task's
  budget/authorization gate before spending. `yes` in a registry is availability, not permission to spend.

#### Search availability and fallback

Run one live probe before concluding a search capability is unavailable; prior-session results and packet boilerplate are not current evidence. Absence from the callable runtime schema is an availability error: report the capability gap and use only the task-approved fallback. If a dedicated search route errors on a live call, use the approved generic search fallback when one exists, and report `tools_used` honestly for each call.

### When you might already know the answer / just learned something durable

**Reach for:** `chrono-vault` `recall` / `record`
- **Trigger — recall (fires when):** you are about to spend real effort re-deriving something the
  squad may already have hit — a recurring gotcha, a prior technique, a lane quirk. The smell is
  "haven't we seen this before?".
- **Trigger — record (fires when):** you just learned a **durable, generalisable** fact — a
  technique, a gotcha, a resolved failure mode — that a future task would waste time rediscovering.
- **Not when:** **the task's `memory_aperture` closes it** (`none`/`cold` without focus). Memory is
  never a task gate — if the aperture is closed, skip both silently and do not treat a 0-result
  recall as a signal. Also not when the fact is one-shot target trivia (record the *technique*, not
  the target) or already lives in the repo (do not duplicate source of truth).
- **Then:** recall *before* deriving; record the generalised lesson *after*.
- **Availability:** governed by `memory_aperture` on the packet.

### When you are about to claim a lane/specialist can do something

**Reach for:** the capability cards (`shared/capabilities/<mode>/<card>.md`)
- **Trigger (fires when):** a routing / architecture / GO decision is about to **rest on a
  capability** — you are planning around "this lane can do X". Hard Rule 9: declared ≠ delivered ≠
  actual; only *actual* counts.
- **Not when:** you are only reading and no decision rests on it, or the capability is already proven
  by a live receipt this session.
- **Then:** read the card for the S0–S7 workflow and gates, **and require a live probe/receipt**
  before treating the capability as available. Agreement between config files that share an origin
  is not proof.

### When you are about to say "done" / hand off

**Reach for:** `superpowers:verification-before-completion`
- **Trigger (fires when):** you are about to write `status: complete`, or claim "fixed / passing / done".
- **Not when:** your status is `needs_review`, `needs_human`, or `blocked` — you are not claiming
  done, so the gate does not fire (though evidence still helps).
- **Then:** run the actual verification, read the real output, *then* claim (Hard Rule 8).
  Claude-lane skill; other lanes apply the discipline by their own means.

**Reach for:** `superpowers:requesting-code-review` / `receiving-code-review`
- **Trigger — request (fires when):** you are finishing a task carrying `mandatory_review: true`, or
  about to merge/hand off — confirm the work actually meets the packet's scope before handoff.
- **Trigger — receive (fires when):** a review has landed and you are about to act on its findings —
  weigh them on merit (especially an unclear or technically questionable one) before changing anything.
- **Not when:** a routine internal step with no handoff and no review gate.
- **Note:** the in-lane discipline that *supplements* the independent cross-family reviewer Chrono
  routes; it never replaces it.

### When you are on an authorized offensive/bounty engagement

**Reach for:** `systematic-attacking` (before acting/submitting) and `systematic-bug-hunting` (at the bench).
- **Trigger (fires when):** `mode: bounty`, or any authorized offensive-security scope — before the
  first offensive action, and before any submission.
- **Not when:** no authorized verified scope exists (then the iron law is *stop*, not *reach*).
- **Then:** follow the two iron laws — never act outside authorized verified scope; no finding
  without a reproduced, negative-controlled, intrinsic-impact proof.

---

## Placement note (why this file, at this level)

Run Part 0's invariance test on a representative row — *across what set is this fact constant?*
"Two consecutive blockers on the same objective → reach for systematic-debugging" does not change
between roles, namespaces, model families, or dispatches. Only **availability** changes by lane, and
availability is already owned by L4's capability projection. So the trigger is **L1-invariant**:
*"would this be equally true if I deleted any single namespace, role, or lane?"* — yes.

L1 root `CLAUDE.md` is policy + pointers only and, by its own "Never" rule, must not name a specific
tool, skill, or flag — and this map names many. So the map cannot be inlined at L1; per the
standard's master principle it becomes **one canonical file that L1 points to**. It lives here in
`docs/standards/`, co-located with the rubric that defines its acceptance test and — being tracked,
unlike git-ignored `_state/` — reachable inside every board worktree (the F-GAP delivery lesson).
`shared/tool-trigger-map.md`, sibling to `shared/routing.md`/`shared/protocol.md`, is an equally
valid home; moving it there is a one-line follow-on if the operator prefers the `shared/` location.

**Not copied into the briefs.** The map is *content*, invariant across roles, so it lives once and is
pointed to. Contrast the `generic_pointer_line` repeated in every brief (pinned by
`scripts/python/validate_capability_homes.py`): that is a *pointer*, repeated on purpose. Duplicating
a pointer is infrastructure; duplicating content is the duplication defect the audits keep finding.
