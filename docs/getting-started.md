# Getting started

Vibe Squad is currently macOS-first, and setup is manual. The normal experience
is one conversation with Chrono; Codex, Claude, the agy-backed Gemini lane,
Grok, and Kimi run as fresh native CLI processes behind the board.

This page is the narrated walkthrough. For the step-by-step install path with a
check after every step, see [docs/install](install/README.md).

## 1. Install the prerequisites

You need:

- `tmux`, `fswatch`, `jq`, and `curl`
- Python 3.13 and `uv`
- the `claude`, `codex`, `agy`, `grok`, and `kimi` CLIs

```bash
brew install jq tmux fswatch
```

All five provider CLIs are required — `bin/squad up` exits 1 if any is missing:

```bash
curl -fsSL https://claude.ai/install.sh | bash   # claude
npm install -g @openai/codex                     # codex
# install Antigravity's agy CLI from its provider distribution
# install the grok CLI from the xAI provider distribution
uv tool install kimi-cli                         # kimi
```

Claude, Codex, Gemini-through-agy, Grok, and Kimi authenticate through their
supported subscription, OAuth, or managed-login paths. `GEMINI_API_KEY` is not
Gemini lane authentication. Model inference always runs through those native
CLIs, never through an MCP server.

Per-CLI authentication steps, postcondition checks, and the `PATH` gotcha for
`claude` and `kimi` are in [Provider CLIs](install/provider-clis.md).

Check before moving on:

```bash
source shared/launch-dependencies.sh
for dep in "${SQUAD_REQUIRED_COMMANDS[@]}"; do
  command -v "$dep" >/dev/null 2>&1 || echo "MISSING: $dep"
done
```

## 2. Clone the repository

```bash
git clone https://github.com/mtarcure/claude-vibe-squad.git
cd claude-vibe-squad
uv sync
```

`uv sync` creates the local Python environment used by optional utility
integrations and repository checks.

## 3. Create the private memory vault

Memory must live outside this public repository. Choose one stable, absolute
path and keep it across sessions:

```bash
export CHRONO_VAULT_ROOT="$HOME/Obsidian-Chrono"
mkdir -p "$CHRONO_VAULT_ROOT"
chmod 700 "$CHRONO_VAULT_ROOT"
if [ ! -f "$CHRONO_VAULT_ROOT/.chrono-vault" ]; then
  printf '%s\n' '{"vault_id":"local-vibesquad","schema_version":1}' \
    > "$CHRONO_VAULT_ROOT/.chrono-vault"
  chmod 600 "$CHRONO_VAULT_ROOT/.chrono-vault"
fi
```

Persist `CHRONO_VAULT_ROOT` in your shell configuration. Do not place this
directory inside the clone, and never commit its notes or credentials. See the
[Chrono Vault guide](../plugins/chrono-vault/README.md) for its data model and
safety boundary.

## 4. Configure authentication and optional tools

If you enable the optional Gemini-backed media provider, make its
`GEMINI_API_KEY` available through your local secret store or shell environment.
The agy lane itself uses OAuth and does not consume that key. Do not add it, or
any other credential, to the repository.

Utility MCPs provide memory, research, browser, and media tools; they are not
model transports. Review what the bootstrap would change before registering
them in your user-level CLI configuration:

```bash
bash scripts/bootstrap-mcps.sh --dry-run
bash scripts/bootstrap-mcps.sh
```

The second command is optional. Run it only when you want those integrations.
An absent optional provider disables exactly what it provides and leaves
everything else working; `--status` reports an uninstalled CLI's registration
state as `UNKNOWN (not measured)` rather than guessing.

`guarded-semgrep`, `guarded-slither`, and `guarded-solodit` additionally need the
Trail of Bits context-protector wrapper, which is an install-time dependency this
repository never vendors. Without it those three servers are unavailable and say
so. See [Guarded security MCPs](install/security-mcps.md).

## 5. Check and launch

```bash
bin/squad doctor
bin/squad up
```

That is the end of the required path. Nothing has to be installed into `launchd`
first: with no daemon present, `bin/squad up` prints one notice saying so and
carries on.

`doctor` reports what is actually available on this machine; installed files or
configuration alone are not proof that a capability works. Resolve any reported
errors before relying on the affected capability.

`doctor` has two modes. The default is the fast pre-flight, and it is what
`bin/squad up` gates on under `SQUAD_DOCTOR_TIMEOUT` (45 seconds). A handful of
checks — currently the public-export hygiene gate, which takes minutes on a
large working tree — cost more than that budget, so the fast run declines them
and lists them under **NOT MEASURED IN FAST MODE**. Those are not passes; run
`bin/squad doctor --deep` to measure them. The nightly routine already does.

## 6. Optional: the launchd routines

`launchd/` holds templates, not installable plists, and none of them is a
precondition for running the squad.

```bash
bash bin/install-routines.sh --daemon-only   # just com.vibesquad.daemon
bash bin/install-routines.sh                 # daemon + the optional routines (docs/install/daemon.md)
bash bin/install-routines.sh --status
```

What `com.vibesquad.daemon` adds, and nothing else does:

- the live `● daemon` indicator and the per-lane task capsules in the tmux
  status bar — its `/tasks` endpoint is where `bin/vs-lane-status.sh` reads them
- the `POST /mcp/<server>/<tool>` HTTP bridge documented in
  `plugins/chrono-recon/README.md`

What runs identically without it: board dispatch and worktree isolation, the
outbox watcher, the reconciliation sweep, the Chrono coordinator, `bin/squad
doctor`, and private memory. None of them opens a connection to it.

What visibly degrades without it: the status bar reads `● daemon offline`
instead of live lane state, and the documented `curl` bridge to the MCP servers
is unavailable. Both are stated at launch, not discovered later.

The installer renders both `__VAULT_ROOT__` and `__HOME__`, refuses a plist with
any unresolved token, validates it with `plutil`, installs it atomically, and
verifies the load with `launchctl print` instead of trusting an exit code. It
will not overwrite a plist you have edited without `--force`, and it will not
bootstrap over a label already loaded from a different file.

Once a daemon *is* installed, `bin/squad up` becomes strict about it again: a
broken or foreign one stops the launch rather than running around it. Absent is
fine; broken is not.

See [The launchd daemon](install/daemon.md) for the failure modes and uninstall.

`--safe` does not select a more conservative profile — no such profile exists.
It suppresses the first-run autonomy warning and skips the pre-flight `doctor`
gate, so plain `bin/squad up` is the stricter of the two on a fresh install.
Permissions for the coordinator and for board-dispatched workers are identical
either way. Ask Chrono for work in plain language, then explicitly choose
Project for delivery work or Bounty for authorized security work when a typed
workflow is needed.

Useful lifecycle commands:

```bash
bin/squad status
bin/squad attach
bin/squad stop
```

For the security and privacy model, read [Architecture](architecture.md) and
[Private configuration](private-config.md).
