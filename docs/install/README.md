# Install

The supported install path, in order. Each step has a command you run and a
**check** that proves it worked. Do not move to the next step until the check
passes — an installed file is not evidence that a capability works.

Vibe Squad currently targets macOS.

| # | Step | Guide |
|---|---|---|
| 1 | Core tools (`tmux`, `fswatch`, `jq`, `curl`, Python, `uv`) | below |
| 2 | The four provider CLIs, installed and authenticated | [provider-clis.md](provider-clis.md) |
| 3 | Clone and create the Python environment | below |
| 4 | The private memory vault | [../getting-started.md](../getting-started.md#3-create-the-private-memory-vault) |
| 5 | Check and launch | below |
| 6 | Optional: the launchd routines | [daemon.md](daemon.md) |
| 7 | Optional: utility MCPs | below |
| 8 | Optional: guarded security MCPs | [security-mcps.md](security-mcps.md) |

Steps 1–5 are required and that is the whole of it — a clone, an environment, a
vault, and a launch. Steps 6–8 are optional, and skipping them must leave
everything else working — see [What "optional" means](#what-optional-means).

## 1. Core tools

```bash
brew install jq tmux fswatch
```

`curl` ships with macOS. Python 3.13 and `uv` are covered in step 3.

Check:

```bash
for t in tmux fswatch jq curl; do command -v "$t" || echo "MISSING: $t"; done
```

## 2. Provider CLIs

`bin/squad up` exits 1 if any of `claude`, `codex`, `gemini`, or `kimi` is
absent. These are four different installers; see
[provider-clis.md](provider-clis.md) for each one and its authentication step.

## 3. Clone and build the Python environment

```bash
git clone https://github.com/mtarcure/claude-vibe-squad.git
cd claude-vibe-squad
uv sync
```

`uv sync` creates `.venv`, which the chrono MCP servers and several repository
checks run from. The project pins Python 3.13 (`.python-version`); `uv` will
fetch that interpreter if the host has a different one, which needs network
access on first run.

Check:

```bash
.venv/bin/python --version   # expect Python 3.13.x
```

## 4. Private memory vault

Memory lives outside this repository. See
[Getting started §3](../getting-started.md#3-create-the-private-memory-vault).

## 5. Check and launch

```bash
bin/squad doctor
bin/squad up
```

`doctor` reports what is actually available on this machine. Read its
"could not determine" section: those are **not** passes.

With no launchd routines installed — the state you are in right now — `bin/squad
up` prints one notice naming what the absent daemon would have added, and
continues. Everything below this line is an addition to a working install, not a
prerequisite for one.

## 6. The launchd routines (optional)

`com.vibesquad.daemon` adds the live `● daemon` and per-lane segments in the
tmux status bar, and the `/summarize` endpoint the weekly review posts to.
Without it the status bar reads `● daemon offline` and the weekly review writes
no summary; dispatch, review, memory, and the coordinator never call it.

```bash
bash bin/install-routines.sh --daemon-only   # just the daemon
bash bin/install-routines.sh                 # daemon + the optional routines
```

Full detail, including what the installer refuses to do and why, is in
[daemon.md](daemon.md).

Check:

```bash
bash bin/install-routines.sh --status
```

## 7. Utility MCPs (optional)

Memory, research, and media integrations. These are not model transports —
model inference always runs through the native CLIs.

```bash
bash scripts/bootstrap-mcps.sh --dry-run   # show what would change
bash scripts/bootstrap-mcps.sh             # register them
```

Check:

```bash
bash scripts/bootstrap-mcps.sh --status
```

## 8. Guarded security MCPs (optional)

`guarded-semgrep`, `guarded-slither`, and `guarded-solodit` run behind the Trail
of Bits context-protector wrapper, which is a large third-party checkout that
this repository deliberately does not vendor. See
[security-mcps.md](security-mcps.md).

## What "optional" means

An optional dependency that is absent must disable exactly the thing it
provides, announce that it is missing, and leave everything else working. A
check that reports healthy because it could not measure anything is a defect,
not a pass.

Concretely:

- No `secrets.zsh` → the optional research/media integrations stay off. Nothing
  else changes.
- No `mcp-context-protector` → those three guarded security MCPs are
  unavailable and say so. No other MCP, specialist, or lane is affected.
- A provider CLI that is not installed → `scripts/bootstrap-mcps.sh --status`
  reports its registration state as `UNKNOWN (not measured)`, rather than
  listing every server as missing and implying a measurement it never took.
- No `com.vibesquad.daemon` → `bin/squad up` says so once at launch, the status
  bar reads `● daemon offline` rather than going blank, and the weekly-review
  routine writes no summary. Dispatch, review, memory, and the coordinator are
  unaffected. An *installed but broken* daemon is a different case and still
  blocks the launch — see [daemon.md](daemon.md).

The four provider CLIs are **not** optional: `bin/squad up` blocks on them.
Neither are `tmux`, `fswatch`, `jq`, `curl`, Python 3.13, and `uv`. Those are
third-party tools doing real work, and requiring them is the point; a background
launchd job of our own is not in that category, which is why it stopped being a
precondition.
