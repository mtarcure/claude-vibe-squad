# Rollback runbook (P11.7)

Rollback covers four independent surfaces: Git refs, launchd/runtime,
repository-local state, and the private memory vault. Restore one surface at a
time and verify it before proceeding to the next. Every live mutation still
requires the applicable operator gate.

---

## 1. Git rollback

These commands are destructive to the selected checkout. Confirm the checkout,
dirty state, desired anchor, and operator gate before running either one.

Private rollback anchor:

```bash
git -C ~/Obsidian-Claude-Vibe-Squad reset --hard v4-baseline-2026-08-07
```

The public checkout rolls back to the `v1.1.1` tag, but only after a live remote
preflight resolves that tag to the commit you expect. A rollback must never
trust a copied commit id: a remote ref can move, and a stale local snapshot can
disagree with the live remote. Run this fail-closed preflight from a
network-capable operator shell first:

```bash
git ls-remote --tags public refs/tags/v1.1.1 'refs/tags/v1.1.1^{}'
```

If the command fails, returns no tag, or resolves the peeled tag to a commit you
do not expect, stop. That is an unresolved remote-state discrepancy, not
permission to create or move a public tag. Only once the preflight resolves
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

Repository plists are install templates. List them with
`git ls-files 'launchd/*.plist'`; most carry literal `__VAULT_ROOT__` and/or
`__HOME__` tokens — check with `grep -lE '__[A-Z][A-Z0-9_]*__' launchd/*.plist` —
and the render step below fails closed on any token that survives. Never copy a
repository plist directly into `~/Library/LaunchAgents`; render it, reject every
remaining token, lint it, install it atomically, then bootstrap it.

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

Result in a public clone: exit 0 with no output. Nothing under `_state/` is
tracked; the whole directory is runtime state that publication excludes.

Git rollback therefore does not restore the untracked runtime registry,
receipts, campaign evidence, or other local state under `_state/`. Do not include
that directory in a Git cleanup or reset procedure. Any cleanup remains a
separate operator-gated action with its own backup and recovery evidence.

## 4. Private memory vault

Create a new verified snapshot on demand with:

```bash
bin/vault-snapshot.sh
```

The loaded nightly agent also invokes this command daily at 03:00. Confirm a
usable archive exists before rollback; the schedule alone is not recovery
evidence.

For a restore to a different path, extract the archive and rebuild the FTS index
because the index contains absolute note paths:

```bash
tar -xzf ~/vault-snapshots/chrono-vault-<stamp>.tar.gz -C <target-parent>
CHRONO_VAULT_ROOT=<target-parent>/Obsidian-Chrono .venv/bin/python -c \
  "import sys;sys.path.insert(0,'plugins/chrono-vault');import index;print(index.rebuild_index())"
```

Treat the restore as unverified until a separate, safe exercise measures both
RPO and RTO against a scratch destination.

---

## Current status

| surface | rollback status |
|---|---|
| private Git refs | rollback anchors `v3-final` and `v4-baseline-2026-08-07` exist |
| public Git ref | roll back to `v1.1.1`; a live remote preflight that resolves the tag to the commit you expect is mandatory before touching a public checkout |
| runtime config | every tracked agent renders to an install path via §2; install state is host-specific, not a repository fact |
| daemon shutdown | `bin/squad down` bootouts and verifies absence; raw tmux kill is explicitly tmux-only |
| plist restore | template rendering, unresolved-token rejection, lint, atomic install, bootstrap, and load verification are required |
| repository-local `_state/` | not restored by Git; a public clone tracks nothing under it |
| memory vault | snapshot scheduled daily at 03:00; scratch restore/RTO/RPO validation remains separate |
