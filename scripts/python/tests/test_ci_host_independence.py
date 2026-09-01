from __future__ import annotations

import os
import subprocess
import unittest
from unittest import mock

from scripts.python.tests.ci_host_independence import (
    HOST_INDEPENDENT_ENV,
    skip_if_trusted_lane_executable_missing,
    skip_in_host_independent_ci,
)


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
                "is unavailable: /home/runner/.local/bin/agy\n"
            )
        )

        with mock.patch.dict(
            "os.environ", {HOST_INDEPENDENT_ENV: "1"}, clear=False
        ):
            with self.assertRaisesRegex(
                unittest.SkipTest,
                r"host-dependent: trusted lane executable is unavailable: "
                r"/home/runner/\.local/bin/agy",
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


if __name__ == "__main__":
    unittest.main()
