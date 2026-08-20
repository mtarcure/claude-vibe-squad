# The launchd daemon

The LaunchAgent `com.vibesquad.daemon` is **optional**. `bin/squad up` runs
without it, says so once, and continues (`bin/launch-squad.sh:123-133`):

```text
NOTICE: the optional launchd daemon is not installed — continuing without it.
```

`launchd/` holds *templates*, not installable plists. `bin/install-routines.sh`
renders and installs them.

## What it adds, and what you lose without it

The daemon is a local FastAPI process on `127.0.0.1:9876` (`daemon/main.py`).
Exactly two things call it, and they are the whole of what it buys:

| Consumer | Endpoint | Without the daemon |
|---|---|---|
| `bin/vs-lane-status.sh` → tmux status bar | `GET /tasks` | the bar reads `● daemon offline`; per-lane task capsules stop updating |
| the HTTP tool bridge in `plugins/chrono-recon/README.md` | `POST /mcp/<server>/<tool>` | that documented `curl` path is unavailable; the MCP servers themselves are unaffected |

The daemon also still serves `POST /summarize`. Nothing in the repository calls
it: its only caller was `scripts/python/weekly_review_runner.py`, deleted
2026-08-17 with the `com.vibesquad.weekly-review` job it belonged to. The route
is live and reachable by hand, and it buys the install nothing.

Nothing else opens a connection to it. Board dispatch, worktree isolation, the
outbox watcher, the reconciliation sweep, `bin/send-task.sh`, private memory,
`bin/squad doctor` and the Chrono coordinator all run identically with it
absent — the daemon's own file watcher (`daemon/watcher.py`) watches
`daemon/state/outbox`, which is **not** the `departments/*/outbox` tree that
`bin/outbox-watcher.sh` drives the board from.

The degradation is announced, never silent: the launcher names it at startup and
the status bar keeps saying `offline` for as long as it is.

## Install

```bash
bash bin/install-routines.sh
```

That installs the daemon plus the optional routines — `com.claudevibesquad.nightly`
and `com.vibesquad.dream`. The authoritative list
is `OPTIONAL_AGENTS` in `bin/install-routines.sh`; the other install docs point
here instead of restating it. To install only the daemon:

```bash
bash bin/install-routines.sh --daemon-only
```

To see exactly what it would do first:

```bash
bash bin/install-routines.sh --dry-run
```

`--dry-run` renders every template, resolves its tokens, and runs `plutil` on the
result without writing or loading anything.

## Verify

```bash
bash bin/install-routines.sh --status
```

```text
  LABEL                                  PLIST      LAUNCHD    ROLE
  com.vibesquad.daemon                   installed  loaded     required by 'squad up'
  com.claudevibesquad.nightly            installed  loaded     optional
  com.vibesquad.dream                    installed  loaded     optional
```

`installed` **and** `loaded` is what a working daemon looks like. Neither is a
launch gate any more: `bin/squad up` starts whether or not this label appears at
all. (The `ROLE` column still prints `required by 'squad up'`; that string lives
in `bin/install-routines.sh` and is now stale.)

**Absent is fine; broken is not.** Once a plist *is* installed, `bin/squad up`
holds it to the same standard as before and stops the launch for any of these,
because each one can only be reached by someone who did install a daemon and
needs to know theirs is wrong:

- the label is loaded from a **different** plist than this checkout manages
- the installed plist still carries an unrendered `__TOKEN__`
- the installed plist fails `plutil -lint`
- `launchctl bootstrap` ran and the job is still not registered afterwards

Only "no plist at all" is the ordinary, non-blocking answer.

## What the installer does, in order

For each agent:

1. **Render** `launchd/<label>.plist`, substituting `__VAULT_ROOT__` and
   `__HOME__` with absolute paths.
2. **Reject unresolved tokens.** If anything matching `__NAME__` survives, the
   install stops. `bin/launch-squad.sh:135` applies the same rule and would
   refuse to bootstrap the plist, so failing here gives you the error at install
   time instead of at launch time.
3. **Validate** with `plutil -lint`.
4. **Install atomically.** The rendered file is written inside the target
   directory and then renamed over the destination, so no reader ever sees a
   partially written plist.
5. **Bootstrap** into `gui/$(id -u)` and **verify by observation** with
   `launchctl print`, rather than trusting the bootstrap exit code.

### Both tokens are always substituted

Even templates that only *use* `__VAULT_ROOT__` are rendered for `__HOME__` too.
The daemon template's own instruction comment contains the literal string
`__HOME__`, and the launcher's token check scans the whole file, comments
included. Substituting only `__VAULT_ROOT__` produces a plist that passes
`plutil` and is then rejected at launch:

```text
ERROR: installed daemon plist still contains a template token: …/com.vibesquad.daemon.plist
```

## What it refuses to do

**It will not overwrite a plist that differs from the template.** An installed
plist may carry your edits, so a difference stops the install:

```text
  ✗ installed plist differs from the rendered template: …/com.vibesquad.daemon.plist
    Re-run with --force to replace it, or diff it first:
```

Re-run with `--force` once you have looked at the difference. Re-running when
nothing changed is a no-op and reports `already installed and identical`.

**It will not bootstrap over a label loaded from a different file.** launchd is
addressed by label, not by path, so a label can already be registered from some
other installation. The installer compares the path `launchctl print` reports
against the plist it manages, and stops rather than silently displacing it:

```text
  ✗ com.vibesquad.daemon is already loaded from a DIFFERENT plist
      loaded: <another-users-home>/Library/LaunchAgents/com.vibesquad.daemon.plist
      wanted: $HOME/Library/LaunchAgents/com.vibesquad.daemon.plist
```

`--status` shows this state as `foreign`. It is reported as neither `loaded` nor
`not loaded`, because it is *another* installation's state — counting it as
`loaded` would credit this install with something it did not do.

## Uninstall

```bash
launchctl bootout gui/$(id -u)/com.vibesquad.daemon
rm ~/Library/LaunchAgents/com.vibesquad.daemon.plist
```

Removing it is a supported end state, not a broken install. The next `bin/squad
up` prints the absent-daemon notice and launches; you lose the two things listed
in [What it adds](#what-it-adds-and-what-you-lose-without-it) and nothing else.
Remove the plist as well as booting the label out — a loaded label whose file is
gone still answers `launchctl print`, which is why the launcher checks the path
launchd reports rather than just asking whether the label is known.

## Troubleshooting

**`bootstrap failed (rc=5)` / `Input/output error`** — launchd rejected the job.
This also occurs when the install runs inside a sandbox that blocks launchd IPC;
the plist is still installed and valid, and `--status` will show
`installed / not loaded`. Inspect with `launchctl print gui/$(id -u)/<label>`.

**`launchctl unavailable`** — the plists are installed but nothing is loaded.
The installer reports this as a degraded step rather than a success.

**Installing without loading.** Set `SQUAD_INSTALL_NO_BOOTSTRAP=1` to render,
validate, and install the plists while skipping `launchctl` entirely.

**Installing somewhere else.** `SQUAD_LAUNCHAGENTS_DIR` overrides the target
directory (default `~/Library/LaunchAgents`). Both variables exist so the
install path can be exercised without touching a live session.
