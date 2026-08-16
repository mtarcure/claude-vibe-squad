# The Dreaming System — protocol

A dream pass is one worker, reading this file, looking back over what the squad
actually did, and writing one runtime journal. Everything below is judgment a
worker applies; the runner only hands this protocol to the board on a schedule.

If you are that worker: read this whole file, then do exactly what it says. You
need nothing else.

---

## 1. The one rule that outranks the rest

**A published dream is exactly one journal under `_state/dream-logs/`.**

The task packet sets both `write_scope` and `return_artifact` to that exact file
and uses memory aperture `none`. The controller commits only declared-scope
residue (`scripts/python/worktree_isolation.py:1311-1414`) and rejects committed
out-of-scope paths before integration (`:1548-1555`). A worker can dirty its
isolated worktree, but those bytes cannot land on the canonical branch.

There is no propose or apply mode. If an observation deserves action, name it in
`## Candidates`; the operator may commission an ordinary reviewed task later.

If you find yourself editing a specialist brief, a routing table, or a script
because a dream told you to: stop. You are no longer dreaming, you are doing
un-reviewed work under a schedule that nobody is watching.

---

## 2. Passes

| Pass | When | Window |
|---|---|---|
| light | nightly | trailing 1 day |
| deep | Sunday | trailing 7 days |

The light pass is a skim: count the inputs, note anything that repeats, stop. It
should be short. A light journal that runs to three pages means you analysed
instead of skimmed.

The deep pass uses the broader seven-day window. Either pass may report a pattern
only when it finds three independent instances inside its own window.

`bin/dream.sh` picks the pass from the day of week (Sunday → deep) unless you
override it with `SQUAD_DREAM_PASS`.

---

## 3. Inputs

Read these five. Nothing else is in scope, and you do not need permission to read
any of them — but you may only read, and you skip anything that looks like a
secret rather than redacting it in place.

| Input | Where it actually lives | What you are looking for |
|---|---|---|
| operator corrections | `git log` on the default branch — messages containing `fix`, `revert`, `actually`, and any commit that undoes a recent one | the squad did a thing, a human undid it |
| cross-namespace handoff failures | `departments/*/outbox/*-response.md` with `status:` of `blocked` / `needs_human`, and `## NEEDS FROM CHRONO` sections | work that stopped at a boundary |
| dispatch outcomes | `_state/dispatch-log.jsonl`, `_state/active-tasks.json` | tasks that failed, retried, or never settled |
| memory churn | `_state/cleanup-logs/*-brain.md` | facts written then removed, or contradicted |
| mode-run metadata | `_state/nightly-failures/*.log`, `_state/morning-briefs/*.md` | phases that fail quietly and repeatedly |

Two of these directories are runtime state that only exists on a live host. In a
fresh clone or a board worktree they are absent — that is not an error. Record
the count as `0 (not present)` and move on. A dream that cannot see an input says
so; it never infers what the input would have said.

---

## 4. Evidence bar

These are the rules that keep a dream from becoming a generator of plausible
sentences. They are strict on purpose.

1. **Every observation cites at least one path, commit, or task id.** An
   observation without a citation is deleted, not softened. "Dispatch feels
   flaky" is not an observation; "`TASK-…-2610` and `TASK-…-2600` both settled
   `blocked` with `failure_class: request_validation`" is.
2. **Three instances minimum before you call it a pattern.** Two is a
   coincidence. One is an anecdote. If you have two, write it under *Friction*
   and let a later pass find the third.
3. **Count first, interpret second.** The journal opens with counts. If the
   counts are small, the interpretation section should be small too.
4. **Agreement between two files that were copied from each other is not
   corroboration.** Check whether your three instances have three independent
   origins.
5. **"Nothing this pass" is a correct and common result.** Write it plainly. Do
   not pad a journal to look productive; a padded journal trains the next reader
   to skim.

---

## 5. Journal format — write exactly these headings

The journal is not free-form. The `## 💭 Dream insights` block of
`bin/morning-brief.sh` (`:208-225`) parses it: it lifts
everything under `## Notable Patterns` into the morning brief and reads the
single line **after** `## Verdict`. Rename or reorder those two headings and the
brief silently shows nothing.

Write to the path the packet gives you as `return_artifact` — normally
`_state/dream-logs/<YYYY-MM-DD>.md`.

```markdown
# Dream journal — <YYYY-MM-DD> (<light|deep>, shadow)

## Inputs scanned
- operator corrections: <n> (<path or "not present">)
- handoff failures: <n> (<path>)
- dispatch outcomes: <n> (<path>)
- memory churn: <n> (<path>)
- mode-run metadata: <n> (<path>)

## Notable Patterns
- <pattern — cited, ≥3 instances. Or the single line "- (none this pass)">

## Friction
- <things that cost time but are not yet patterns — cited>

## Candidates
- <skill_candidate | role_patch | routing_rule_change | … — named, NOT applied>

## No-action notes
- <what you looked at and deliberately did nothing about, and why>

## Privacy
- <what you skipped, and why>

## Verdict
<ONE line: "clear", "watch: <thing>", or "escalate: <thing>">
```

`## Notable Patterns` and `## Verdict` are load-bearing. The rest are for the
human reading the file directly, so they can change if a later pass has a better
idea.

---

## 6. Who runs it

The runtime map (`shared/specialist-runtime-map.tsv:35`) binds `memory-curator`
to **claude** as primary and **gpt-codex** as reviewer. The packet requests that
review with `mandatory_review: true`; Chrono must dispatch it before delivery.
The flag holds the result for review but does not launch the reviewer itself.

---

## 7. Running one by hand

```sh
bash bin/dream.sh                      # pass chosen by weekday, shadow mode
SQUAD_DREAM_PASS=deep bash bin/dream.sh
bash bin/dream.sh --dry-run
```

For an isolated audit, `SQUAD_DREAM_STATE_DIR` may name a nested `_state/...`
directory; traversal, absolute paths, and shell metacharacters are rejected.

The runner renders a task packet from `shared/dreaming/packet-template.md` and
hands it to `bin/send-task.sh`. It does not read inputs, score anything, or
decide what a pattern is — all of that is the worker's job, and the worker's
instructions are this file.
