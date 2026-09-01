"""Shared skip policy for tests that require trusted host infrastructure."""

from __future__ import annotations

import os
import re
import subprocess
import unittest
from collections.abc import Callable
from typing import TypeVar


HOST_INDEPENDENT_ENV = "SQUAD_CI_HOST_INDEPENDENT"
_TestItem = TypeVar("_TestItem", bound=Callable[..., object] | type)
_TRUSTED_LANE_EXECUTABLE_UNAVAILABLE = re.compile(
    r"trusted lane executable is unavailable:\s*([^\r\n]+)"
)


def skip_in_host_independent_ci(reason: str) -> Callable[[_TestItem], _TestItem]:
    """Skip a live-host test only when the explicit CI boundary is enabled."""

    return unittest.skipIf(
        os.environ.get(HOST_INDEPENDENT_ENV) == "1",
        f"host-dependent: {reason}",
    )


def skip_if_trusted_lane_executable_missing(
    completed: subprocess.CompletedProcess[str],
) -> subprocess.CompletedProcess[str]:
    """Skip an admitted dispatch only when its trusted lane CLI is absent.

    Refusal-path tests still receive their completed process and keep asserting
    everywhere.  A host-independent CI run skips only after the real dry-run
    preflight names the unavailable executable, so hosts that have the binary
    continue to execute the same tests even with the CI boundary enabled.
    """

    if os.environ.get(HOST_INDEPENDENT_ENV) != "1":
        return completed
    output = (completed.stdout or "") + (completed.stderr or "")
    match = _TRUSTED_LANE_EXECUTABLE_UNAVAILABLE.search(output)
    if match:
        executable = match.group(1).strip()
        raise unittest.SkipTest(
            "host-dependent: trusted lane executable is unavailable: "
            f"{executable}"
        )
    return completed
