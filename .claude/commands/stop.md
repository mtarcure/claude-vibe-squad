# /stop

Gracefully close the Vibe Squad tmux session from inside Chrono.

Run:

```bash
bash ~/Obsidian-Claude-Vibe-Squad/bin/squad-stop.sh
```

Behavior:

- asks Chrono to update `chrono/current.md` and Lead `current.md` files
- writes only an ignored transient shutdown summary under `_state/shutdown-summaries/`
- does not write `docs/handoffs/`
- cleans mode-spawned browser profiles, never the operator's persistent Chrome
- kills the `squad` tmux session

Use this when the operator says `/stop`, `/close`, `/shutdown`, "close the system", or "stop the squad".
