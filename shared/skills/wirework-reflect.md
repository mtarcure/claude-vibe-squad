---
name: wirework-reflect
status: authored
description: Use when a task or phase has just finished — compare what actually happened against what was planned and capture the one durable lesson to chrono-vault, so the next run does not rediscover the same trap.
---

# Wirework Reflect

Compare the planned outcome against the actual one and capture what is worth carrying forward. The
value is not the comparison — it is that the lesson lands somewhere a future run will *find* it. A
lesson noted in a response envelope is read once by one reader and then buried; a lesson in durable
memory is recalled by whoever hits the same situation next.

This runs **after** the work, is **advisory**, and **never blocks completion**.

## When to use
- A task, phase, or dispatched packet has just completed — including when it completed successfully.
- Something diverged from the plan, in either direction. An overshoot teaches as much as a miss.
- A tool, lane, or technique behaved differently from what was expected.

## Steps
1. **State the planned outcome and the actual one side by side**, both concrete. "Ship the port and pass
   CI" against "ported nine files; one validator was already failing before the change". Vague inputs
   produce a lesson too general to ever match a future situation.
2. **Classify the divergence** as one of: **matched**, **partial**, **missed**, or **exceeded**. Keeping
   `exceeded` as its own bucket matters — a run that went unexpectedly well carries a reusable technique,
   and collapsing it into "matched" throws that away.
3. **Extract exactly one lesson, in one line.** Not a summary of the task: the transferable thing. The
   test is whether it would change a future run's behaviour. "The port went fine" changes nothing;
   "adding a name to the skill catalog also requires a registry row or capability validation fails"
   changes the next attempt.
4. **Check it is durable, not situational.** Record the technique, the gotcha, the tool behaviour — not
   the target and not this task's narrative. A lesson that only makes sense with this task's context
   attached is a status update wearing a lesson's clothes.
5. **Check the repo does not already record it.** Code structure, git history, and documented conventions
   are already written down. Memory is for what cannot be re-derived by reading the repo.
6. **Record it** (below), then continue. Do not gate anything on the write succeeding.

## Recording (chrono-vault)

After the task or phase completes, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="learning", fields={"title": "reflect: <task or phase>", "body": "planned=<...>; actual=<...>; verdict=<matched|partial|missed|exceeded>; lesson=<one line>; delta=<what diverged and why>", "target": "<component or target>", "attack_class": "none", "source_task": "<task-id>"})`.

Use `note_type="attempt"` or `"finding"` with a real `attack_class` where the reflection concerns
security work. A memory error is logged in one line and never blocks the work — the reflection still
stands in the artifact, it is simply not persisted, and that degradation is stated rather than hidden.

## Failure modes
- **Status-update-as-lesson** — recording what happened instead of what to do differently.
- **Success blindness** — reflecting only on failures, so techniques that worked are never captured.
- **Target-specific memory** — recording facts about one target rather than a reusable technique.
- **Duplicating the repo** — writing down what the code, history, or conventions already state.
- **Gating on memory** — treating a failed write as a task failure. It is telemetry.
- **Reflex reflection** — emitting a note after every step regardless of whether anything was learned.
  Nothing diverged and nothing was learned is a legitimate outcome; say so and record nothing.

## Acceptance
- Planned and actual outcomes are both stated concretely, and the divergence is classified.
- The lesson is one line, transferable, and would change a future run's behaviour.
- The lesson is durable technique rather than this task's narrative or target-specific fact.
- The record call was made at most once, and any failure was noted in one line without blocking.
- Where nothing was learned, that is stated rather than padded into a note.
