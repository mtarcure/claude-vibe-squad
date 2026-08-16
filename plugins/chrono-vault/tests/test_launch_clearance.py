from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCH_SCRIPT = REPO_ROOT / "bin" / "launch-squad.sh"
DOCTOR_SCRIPT = REPO_ROOT / "bin" / "doctor.sh"
NIGHTLY_SCRIPT = REPO_ROOT / "bin" / "run-nightly.sh"
CLEARANCE_EXPORT = "'export CHRONO_VAULT_CLEARANCE=restricted'"


class LaunchClearanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lines = LAUNCH_SCRIPT.read_text(encoding="utf-8").splitlines()

    def test_restricted_clearance_is_wired_only_to_chrono(self) -> None:
        clearance_lines = [
            line.strip()
            for line in self.lines
            if "tmux send-keys" in line and CLEARANCE_EXPORT in line
        ]
        expected = {
            'tmux send-keys -t "${SESSION}:chrono" '
            + CLEARANCE_EXPORT
            + " C-m",
        }

        self.assertEqual(len(clearance_lines), 1)
        self.assertEqual(set(clearance_lines), expected)
        self.assertFalse(
            any(
                target in line
                for target in (
                    "${GPT_CODEX_WIN}",
                    "${CLAUDE_WIN}",
                    "${GEMINI_WIN}",
                    "${KIMI_WIN}",
                )
                for line in clearance_lines
            )
        )

    def test_clearance_follows_each_pane_auth_command(self) -> None:
        pane_auth = (
            ("${SESSION}:chrono", "MEDIA_AUTH_PREFIX"),
        )
        for target, prefix in pane_auth:
            with self.subTest(target=target):
                auth = f'tmux send-keys -t "{target}" "${{{prefix}}}" C-m'
                clearance = (
                    f'tmux send-keys -t "{target}" {CLEARANCE_EXPORT} C-m'
                )
                auth_index = self.lines.index(auth)
                self.assertEqual(self.lines[auth_index + 1], clearance)

    def test_launcher_checks_one_concrete_root_before_doctor_or_tmux(self) -> None:
        text = LAUNCH_SCRIPT.read_text(encoding="utf-8")
        root_export = text.index(
            'export CHRONO_VAULT_ROOT="${CHRONO_VAULT_ROOT:-${HOME}/Obsidian-Chrono}"'
        )
        root_check = text.index('"${VAULT_ROOT}/bin/doctor.sh" --check-private-vault-root')
        doctor = text.index("# Pre-flight health gate")
        tmux = text.index("tmux new-session")
        self.assertLess(root_export, root_check)
        self.assertLess(root_check, doctor)
        self.assertLess(root_check, tmux)

    def test_only_chrono_media_prefix_remains(self) -> None:
        assignments = {
            line.partition("=")[0]: line
            for line in self.lines
            if line.startswith(("AUTH_PREFIX=", "MEDIA_AUTH_PREFIX=", "GEMINI_AUTH_PREFIX="))
        }
        self.assertEqual(set(assignments), {"MEDIA_AUTH_PREFIX"})
        self.assertIn("CHRONO_VAULT_ROOT", assignments["MEDIA_AUTH_PREFIX"])
        self.assertIn("CHRONO_VAULT_ROOT_SHELL", assignments["MEDIA_AUTH_PREFIX"])
        self.assertNotIn("Obsidian-Chrono", assignments["MEDIA_AUTH_PREFIX"])
        self.assertNotIn("CHRONO_VAULT_CLEARANCE", assignments["MEDIA_AUTH_PREFIX"])

    def test_watcher_child_gets_the_same_safely_quoted_root(self) -> None:
        text = LAUNCH_SCRIPT.read_text(encoding="utf-8")
        quote = text.index(
            "printf -v CHRONO_VAULT_ROOT_SHELL '%q' \"${CHRONO_VAULT_ROOT}\""
        )
        reattach = text.index('if tmux has-session -t "${SESSION}"')
        child = next(
            line.strip()
            for line in self.lines
            if line.strip().startswith('child_command="exec env ')
        )
        self.assertLess(quote, reattach)
        self.assertIn(
            "CHRONO_VAULT_ROOT=${CHRONO_VAULT_ROOT_SHELL}", child
        )
        self.assertNotIn("Obsidian-Chrono", child)

    def test_help_does_not_require_a_private_vault(self) -> None:
        environment = dict(os.environ)
        environment.pop("CHRONO_VAULT_ROOT", None)
        completed = subprocess.run(
            ["bash", str(LAUNCH_SCRIPT), "--help"],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_nightly_projects_the_existing_default_root(self) -> None:
        self.assertIn(
            'export CHRONO_VAULT_ROOT="${CHRONO_VAULT_ROOT:-${HOME}/Obsidian-Chrono}"',
            NIGHTLY_SCRIPT.read_text(encoding="utf-8"),
        )


class PrivateVaultDoctorCheckTests(unittest.TestCase):
    def run_check(self, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(DOCTOR_SCRIPT), "--check-private-vault-root"],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_check_mode_accepts_valid_external_root_without_printing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".chrono-vault").write_text(
                json.dumps({"vault_id": "p4-check", "schema_version": 1}),
                encoding="utf-8",
            )
            completed = self.run_check(
                {**os.environ, "CHRONO_VAULT_ROOT": str(root)}
            )
            output = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 0, output)
            self.assertNotIn(str(root), output)

    def test_check_mode_rejects_missing_and_public_roots_without_writing(self) -> None:
        for root in (None, str(REPO_ROOT)):
            with self.subTest(root=root):
                environment = dict(os.environ)
                if root is None:
                    environment.pop("CHRONO_VAULT_ROOT", None)
                else:
                    environment["CHRONO_VAULT_ROOT"] = root
                completed = self.run_check(environment)
                output = completed.stdout + completed.stderr
                self.assertNotEqual(completed.returncode, 0, output)
                self.assertNotIn(str(REPO_ROOT), output)

    def test_check_mode_precedes_doctor_log_creation(self) -> None:
        text = DOCTOR_SCRIPT.read_text(encoding="utf-8")
        mode = text.index('"${1:-}" == "--check-private-vault-root"')
        mkdir = text.index('mkdir -p "$(dirname "${DOCTOR_LOG}")"')
        self.assertLess(mode, mkdir)
        self.assertIn("python3 -B", text[:mkdir])


if __name__ == "__main__":
    unittest.main()
