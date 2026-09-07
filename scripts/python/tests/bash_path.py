#!/usr/bin/env python3
r"""The one home for "which bash do these tests run?" (CLAUDE.md rule 10).

Not a test module: the discovery pattern is ``test_*.py`` (bin/test:526), so
this name is deliberately outside it, the same way ``dispatch_checkout.py`` and
``doctor_fixture.py`` already are.

Linux and the container have exactly one bash and PATH finds it. Windows has
several and PATH finds the WRONG one: ``shutil.which("bash")`` resolves
``C:\Windows\System32\bash.exe``, the WSL shim, which cannot exec DrvFs
scripts reliably. A plain PATH scan that merely skips System32 is no better --
on a Cmder host it lands on the ``bash.exe`` wrapper in Cmder's own ``bin``, not
on a real Git-for-Windows bash.

So on Windows the answer is derived from git itself: ``git --exec-path`` points
inside the Git-for-Windows install, and the nearest ancestor of it holding
``bin/bash.exe`` is that install's real bash. That works for any install
location -- ``C:\Program Files\Git``, a Cmder vendor tree, a scoop shim --
without naming one operator's machine.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
import shutil
import subprocess
import unittest


@functools.cache
def bash_path() -> str:
    """Absolute path to a POSIX bash, or SkipTest if the host has none."""
    if os.name != "nt":
        found = shutil.which("bash")
        if found:
            return found
        raise unittest.SkipTest("bash is required for these seams")

    try:
        exec_path = subprocess.run(
            ["git", "--exec-path"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        exec_path = ""
    if exec_path:
        start = Path(exec_path)
        for ancestor in (start, *start.parents):
            candidate = ancestor / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    raise unittest.SkipTest("Git for Windows bash is required for these seams")
