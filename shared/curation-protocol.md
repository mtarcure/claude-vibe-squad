# Curation Protocol

What Chrono does with `_state/curation-queue.jsonl` (Task 9's demotion queue) at a session boundary. Spec §10. Cites `shared/memory-discipline.md` rule 3 (resolve contradictions through lifecycle state, never by deleting) — this protocol is that rule applied to the one queue that feeds it.

---

## 1. Trigger and read path

At a session boundary, run `bin/curation-review.sh --since <last review>` and read its rendered output. That script is a renderer only — it groups the raw queue by `note_id` and shows each one's flag count, reasons, and the timestamp of its most recent flag. It has no opinion and takes no action. Everything below is Chrono's judgment, applied after reading that output, never the script's.

**Use `--since`.** The queue is append-only and nothing is ever acknowledged or archived, so a bare `bin/curation-review.sh` re-renders every flag ever recorded — including every one already dismissed under rule 3. `--since` takes an ISO-8601 UTC timestamp or date and shows only what was flagged at or after it; pass the moment of the previous review. It prints a distinct "nothing new" line when there are older flags but no newer ones, so an empty result is never confused with an empty queue. Rows written before flags carried a `ts` are shown regardless and marked `undated`: unknown age is not known-old, and hiding them would lose the backlog. Run the bare form when you want the whole standing backlog.

**The test:** if a note's status changed and the only thing that ran was `bin/curation-review.sh`, that is a bug in the script, not a feature.

## 2. A flag is a lead, not a verdict

`not_useful` and `incorrect` are usage outcomes from one worker on one task — measured at 27 and 5 samples respectively against 218 `used` (spec §8). A single flag on a note means "go look again," not "this is wrong." Before acting on any note in the queue, re-verify its claim the same way `shared/memory-discipline.md` rule 4 requires for any memory: read the file, grep the symbol, run the command. The flag tells you where to look; it is not the evidence.

## 3. What curation keeps

For each flagged `note_id`, after re-verification, Chrono may:

- **Merge** — two notes describing the same fact; keep one, supersede the other with `set_status(..., "superseded", supersedes=<keeper>)`.
- **Repair attribution** — the note is correct but mis-scoped (wrong target/component/source_task); write a corrected note and supersede the original. Never edit a published note's body in place — `shared/memory-discipline.md` rule 3 applies here too.
- **Supersede** — the note was right when written and is now stale; a corrected note replaces it via the same compare-and-swap path.
- **Invalidate** — re-verification shows the note's claim is false. Only here, and only after re-verification, does Chrono call `set_status(id, "invalidated", reason, expected_revision)`. This is the one path in the whole loop that may set `invalidated`, and it always requires a passed review — a flag alone is never sufficient (spec §8's asymmetry with promotion, which also requires a passed review).
- **Dismiss** — re-verification shows the note is still correct; the flag was a bad read, not a bad note. No status change. The flag stays in the queue's history (the queue is append-only, see rule 5) but needs no further action — `--since` is what keeps it from being re-read at every subsequent boundary.

## 4. What curation lost, on purpose

Curation does not promote, and **`used` on its own still promotes nothing.** Spec §8's objection stands as written: promoting on `used` alone — 87% of observed outcomes — would entrench whatever the ranker already surfaces and never lift the notes it cannot reach. If a future reviewer is tempted to add "and if a note gets N `used` flags, bump its rank" here: **do not.** That is a design change belonging to promotion (Stage 1, event-driven on a passed review), not to curation, and needs the operator.

The operator has since made exactly that call, and it did not weaken this rule. Since 2026-08-17 promotion requires **both** signals: a worker reported the note `used`, **and** the task that used it passed review. Neither alone moves a note. `used` is the per-note half — without it, a passing review promoted every note recall happened to return, which is spec §8's objection restated one step weaker. The passed review is the half that says the work the note informed was actually right, and it is the half curation must never supply.

## 5. Queue growth is expected; a stalled queue is not an outage

`bin/curation-review.sh` never rotates, archives, or clears the queue file — it only reads it, and `--since` (rule 1) is a read filter, not a cursor the script stores. Curation stalling was, twice before (2026-07-25), a silent three-week outage because promotion and curation were coupled: when curation stopped, so did everything downstream of it. This design decouples them. **If curation stalls again, the result is a growing queue and a correspondingly noisier ranking — not an outage.** Promotion keeps running regardless. Do not "fix" a stalled queue by wiring promotion back into curation; that recreates the exact coupling this design removed.

## 6. Nothing here is a sweep

Curation review happens at a session boundary because Chrono is present to exercise judgment, not on a timer. A cron job that auto-invalidates flagged notes reintroduces exactly the terminal-on-thin-evidence failure rule 2 exists to prevent — see `shared/lifecycle.md` rule "Event handlers, never sweeps."
