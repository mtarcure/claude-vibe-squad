"""Shared skip policy for tests that require trusted host infrastructure."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from typing import TypeVar
from unittest import mock


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


def hermetic_lane_cli_patch(
    lane_cli_paths: MutableMapping[str, Path],
    lanes: Sequence[str],
):
    """Patch selected lane paths to one real executable inside this test process.

    This is a dependency fixture for tests whose subject lies after executable
    admission but which never launch the lane CLI.  It is deliberately located
    under ``scripts/python/tests`` and has no production environment switch.
    """

    executable = Path(sys.executable).resolve(strict=True)
    return mock.patch.dict(
        lane_cli_paths,
        {lane: executable for lane in lanes},
    )


def hermetic_lane_cli_environment(
    test_case: unittest.TestCase,
    lanes: Sequence[str],
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a subprocess environment with selected trusted CLI test fixtures.

    Python imports the generated ``sitecustomize`` only in the subprocesses to
    which the caller passes this environment.  The production builder does not
    know about this seam, and the fixture does not depend on the CI profile flag.
    """

    if not lanes:
        raise ValueError("at least one lane is required")
    fixture = tempfile.TemporaryDirectory(prefix="lane-cli-fixture-")
    test_case.addCleanup(fixture.cleanup)
    fixture_root = Path(fixture.name)
    python_root = Path(__file__).resolve().parents[1]
    execution_marker = fixture_root / "unexpected-execution"
    executable = fixture_root / "lane-cli-stub"
    executable.write_text(
        "#!/bin/sh\n"
        ': > "$SQUAD_TEST_LANE_CLI_EXECUTION_MARKER"\n'
        "exit 97\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    test_case.addCleanup(
        lambda: test_case.assertFalse(
            execution_marker.exists(),
            "a dry-run test executed its lane CLI dependency fixture",
        )
    )
    sitecustomize = fixture_root / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "import sys",
                f"sys.path.insert(0, {str(python_root)!r})",
                "import seatbelt_profile",
                f"executable = Path({str(executable)!r})",
                f"for lane in {tuple(lanes)!r}:",
                "    seatbelt_profile.LANE_CLI_PATHS[lane] = executable",
                "",
            )
        ),
        encoding="utf-8",
    )

    environment = dict(os.environ if base is None else base)
    inherited_pythonpath = environment.get("PYTHONPATH")
    pythonpath = [str(fixture_root), str(python_root)]
    if inherited_pythonpath:
        pythonpath.append(inherited_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
    environment["SQUAD_TEST_LANE_CLI_EXECUTION_MARKER"] = str(execution_marker)
    return environment
