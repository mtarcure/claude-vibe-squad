#!/usr/bin/env python3
"""Focused red/green/indeterminate controls for the P13 batch checks."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402

# See dispatch_checkout: send-task.sh refuses to dispatch from a linked
# worktree, and that refusal runs before the guards this suite tests -- so
# without this the result depends on checkout shape, not on behaviour.
# The helper returns the root unchanged in a main checkout.
ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])

_DOCTOR_HELPERS = (
    Path("bin") / "doctor-log-home.sh",
    Path("shared") / "repo-root.sh",
)

_EMPTY_PS = """#!/bin/bash
# Pass doctor's liveness canary, then return a genuinely empty process table.
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

_DENY_ARTIFACT_FIND = """#!/bin/bash
# The artifact target exists, but its enumerator cannot read it. Other doctor
# find calls retain their real behavior so this is a single-fault control.
for argument in "$@"; do
    case "$argument" in
        */_state/blog-summaries)
            printf 'find: artifact target unreadable\\n' >&2
            exit 1
            ;;
    esac
done
exec "$DOCTOR_REAL_FIND" "$@"
"""


def run_bash(script: Path, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(script)],
        cwd=ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


class GraduationScanTriStateTest(unittest.TestCase):
    def run_scan(self, ledger: str | None, *, jq_bin: str = "jq"):
        with tempfile.TemporaryDirectory(prefix="graduation-scan-") as temp:
            root = Path(temp)
            patterns = root / "patterns.jsonl"
            candidates = root / "candidates.md"
            if ledger is not None:
                patterns.write_text(ledger, encoding="utf-8")
            result = run_bash(
                ROOT / "bin/graduation-scan.sh",
                env={
                    "GRADUATION_PATTERNS_UNDER_TEST": str(patterns),
                    "GRADUATION_CANDIDATES_UNDER_TEST": str(candidates),
                    "GRADUATION_JQ_UNDER_TEST": jq_bin,
                },
            )
            report = candidates.read_text(encoding="utf-8") if candidates.exists() else ""
            return result, report

    def test_absent_or_malformed_ledger_is_indeterminate(self):
        for ledger in (None, "{not-json}\n", '{"ts": 3}\n'):
            with self.subTest(ledger=ledger):
                result, report = self.run_scan(ledger)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("COULD NOT DETERMINE", report)

    def test_missing_parser_is_indeterminate(self):
        result, report = self.run_scan("", jq_bin="/definitely/missing/jq")
        self.assertEqual(result.returncode, 2)
        self.assertIn("COULD NOT DETERMINE", report)

    def test_empty_completed_scan_passes(self):
        result, report = self.run_scan("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No graduation candidates", report)
        self.assertIn("PASS:", result.stdout)

    def test_threshold_hit_is_a_finding(self):
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [
            {
                "ts": now,
                "routine_signature": "same-routine",
                "engagement_id": f"engagement-{index}",
                "specialist": "devops-engineer",
            }
            for index in range(3)
        ]
        result, report = self.run_scan(
            "".join(json.dumps(row) + "\n" for row in rows)
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("same-routine", report)
        self.assertIn("FAIL:", result.stderr)


class DispatchToolkitTriStateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dispatch-toolkit-")
        self.root = Path(self.temporary.name)
        self.inventory = self.root / "inventory"
        self.inventory.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def write_toolkit(self, codex_expected: str = "alpha") -> Path:
        toolkit = self.root / "dispatch-toolkit.sh"
        blocks = {
            "gpt-codex": codex_expected,
            "claude": "bravo",
            "gemini": "charlie",
            "kimi": "delta",
        }
        toolkit.write_text(
            "\n".join(
                f"    {lane})\n"
                "## Expected Model Lane Tool Surface\n"
                f"This lane expects `{name}`. Later tools include `not_a_server`.\n"
                "        ;;"
                for lane, name in blocks.items()
            )
            + "\n",
            encoding="utf-8",
        )
        return toolkit

    def write_clean_inventories(self):
        (self.inventory / "codex.txt").write_text(
            json.dumps([{"name": "alpha"}]), encoding="utf-8"
        )
        (self.inventory / "claude.txt").write_text(
            "Checking MCP server health…\n"
            "bravo: /bin/bravo - ✔ Connected\n",
            encoding="utf-8",
        )
        (self.inventory / "gemini.txt").write_text(
            "Configured MCP servers:\n"
            "✓ charlie: /bin/charlie (stdio) - Connected\n",
            encoding="utf-8",
        )
        (self.inventory / "kimi.txt").write_text(
            "delta /bin/delta enabled\n", encoding="utf-8"
        )

    def run_verify(self, toolkit: Path):
        return run_bash(
            ROOT / "bin/dispatch-toolkit-verify.sh",
            env={
                "DISPATCH_TOOLKIT_UNDER_TEST": str(toolkit),
                "DISPATCH_TOOLKIT_MCP_LIST_DIR_UNDER_TEST": str(self.inventory),
            },
        )

    def test_clean_exact_sets_pass(self):
        self.write_clean_inventories()
        result = self.run_verify(self.write_toolkit())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS:", result.stdout)

    def test_novel_name_mismatch_fails(self):
        self.write_clean_inventories()
        result = self.run_verify(self.write_toolkit("future_mcp.v2"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("future_mcp.v2", result.stdout)
        self.assertIn("FAIL:", result.stdout)

    def test_inventory_that_cannot_run_is_indeterminate(self):
        self.write_clean_inventories()
        (self.inventory / "kimi.txt").unlink()
        result = self.run_verify(self.write_toolkit())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("COULD NOT DETERMINE", result.stdout)


class WriteScopeGuardTriStateTest(unittest.TestCase):
    def make_repro(self, body: str) -> Path:
        path = Path(self.temporary.name) / "repro.sh"
        path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return path

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wsguard-c4-")

    def tearDown(self):
        self.temporary.cleanup()

    def run_verify(self, repro: Path):
        return run_bash(
            ROOT / "tools/wsguard/verify.sh",
            env={"WSGUARD_REPRO_UNDER_TEST": str(repro)},
        )

    def test_completed_silent_twin_passes(self):
        result = self.run_verify(self.make_repro("echo WSGUARD_REPRO_COMPLETE\n"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_completed_warning_twin_fails(self):
        result = self.run_verify(
            self.make_repro(
                "echo 'WARNING: write_scope path is gitignored'\n"
                "echo WSGUARD_REPRO_COMPLETE\n"
            )
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_failed_twin_is_indeterminate(self):
        result = self.run_verify(self.make_repro("exit 42\n"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("COULD NOT DETERMINE", result.stdout)


class DoctorTargetContractTest(unittest.TestCase):
    def run_doctor(self, *, deny_artifact_find: bool = False):
        with tempfile.TemporaryDirectory(prefix="doctor-target-contract-") as temp:
            fixture = Path(temp)
            root = fixture / "root"
            (root / "bin").mkdir(parents=True)
            (root / "shared").mkdir(parents=True)

            shutil.copy2(ROOT / "bin" / "doctor.sh", root / "bin" / "doctor.sh")
            (root / "bin" / "doctor.sh").chmod(0o755)
            for helper in _DOCTOR_HELPERS:
                shutil.copy2(ROOT / helper, root / helper)

            subprocess.run(
                ["git", "init", "-q"], cwd=root, check=True, capture_output=True
            )

            home = fixture / "home"
            local_bin = home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            ps_stub = local_bin / "ps"
            ps_stub.write_text(_EMPTY_PS, encoding="utf-8")
            ps_stub.chmod(0o755)

            environment = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "VAULT_ROOT": str(root),
                "TERM": "dumb",
                "LANG": "C",
                "TMPDIR": str(fixture),
            }
            environment.pop("CHRONO_DOCTOR_LOG_DIR", None)
            environment.pop("CHRONO_VAULT_ROOT", None)

            if deny_artifact_find:
                (root / "_state" / "blog-summaries").mkdir(parents=True)
                find_stub = local_bin / "find"
                find_stub.write_text(_DENY_ARTIFACT_FIND, encoding="utf-8")
                find_stub.chmod(0o755)
                real_find = shutil.which("find")
                self.assertIsNotNone(real_find, "test control requires a real find")
                environment["DOCTOR_REAL_FIND"] = str(real_find)

            result = subprocess.run(
                ["/bin/bash", str(root / "bin" / "doctor.sh")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            summaries = sorted(
                (home / ".local/state/chrono-vault/doctor-logs").glob(
                    "*-summary.json"
                )
            )
            self.assertEqual(
                len(summaries),
                1,
                f"doctor did not emit one summary: {result.stdout}{result.stderr}",
            )
            summary = json.loads(summaries[0].read_text(encoding="utf-8"))
            return result, summary

    def test_absent_and_unreadable_present_targets_have_distinct_exit_codes(self):
        zero_state, zero_summary = self.run_doctor()
        self.assertEqual(
            zero_state.returncode, 0, zero_state.stdout + zero_state.stderr
        )
        self.assertGreater(zero_summary["absent_input_count"], 0)
        self.assertEqual(
            zero_summary["gate_unknown_count"], 0, zero_summary["gate_unknowns"]
        )
        self.assertIn("what a fresh install looks like", zero_state.stdout)

        unreadable, unreadable_summary = self.run_doctor(deny_artifact_find=True)
        self.assertEqual(
            unreadable.returncode, 2, unreadable.stdout + unreadable.stderr
        )
        self.assertIn(
            "token-bleed artifact scan failed",
            unreadable_summary["gate_unknowns"],
        )
        self.assertIn("input was there", unreadable.stdout)


if __name__ == "__main__":
    unittest.main()
