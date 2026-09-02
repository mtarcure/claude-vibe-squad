from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from scripts.python.tests.ci_host_independence import (
    HOST_INDEPENDENT_ENV,
    hermetic_lane_cli_environment,
    hermetic_lane_cli_patch,
    skip_if_trusted_lane_executable_missing,
    skip_in_host_independent_ci,
)


# The sample executable paths below deliberately avoid the runner's real
# home-directory path. The publication content scan rejects EVERY absolute
# home-shaped path in a published file -- a blanket rule, so it never has to
# decide whose home is safe -- and this file is published. The path here is
# arbitrary test data; only its absoluteness and its appearance in the message
# matter, so a hostedtoolcache path exercises the behaviour identically.

class HostIndependentSkipPolicyTests(unittest.TestCase):
    @staticmethod
    def _decorated(*, flag: str | None):
        environment = {} if flag is None else {HOST_INDEPENDENT_ENV: flag}
        with mock.patch.dict(os.environ, environment, clear=True):

            @skip_in_host_independent_ci("needs a live fixture")
            def sample() -> None:
                return None

        return sample

    def test_exact_flag_value_enables_skip(self) -> None:
        sample = self._decorated(flag="1")
        self.assertTrue(sample.__unittest_skip__)
        self.assertEqual(
            sample.__unittest_skip_why__,
            "host-dependent: needs a live fixture",
        )

    def test_absent_or_other_flag_value_keeps_test_enabled(self) -> None:
        for flag in (None, "0", "true"):
            with self.subTest(flag=flag):
                sample = self._decorated(flag=flag)
                self.assertFalse(getattr(sample, "__unittest_skip__", False))


class TrustedLaneExecutableSkipTests(unittest.TestCase):
    def completed(self, *, stderr: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["bin/send-task.sh", "packet.md", "--dry-run"],
            returncode=1,
            stdout="",
            stderr=stderr,
        )

    def test_host_independent_ci_names_and_skips_the_missing_executable(self) -> None:
        completed = self.completed(
            stderr=(
                "dispatch_context_builder.py: error: trusted lane executable "
                "is unavailable: /opt/hostedtoolcache/bin/agy\n"
            )
        )

        with mock.patch.dict(
            "os.environ", {HOST_INDEPENDENT_ENV: "1"}, clear=False
        ):
            with self.assertRaisesRegex(
                unittest.SkipTest,
                r"host-dependent: trusted lane executable is unavailable: "
                r"/opt/hostedtoolcache/bin/agy",
            ):
                skip_if_trusted_lane_executable_missing(completed)

    def test_the_same_missing_executable_is_not_skipped_outside_ci(self) -> None:
        completed = self.completed(
            stderr=(
                "error: trusted lane executable is unavailable: "
                "/opt/homebrew/bin/codex\n"
            )
        )

        with mock.patch.dict("os.environ", {}, clear=True):
            returned = skip_if_trusted_lane_executable_missing(completed)

        self.assertIs(returned, completed)

    def test_an_admission_refusal_keeps_running_in_host_independent_ci(self) -> None:
        completed = self.completed(
            stderr="error: return_artifact is outside packet write_scope\n"
        )

        with mock.patch.dict(
            "os.environ", {HOST_INDEPENDENT_ENV: "1"}, clear=False
        ):
            returned = skip_if_trusted_lane_executable_missing(completed)

        self.assertIs(returned, completed)


class HermeticLaneCliFixtureTests(unittest.TestCase):
    def test_in_process_patch_is_scoped_and_uses_a_real_executable(self) -> None:
        paths = {"codex": Path("/missing/codex")}

        with hermetic_lane_cli_patch(paths, ("codex",)):
            fixture = paths["codex"]
            self.assertTrue(fixture.is_absolute())
            self.assertTrue(fixture.is_file())
            self.assertTrue(os.access(fixture, os.X_OK))

        self.assertEqual(paths, {"codex": Path("/missing/codex")})

    def test_subprocess_fixture_changes_only_the_named_lanes(self) -> None:
        environment = hermetic_lane_cli_environment(
            self,
            ("codex", "gemini"),
            base=os.environ,
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import seatbelt_profile as s; "
                    "print(s.LANE_CLI_PATHS['codex']); "
                    "print(s.LANE_CLI_PATHS['gemini']); "
                    "print(s.LANE_CLI_PATHS['claude'])"
                ),
            ],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        codex, gemini, claude = completed.stdout.splitlines()
        self.assertEqual(codex, gemini)
        fixture = Path(codex)
        self.assertTrue(fixture.is_file())
        self.assertTrue(os.access(fixture, os.X_OK))
        self.assertNotEqual(claude, codex)

if __name__ == "__main__":
    unittest.main()
