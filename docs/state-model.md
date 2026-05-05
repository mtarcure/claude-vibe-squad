# State Model

Vibe Squad has one runtime truth model. Historical handoffs and roadmap files are context, not live state.

## Live Truth Order

1. `_state/active-tasks.json`
2. `chrono/current.md`
3. `departments/*/current.md`
4. Matching `departments/*/outbox/TASK-*-response.md` files

If these disagree, treat it as drift. Run:

```bash
squad status
bash bin/sweep-active.sh
```

`squad status` flags contradictions instead of blending them into a guessed story.

## Runtime Directories

Operator-local runtime state belongs in `_state/` and the department mailbox directories:

- `departments/*/inbox/`
- `departments/*/active/`
- `departments/*/outbox/`
- `departments/*/archive/`
- `_state/tmux-logs/`
- `_state/doctor-logs/`
- `_state/cleanup-logs/`

Public repos should not track mailbox contents. The launcher recreates missing mailbox directories on startup.

## Historical Context

`docs/roadmap.md` is a planning queue. Completed handoffs, specs, and plans are cleanup debt once durable decisions have been folded into canonical docs.
