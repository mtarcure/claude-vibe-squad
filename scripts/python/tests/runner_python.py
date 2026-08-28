"""Resolve an interpreter that ``bin/test`` will accept, or say why none exists.

``bin/test``'s ``select_python`` blocks on any interpreter outside ``3.13.x``.
A test that hands the runner an explicit ``PYTHON_BIN`` must therefore hand it a
SUPPORTED one: passing ``sys.executable`` silently rewrites every assertion
about a later gate into an assertion about the version gate.  That is exactly
how three of these tests went red when the maintainer host moved to 3.14 -- the
runner reported ``environment:python-version:3.14.6`` for suites whose contract
had nothing to do with the version pin, and the coverage went dead without the
failure naming a cause.

The pin below duplicates ``bin/test``.  ``bin/test`` owns it; this mirrors it;
``test_unified_test_runner`` asserts the two agree, so the copy cannot age
independently.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# Mirrors the `^3\.13\.[0-9]+$` guard in bin/test select_python.
SUPPORTED_VERSION_RE = re.compile(r"^3\.13\.[0-9]+$")

_REASON = (
    "no bin/test-supported interpreter (3.13.x) is installed: neither "
    "$ROOT/.venv/bin/python nor python3.13 on PATH resolves to one. "
    "Install one, or run this suite through `bin/test`, which provisions it."
)


def _version_of(candidate: Path | str) -> str:
    try:
        completed = subprocess.run(
            [
                str(candidate),
                "-c",
                'import sys; print(".".join(map(str, sys.version_info[:3])))',
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def find_runner_python(root: Path) -> str | None:
    """Return a real path to a 3.13.x interpreter, mirroring bin/test's order."""
    candidates = [root / ".venv" / "bin" / "python"]
    on_path = shutil.which("python3.13")
    if on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        if not (candidate.is_file() and os.access(candidate, os.X_OK)):
            continue
        if SUPPORTED_VERSION_RE.fullmatch(_version_of(candidate)):
            return os.path.realpath(candidate)
    return None


def require_runner_python(test_case, root: Path) -> str:
    """Return a supported interpreter, or skip with the reason none was found.

    Skipping -- rather than falling back to ``sys.executable`` -- is deliberate:
    a fallback would put the test back in the state this module exists to
    prevent, passing or failing for a reason the assertion never mentions.
    """
    resolved = find_runner_python(root)
    if resolved is None:
        test_case.skipTest(_REASON)
    return resolved
