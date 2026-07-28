from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = REPO_ROOT / "scripts" / "python"
sys.path.insert(0, str(PYTHON_DIR))

from held_action_gate import (  # noqa: E402
    HeldActionDenied,
    HeldActionStore,
    mint_token,
)
from held_effect_wrapper import (  # noqa: E402
    delete_from_main,
    git_push,
    outreach,
    provider_billing,
)


TASK_ID = "TASK-2026-07-22-0635-v2-rightsized-golive"
ATTEMPT_ID = "d-baa435dbc4924d2c90562483f40bd650"
SIGNING_KEY = b"right-sized-held-effect-test-key"


def _token(*, category: str, target: str):
    return mint_token(
        category=category,
        target=target,
        task_id=TASK_ID,
        attempt_id=ATTEMPT_ID,
        issued_at=100,
        expires_at=200,
        signing_key=SIGNING_KEY,
    )


class RightsizedGoliveTests(unittest.TestCase):
    def test_supervisor_documents_trusted_default_and_strict_opt_in(self) -> None:
        completed = subprocess.run(
            [str(REPO_ROOT / "bin" / "board-supervisor.sh"), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("trusted-launch CONTEXT.json", completed.stdout)
        self.assertIn("trusted-launch --strict CONTEXT.json", completed.stdout)
        self.assertIn("DEFAULT trusted path", completed.stdout)

    def test_git_push_is_denied_before_runner_without_token(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command):
            calls.append(tuple(command))
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            with self.assertRaisesRegex(HeldActionDenied, "operator-approval token"):
                git_push(
                    repo=tmp_path,
                    remote="origin",
                    refspec="HEAD:main",
                    task_id=TASK_ID,
                    attempt_id=ATTEMPT_ID,
                    token=None,
                    store=HeldActionStore(tmp_path / "gate"),
                    signing_key=SIGNING_KEY,
                    now=150,
                    runner=runner,
                )
        self.assertEqual(calls, [])


    def test_git_push_consumes_token_before_effect_and_replay_is_denied(
        self,
    ) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command):
            calls.append(tuple(command))
            return subprocess.CompletedProcess(command, 1, "", "remote rejected")

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            target = f"{tmp_path.resolve()}:origin:HEAD:refs/heads/main"
            token = _token(category="public-push", target=target)
            first = git_push(
                repo=tmp_path,
                remote="origin",
                refspec="HEAD:refs/heads/main",
                task_id=TASK_ID,
                attempt_id=ATTEMPT_ID,
                token=token,
                store=HeldActionStore(tmp_path / "gate"),
                signing_key=SIGNING_KEY,
                now=150,
                runner=runner,
            )
            self.assertEqual(first.returncode, 1)
            self.assertEqual(
                calls,
                [
                    (
                        "/usr/bin/git",
                        "-C",
                        str(tmp_path.resolve()),
                        "push",
                        "--",
                        "origin",
                        "HEAD:refs/heads/main",
                    )
                ],
            )

            with self.assertRaisesRegex(HeldActionDenied, "already consumed"):
                git_push(
                    repo=tmp_path,
                    remote="origin",
                    refspec="HEAD:refs/heads/main",
                    task_id=TASK_ID,
                    attempt_id=ATTEMPT_ID,
                    token=token,
                    store=HeldActionStore(tmp_path / "gate"),
                    signing_key=SIGNING_KEY,
                    now=151,
                    runner=runner,
                )
            self.assertEqual(len(calls), 1)

    def test_delete_provider_billing_and_outreach_are_target_bound(
        self,
    ) -> None:
        calls: list[str] = []

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            file_path = tmp_path / "tracked.txt"
            file_path.write_text("kept until authorized\n", encoding="utf-8")

            delete_target = f"{tmp_path.resolve()}:refs/heads/main:tracked.txt"
            delete_from_main(
                repo=tmp_path,
                relative_path="tracked.txt",
                task_id=TASK_ID,
                attempt_id=ATTEMPT_ID,
                token=_token(category="delete-from-main", target=delete_target),
                store=HeldActionStore(tmp_path / "delete-gate"),
                signing_key=SIGNING_KEY,
                now=150,
                remover=lambda path: calls.append(f"delete:{path.name}"),
            )

            billing_target = "openai:subscription:invoice-2026-07"
            provider_billing(
                provider="openai",
                account="subscription",
                operation="invoice-2026-07",
                task_id=TASK_ID,
                attempt_id=ATTEMPT_ID,
                token=_token(category="spend", target=billing_target),
                store=HeldActionStore(tmp_path / "spend-gate"),
                signing_key=SIGNING_KEY,
                now=150,
                performer=lambda: calls.append("billing"),
            )

            outreach_target = "email:operator@example.invalid:status-update"
            outreach(
                channel="email",
                recipient="operator@example.invalid",
                campaign="status-update",
                task_id=TASK_ID,
                attempt_id=ATTEMPT_ID,
                token=_token(category="outreach", target=outreach_target),
                store=HeldActionStore(tmp_path / "outreach-gate"),
                signing_key=SIGNING_KEY,
                now=150,
                performer=lambda: calls.append("outreach"),
            )

        self.assertEqual(calls, ["delete:tracked.txt", "billing", "outreach"])

    def test_wrapper_cli_denies_git_push_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PYTHON_DIR / "held_effect_wrapper.py"),
                    "git-push",
                    "--repo",
                    str(tmp_path),
                    "--remote",
                    "origin",
                    "--refspec",
                    "HEAD:main",
                    "--task-id",
                    TASK_ID,
                    "--attempt-id",
                    ATTEMPT_ID,
                    "--state-dir",
                    str(tmp_path / "gate"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 74)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "denied")
        self.assertEqual(payload["category"], "public-push")
        self.assertIn("operator-approval token", payload["reason"])


if __name__ == "__main__":
    unittest.main()
