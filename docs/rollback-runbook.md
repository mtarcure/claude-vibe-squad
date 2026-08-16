# Rollback runbook (P11.7)

**Re-measured 2026-08-11.** The evidence ledger below replaces the stale
2026-08-09 snapshot. Each mutable claim is paired with the literal command and
result used to check it. A live mutation still requires the applicable operator
gate; the measurements in this revision were read-only.

Rollback covers four independent surfaces: Git refs, launchd/runtime,
repository-local state, and the private memory vault. Restore one surface at a
time and verify it before proceeding to the next.

---

## 0. Measurement ledger

### Private Git refs

Literal command (unpiped):

```bash
git tag --list
```

Result: exit 0 with 14 tags. Five of them are `rescue/TASK-…` tags naming private
internal task identifiers; they are not rollback anchors, so their names are
redacted here rather than reproduced. Run the command yourself to see them:

```text
archive/dispatch-smoke
archive/mmrinv
archive/v1-public
pre-consolidation-2026-07-23
rescue/TASK-<redacted>          (5 private rescue tags)
v1.0-pre-1.1
v1.1.0
v1.1.1
v3-final
v4-baseline-2026-08-07
```

Literal command (unpiped):

```bash
git show-ref --verify refs/tags/v3-final
```

Result: exit 0:

```text
64cd32cba652481a88842a057df55756208afb0c refs/tags/v3-final
```

Literal commands (unpiped):

```bash
git rev-parse v4-baseline-2026-08-07
git rev-parse v3-final
```

Results: exit 0, respectively:

```text
b0acdb8aff88192b14f4264ecf088b672f0c413b
64cd32cba652481a88842a057df55756208afb0c
```

The earlier claims “13 tags” and “`v3-final` is missing” are false. There are
14 private tags and both rollback anchors exist.

### Public Git ref

The public rollback anchor is `v1.1.1` at
`53122e48fd2074ad988cdd59111f68bfe2f47437`; the earlier “zero public tags”
claim is false. This worker could confirm that the live GitHub repository exists
and that the local read-only `public/main` snapshot is exactly that commit, but
the sandbox could not refresh the tag namespace directly:

```bash
git ls-remote --tags public
```

Result: exit 128, unpiped:

```text
fatal: unable to access 'https://github.com/mtarcure/claude-vibe-squad.git/': Could not resolve host: github.com
```

Because a remote lookup failed, do not rely on a copied claim during an actual
rollback. First run this fail-closed preflight from a network-capable operator
shell and require the expected ref/commit before changing a checkout:

```bash
git ls-remote --tags public refs/tags/v1.1.1 'refs/tags/v1.1.1^{}'
```

Expected lightweight-tag result:

```text
53122e48fd2074ad988cdd59111f68bfe2f47437	refs/tags/v1.1.1
```

If the command fails, returns no tag, or resolves the peeled tag to a different
commit, stop. That is an unresolved remote-state discrepancy, not permission to
create or move a public tag.

### Installed and tracked launchd agents

Each command below was run directly, without a pipe:

```bash
launchctl print gui/$(id -u)/com.chrono.caffeinate
launchctl print gui/$(id -u)/com.chrono.chrono-vault-mcp
launchctl print gui/$(id -u)/com.chrono.dream
launchctl print gui/$(id -u)/com.chrono.squad-monitor
launchctl print gui/$(id -u)/com.claudevibesquad.nightly
launchctl print gui/$(id -u)/com.vibesquad.chrome
launchctl print gui/$(id -u)/com.vibesquad.chrono-remote
launchctl print gui/$(id -u)/com.vibesquad.daemon
launchctl print gui/$(id -u)/com.vibesquad.transcription-cache-ttl
launchctl print gui/$(id -u)/com.vibesquad.weekly-review
```

Result: the nine commands other than `com.vibesquad.chrono-remote` exited 0 and
named a plist under `~/Library/LaunchAgents`; `com.vibesquad.chrono-remote`
exited 113 with “Could not find service”. The nine installed agents are:

- `com.chrono.caffeinate`
- `com.chrono.chrono-vault-mcp`
- `com.chrono.dream`
- `com.chrono.squad-monitor`
- `com.claudevibesquad.nightly`
- `com.vibesquad.chrome`
- `com.vibesquad.daemon`
- `com.vibesquad.transcription-cache-ttl`
- `com.vibesquad.weekly-review`

Literal command (unpiped):

```bash
git ls-files launchd
```

Result: exit 0 with a tracked plist for every label above, plus the tracked but
not installed `com.vibesquad.chrono-remote.plist`. Therefore the prior “five of
nine tracked / four untracked” claim is false: all nine installed agents are
tracked, and the repository has ten plist files total.

### Vault snapshot schedule

Literal command (unpiped):

```bash
launchctl print gui/$(id -u)/com.claudevibesquad.nightly
```

Result: exit 0. The live event trigger reports `Hour = 3`, `Minute = 0`, and the
installed program is `bin/run-nightly.sh`. Source inspection shows
`bin/run-nightly.sh` invokes `bin/vault-snapshot.sh` as its first phase (line 79
at measurement time). The prior “nothing schedules this” claim is false: the
snapshot is scheduled daily at 03:00 through the loaded nightly agent. A
schedule is not proof that every run succeeds; inspect the nightly and snapshot
logs before depending on a particular archive.

---

## 1. Git rollback

These commands are destructive to the selected checkout. Confirm the checkout,
dirty state, desired anchor, and operator gate before running either one.

Private rollback anchor:

```bash
git -C ~/Obsidian-Claude-Vibe-Squad reset --hard v4-baseline-2026-08-07
```

Public-checkout rollback anchor, only after the remote preflight above resolves
`v1.1.1` to the expected commit:

```bash
git -C <public-checkout> reset --hard v1.1.1
```

Neither command pushes, moves, or creates a remote ref. Mutating the real public
remote is a separate public-release operation and is outside this runbook step.

## 2. Runtime config and processes

### Stop the complete squad runtime

Use the lifecycle command, not `kill` and not a raw tmux command:

```bash
bin/squad down
```

`down` now targets `gui/$(id -u)/com.vibesquad.daemon` with
`launchctl bootout`, polls `launchctl print` until the service is absent, and
only then proceeds with the existing state-summary and tmux shutdown. It fails
closed if launchd cannot confirm absence. `tmux kill-session -t squad` closes
only tmux; it does not stop the KeepAlive daemon.

Expected daemon confirmation:

```text
✓ Daemon stopped and verified absent from launchd: gui/<uid>/com.vibesquad.daemon
```

Independent postcondition (unpiped):

```bash
launchctl print gui/$(id -u)/com.vibesquad.daemon
```

Expected result: exit 113 and “Could not find service”. Do not declare shutdown
if this command still exits 0.

### Restore a tracked plist safely

Repository plists are install templates. Nine of the ten tracked plists contain
literal `__VAULT_ROOT__` and/or `__HOME__` tokens. Never copy a repository plist
directly into `~/Library/LaunchAgents`; render it, reject every remaining token,
lint it, install it atomically, then bootstrap it.

Set `AGENT` to one tracked filename such as `com.vibesquad.daemon.plist`. This
procedure refuses to overwrite an existing installed plist; preserve and review
the old file first if the destination already exists.

<!-- plist-restore-script: begin -->
```bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
AGENT="${AGENT:?set AGENT to one tracked .plist filename}"
LAUNCH_AGENTS_DIR="${LAUNCH_AGENTS_DIR:-${HOME}/Library/LaunchAgents}"

case "${AGENT}" in
    *.plist) ;;
    *) echo "ERROR: AGENT must end in .plist" >&2; exit 64 ;;
esac
case "${AGENT}" in
    */*) echo "ERROR: AGENT must be a filename, not a path" >&2; exit 64 ;;
esac

source_plist="${REPO_ROOT}/launchd/${AGENT}"
target_plist="${LAUNCH_AGENTS_DIR}/${AGENT}"
[[ -f "${source_plist}" ]] || { echo "ERROR: missing ${source_plist}" >&2; exit 1; }
mkdir -p "${LAUNCH_AGENTS_DIR}"
[[ ! -e "${target_plist}" ]] || {
    echo "ERROR: ${target_plist} already exists; preserve and review it before replacement" >&2
    exit 1
}

rendered_plist="$(mktemp "${LAUNCH_AGENTS_DIR}/${AGENT}.rendered.XXXXXX")"
cleanup_rendered() {
    if [[ -n "${rendered_plist:-}" && -f "${rendered_plist}" ]]; then
        rm -f -- "${rendered_plist}"
    fi
}
trap cleanup_rendered EXIT

python3 - "${source_plist}" "${rendered_plist}" "${REPO_ROOT}" "${HOME}" <<'PY'
from pathlib import Path
import sys

source, destination, repo_root, home = sys.argv[1:]
rendered = (
    Path(source)
    .read_text()
    .replace("__VAULT_ROOT__", repo_root)
    .replace("__HOME__", home)
)
Path(destination).write_text(rendered)
PY

if LC_ALL=C grep -Eq '__[A-Z][A-Z0-9_]*__' "${rendered_plist}"; then
    echo "ERROR: rendered plist still contains a template token" >&2
    exit 1
fi
plutil -lint "${rendered_plist}"
chmod 0644 "${rendered_plist}"
mv "${rendered_plist}" "${target_plist}"
rendered_plist=""

launchctl bootstrap "gui/$(id -u)" "${target_plist}"
launchctl print "gui/$(id -u)/${AGENT%.plist}"
```
<!-- plist-restore-script: end -->

The final `launchctl print` is the load postcondition. A successful file render
without a loaded agent is not a successful runtime restore.

### Start after shutdown

```bash
bin/squad up
```

`up` checks the installed daemon plist for unresolved template tokens, validates
it with `plutil`, bootstraps it when absent, and confirms it with
`launchctl print` before running the ordinary health gate and creating tmux.
The repository template is never used as the bootstrap source.

## 3. Schemas and repository-local state

Literal command (unpiped):

```bash
git ls-files _state
```

Result: exit 0 with exactly one tracked path:

```text
_state/repo-split-2026-07-16/identifier-denylist.txt
```

Git rollback therefore does not restore the untracked runtime registry,
receipts, campaign evidence, or other local state under `_state/`. Do not include
that directory in a Git cleanup or reset procedure. Any cleanup remains a
separate operator-gated action with its own backup and recovery evidence.

## 4. Private memory vault

Create a new verified snapshot on demand with:

```bash
bin/vault-snapshot.sh
```

The loaded nightly agent also invokes this command daily at 03:00 as measured
above. Confirm a usable archive exists before rollback; the schedule alone is
not recovery evidence.

For a restore to a different path, extract the archive and rebuild the FTS index
because the index contains absolute note paths:

```bash
tar -xzf ~/vault-snapshots/chrono-vault-<stamp>.tar.gz -C <target-parent>
CHRONO_VAULT_ROOT=<target-parent>/Obsidian-Chrono .venv/bin/python -c \
  "import sys;sys.path.insert(0,'plugins/chrono-vault');import index;print(index.rebuild_index())"
```

This packet did not browse the private vault or re-run a destructive restore;
its memory aperture is `none`. Treat the restore as unverified until a separate,
safe exercise measures both RPO and RTO against a scratch destination.

---

## Current status

| surface | measured rollback status |
|---|---|
| private Git refs | available: 14 tags; `v3-final` and `v4-baseline-2026-08-07` exist |
| public Git ref | `v1.1.1` / `53122e48`; live remote resolution is a mandatory preflight because this worker's DNS lookup was blocked |
| runtime config | all nine installed agents have tracked source plists; one additional tracked agent is not installed |
| daemon shutdown | `bin/squad down` bootouts and verifies absence; raw tmux kill is explicitly tmux-only |
| plist restore | template rendering, unresolved-token rejection, lint, atomic install, bootstrap, and load verification are required |
| repository-local `_state/` | not restored by Git; only one path is tracked |
| memory vault | snapshot scheduled daily at 03:00; scratch restore/RTO/RPO validation remains separate |
