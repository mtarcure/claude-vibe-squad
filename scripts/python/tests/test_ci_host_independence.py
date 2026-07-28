from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts.python.tests.ci_host_independence import (
    HOST_INDEPENDENT_ENV,
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


if __name__ == "__main__":
    unittest.main()
