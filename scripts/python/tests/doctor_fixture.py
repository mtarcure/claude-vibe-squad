#!/usr/bin/env python3
"""Shared pieces for tests that run a real bin/doctor.sh in a throwaway tree.

Not a test module: the discovery pattern is ``test_*.py`` (bin/test:526), so
this name is deliberately outside it, the same way ``dispatch_checkout.py``
already is.

Every consumer builds the same fixture -- a copied doctor plus the helpers it
sources, a stubbed HOME whose ``.local/bin`` doctor prepends to PATH, and a
``git init`` so ``classify_dependency`` can answer. Three test files were
already carrying private copies of that helper list; the launch-dependency gate
added a fourth thing they all need, which is the point at which a copy stops
being cheaper than a home (CLAUDE.md rule 10).

SAFETY: nothing here touches the operator's repository, tmux server, processes
or doctor logs. Doctor prepends ``$HOME/.local/bin`` to PATH, so a stub placed
there WINS over the host's real binary -- which is how these fixtures observe a
process table and a tmux server without going anywhere near the real ones.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil


# Everything bin/doctor.sh sources, resolved relative to the repository root.
# A fixture missing one of these does not fail cleanly: doctor either dies at
# the source line or -- worse -- reports the check that needed it as an
# unknown, which reads like a finding about the tree under test.
DOCTOR_HELPERS = (
    Path("bin") / "doctor-log-home.sh",
    Path("shared") / "repo-root.sh",
    Path("shared") / "launch-dependencies.sh",
    Path("shared") / "lead-windows.sh",
    Path("shared") / "namespaces.sh",
    Path("shared") / "process-identity.sh",
)

# Satisfy doctor's ps liveness canary, then report an empty process table, so a
# fixture never depends on -- or reports on -- the host's real processes.
EMPTY_PS = """#!/bin/bash
previous=""
for argument in "$@"; do
    if [[ "$previous" == "-p" ]]; then
        printf '%s\\n' "$argument"
        exit 0
    fi
    previous="$argument"
done
exit 0
"""

# tmux is INSTALLED (so the dependency gate passes) but has no server: every
# query fails, which is what a machine that has never launched the squad looks
# like. Without this the fixture would query the operator's live tmux socket.
TMUX_NO_SERVER = """#!/bin/bash
exit 1
"""

# A lane CLI that answers --version, so the fixture reports the ordinary
# "installed" path rather than a probe that returned nothing.
LANE_CLI = """#!/bin/bash
printf 'doctor-fixture stub 0.0.0\\n'
exit 0
"""

# jq is the one dependency doctor uses to PARSE, so a stub that merely exits
# would silently change what the parsing checks conclude. Hand off to the real
# one; fail closed if the host genuinely has none.
JQ_PASSTHROUGH = """#!/bin/bash
for candidate in /usr/bin/jq /opt/homebrew/bin/jq /usr/local/bin/jq; do
    [[ -x "$candidate" ]] && exec "$candidate" "$@"
done
exit 1
"""

_LANE_CLIS = ("claude", "codex", "gemini", "grok", "kimi")


def write_stub(directory: Path, name: str, body: str = "#!/bin/bash\nexit 0\n") -> Path:
    """Drop one executable stub into a fixture bin directory."""
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / name
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)
    return stub


def install_doctor_helpers(repo_root: Path, fixture_root: Path) -> None:
    """Copy doctor and every file it sources into a throwaway tree."""
    (fixture_root / "bin").mkdir(parents=True, exist_ok=True)
    (fixture_root / "shared").mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "bin" / "doctor.sh", fixture_root / "bin" / "doctor.sh")
    (fixture_root / "bin" / "doctor.sh").chmod(0o755)
    for helper in DOCTOR_HELPERS:
        shutil.copy2(repo_root / helper, fixture_root / helper)


# bin/doctor.sh's notification-spine check imports registry_reconciler to get
# the reconciler's OWN definition of an owed delivery. A fixture that wants that
# check to run has to carry the module and the two siblings it imports.
_RECONCILER_MODULES = (
    "registry_reconciler.py",
    "repo_root.py",
    "durable_publish.py",
)


def install_reconciler(repo_root: Path, fixture_root: Path) -> None:
    """Copy registry_reconciler and its local imports into a throwaway tree."""
    target = fixture_root / "scripts" / "python"
    target.mkdir(parents=True, exist_ok=True)
    for module in _RECONCILER_MODULES:
        shutil.copy2(repo_root / "scripts" / "python" / module, target / module)


def notification_event_key(task_ref: str, state: str) -> str:
    """The receipt key format, mirrored for fixture construction only.

    Tests must be able to build a receipt WITHOUT calling the code under test,
    or a broken key formula would produce a fixture that agrees with itself.
    ``test_doctor_runtime_liveness`` pins this against the reconciler's own
    function so the mirror cannot drift.
    """
    return f"{len(task_ref)}:{task_ref}|{len(state)}:{state}"


def write_receipt(receipts_dir: Path, task_ref: str, state: str) -> Path:
    """Write one delivered-nudge receipt in the reconciler's JSON shape."""
    import hashlib

    receipts_dir.mkdir(parents=True, exist_ok=True)
    key = notification_event_key(task_ref, state)
    receipt = receipts_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.sent"
    receipt.write_text(
        json.dumps(
            {
                "event_key": key,
                "message_sha256": "0" * 64,
                "sent_at": "2026-08-17T00:00:00+00:00",
                "target": "squad:chrono",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt


def launch_dependencies(repo_root: Path) -> list[str]:
    """The commands `squad up` gates on, read from the one file that owns them.

    Parsed rather than hardcoded: a test carrying its own copy of the list would
    be the very duplication shared/launch-dependencies.sh exists to remove.
    """
    text = (repo_root / "shared" / "launch-dependencies.sh").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("SQUAD_REQUIRED_COMMANDS=("):
            return line.split("(", 1)[1].split(")", 1)[0].split()
    raise AssertionError(
        "shared/launch-dependencies.sh defines no SQUAD_REQUIRED_COMMANDS"
    )


def stub_launch_dependencies(
    local_bin: Path, repo_root: Path, *, omit: str | None = None
) -> None:
    """Make every launch dependency resolvable from the fixture's own PATH.

    Without this a fixture inherits the HOST's answer to "is kimi installed",
    which is neither hermetic nor stable: doctor prepends ``$HOME/.local/bin``
    and ``/opt/homebrew/bin``, so the verdict depended on what the maintainer
    happened to have installed. ``omit`` masks exactly one command, which is how
    a test reproduces the cloner who has not installed it.
    """
    for command in launch_dependencies(repo_root):
        if command == omit:
            continue
        if command == "tmux":
            write_stub(local_bin, command, TMUX_NO_SERVER)
        elif command == "jq":
            write_stub(local_bin, command, JQ_PASSTHROUGH)
        elif command in _LANE_CLIS:
            write_stub(local_bin, command, LANE_CLI)
        else:
            write_stub(local_bin, command)
