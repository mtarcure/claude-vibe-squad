from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "bin" / "test"


class UnifiedTestRunnerContractTests(unittest.TestCase):
    def run_runner(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(RUNNER), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_private_self_test_covers_typed_results_and_exit_precedence(self) -> None:
        result = self.run_runner("--runner-self-test")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RUNNER SELFTEST PASS", result.stdout)
        self.assertIn("BLOCKED: synthetic dependency", result.stderr)
        self.assertIn("FAIL: synthetic product failure", result.stderr)
        self.assertIn("WARNING: SKIP synthetic non-applicable", result.stderr)
        self.assertIn("N/A: synthetic private projection", result.stdout)

    def test_invalid_arguments_are_usage_errors(self) -> None:
        result = self.run_runner("--unknown")

        self.assertEqual(result.returncode, 64)
        self.assertIn("Usage: bin/test", result.stderr)

    def test_multiple_arguments_are_usage_errors(self) -> None:
        result = self.run_runner("--fast", "--full")

        self.assertEqual(result.returncode, 64)
        self.assertIn("Usage: bin/test", result.stderr)

    def test_orphan_supervisor_detector_is_an_explicit_runner_gate(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn(
            '"$PYTHON_BIN" scripts/python/tests/orphan_supervisor_leak_test.py',
            runner,
        )
        self.assertIn('--scan-root "$suite_tmp"', runner)

    def test_unsupported_explicit_python_blocks_without_running_python_suites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_python = Path(temp_dir) / "python"
            fake_python.write_text("#!/bin/sh\nprintf '3.12.9\\n'\n")
            fake_python.chmod(0o755)
            for command in ("basename", "dirname"):
                command_path = shutil.which(command)
                self.assertIsNotNone(command_path)
                (Path(temp_dir) / command).symlink_to(command_path)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": temp_dir,
                    "PYTHON_BIN": str(fake_python),
                    "SQUAD_CI_HOST_INDEPENDENT": "1",
                }
            )
            result = subprocess.run(
                ["/bin/bash", str(RUNNER), "--fast"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("environment:python-version:3.12.9", result.stderr)
        self.assertNotIn("FAIL:", result.stderr)
        summary = re.search(
            r"Total suites: (\d+) \(pass=(\d+), fail=(\d+), blocked=(\d+), "
            r"skip=(\d+), na=(\d+)\)",
            result.stdout,
        )
        self.assertIsNotNone(summary, result.stdout)
        total, passed, failed, blocked, skipped, not_applicable = map(
            int, summary.groups()
        )
        self.assertEqual((passed, failed), (0, 0))
        self.assertEqual(blocked, total - skipped - not_applicable)

    def test_optimized_python_blocks_before_test_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for command in ("basename", "dirname"):
                command_path = shutil.which(command)
                self.assertIsNotNone(command_path)
                (Path(temp_dir) / command).symlink_to(command_path)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": temp_dir,
                    "PYTHON_BIN": os.path.realpath(os.sys.executable),
                    "PYTHONOPTIMIZE": "1",
                    "SQUAD_CI_HOST_INDEPENDENT": "1",
                }
            )
            result = subprocess.run(
                ["/bin/bash", str(RUNNER), "--fast"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("environment:python-optimized", result.stderr)
        self.assertNotIn("FAIL:", result.stderr)

    def test_forced_host_denial_is_not_applicable_before_dispatch(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "PYTHON_BIN": os.path.realpath(os.sys.executable),
                "SQUAD_RUNNER_TEST_HOST_PREFLIGHT": "deny-loopback",
            }
        )
        result = subprocess.run(
            ["/bin/bash", str(RUNNER), "--runner-host-preflight"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "N/A: dispatch host preflight: "
            "not-applicable:environment:sandbox:loopback",
            result.stdout,
        )
        self.assertIn("blocked=0", result.stdout)
        self.assertIn("na=1", result.stdout)
        self.assertNotIn("dispatch enforcement", result.stdout)

    def test_suite_inventory_matches_the_current_tracked_tree(self) -> None:
        result = self.run_runner("--suite-inventory-only")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("suite inventory", result.stdout)
        self.assertNotIn("STALE", result.stdout + result.stderr)
        self.assertNotIn("UNCLAIMED", result.stdout + result.stderr)

    def test_suite_inventory_discovers_hyphenated_test_prefix(self) -> None:
        """The motivating file shape must remain visible even when none exist."""
        runner = RUNNER.read_text(encoding="utf-8")
        match = re.search(
            r"^SUITE_INVENTORY_DISCOVERY='([^']+)'$", runner, re.MULTILINE
        )
        self.assertIsNotNone(match, "suite inventory discovery ERE is missing")
        probe = subprocess.run(
            ["grep", "-E", match.group(1)],
            input="scripts/test-hyphen-canary.sh\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), "scripts/test-hyphen-canary.sh")

    def test_suite_inventory_hyphenated_canary_is_a_real_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fake_git = Path(temp) / "git-with-canary"
            fake_git.write_text(
                "#!/usr/bin/env bash\n"
                "set -uo pipefail\n"
                "/usr/bin/git \"$@\" || exit $?\n"
                "if [[ \"$*\" == \"ls-files\" ]]; then\n"
                "  echo scripts/test-hyphen-canary.sh\n"
                "fi\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o755)
            env = {
                **os.environ,
                "SQUAD_SUITE_INVENTORY_GIT_UNDER_TEST": str(fake_git),
            }
            result = subprocess.run(
                ["bash", str(RUNNER), "--suite-inventory-only"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("scripts/test-hyphen-canary.sh", result.stderr)
        self.assertIn("claimed by no row", result.stderr)

    def test_suite_inventory_git_failure_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fake_git = Path(temp) / "git-fails"
            fake_git.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
            fake_git.chmod(0o755)
            env = {
                **os.environ,
                "SQUAD_SUITE_INVENTORY_GIT_UNDER_TEST": str(fake_git),
            }
            result = subprocess.run(
                ["bash", str(RUNNER), "--suite-inventory-only"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("BLOCKED: suite inventory", result.stderr)

    def test_sealed_clone_dependencies_use_the_repository_lockfiles(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn('uv sync --locked --project "$ROOT"', runner)
        self.assertIn('npm ci --prefix "$ROOT/moat" --no-audit --no-fund', runner)
        self.assertIn('UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/uv-cache}"', runner)
        self.assertIn("dependency:command:uv-or-python3.13", runner)
        self.assertIn("MOAT_NODE_MODULES", runner)

    def test_private_projection_suite_has_an_explicit_na_contract(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertNotIn("^scripts/test-[^/]+\\.sh$|", runner)
        self.assertIn(
            "^plugins/chrono-dedup/tests/test_[^/]+\\.py$|bin-test-private|",
            runner,
        )
        self.assertIn("profile:public-projection-withholds-private-dedup", runner)


if __name__ == "__main__":
    unittest.main()
