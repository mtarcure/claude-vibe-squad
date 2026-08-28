from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXPORT = ROOT / "tools/export"
sys.path.insert(0, str(EXPORT))

from projector import (  # noqa: E402
    _read_last_source_anchor,
    check_publish_provenance,
    format_publish_provenance,
)


class PublishProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.board = self.root / "_state/board-dispatch"
        self.board.mkdir(parents=True)
        self.git("init", "-q")
        self.git("config", "user.name", "Provenance Test")
        self.git("config", "user.email", "provenance@example.invalid")
        self.main_branch = self.git("branch", "--show-current")
        self.write("README.md", "base\n")
        self.commit("base")
        self.anchor = self.head()

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, subject: str, body: str | None = None) -> str:
        self.git("add", "-A")
        command = ["commit", "-q", "-m", subject]
        if body:
            command.extend(["-m", body])
        self.git(*command)
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def receipt(
        self,
        *,
        task: str,
        commit: str,
        paths: list[str],
        field: str = "worktree_integration",
        worker_head: str | None = None,
        base_commit: str | None = None,
    ) -> None:
        record: dict[str, object] = {
            "status": "integrated",
            "integration_commit": commit,
            "target_after": commit,
            "integrated_paths": paths,
        }
        if worker_head:
            record["worker_head"] = worker_head
        if base_commit:
            record["base_commit"] = base_commit
        payload = {
            "schema": "board-dispatch-receipt/v2",
            "task_id": task,
            field: record,
        }
        path = self.board / f"{task}.d-fixture.receipt.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

    def findings(self):
        return check_publish_provenance(
            self.root,
            anchor=self.anchor,
            source="HEAD",
            board_state=self.board,
        )

    def test_reports_direct_protected_commit_with_paths_and_ready_dispatch(self) -> None:
        self.write("scripts/python/runtime.py", "value = 1\n")
        commit = self.commit("coordinator change")

        rendered = format_publish_provenance(self.findings())

        self.assertIn(commit, rendered)
        self.assertIn('path: "scripts/python/runtime.py"', rendered)
        self.assertIn("bash scripts/send-task.sh coding", rendered)
        self.assertIn("backend-engineer --mode project", rendered)

    def test_ignores_unprotected_commits(self) -> None:
        self.write("docs/note.md", "documentation\n")
        self.commit("docs only")

        self.assertEqual(self.findings(), ())
        self.assertEqual(format_publish_provenance(()), "")

    def test_fast_forward_integration_receipt_binds_without_trailers(self) -> None:
        path = "scripts/python/lane.py"
        self.write(path, "value = 2\n")
        commit = self.commit("lane-authored fast-forward")
        self.receipt(task="TASK-2099-01-01-0001-lane", commit=commit, paths=[path])

        self.assertEqual(self.findings(), ())

    def test_merge_receipt_and_worker_trailers_bind(self) -> None:
        base = self.head()
        self.git("checkout", "-q", "-b", "worker")
        path = "bin/lane-tool"
        self.write(path, "#!/bin/sh\n")
        worker = self.commit("worker change")
        self.git("checkout", "-q", self.main_branch)
        self.git("merge", "--no-ff", "-q", "worker", "-m", "temporary merge")
        tree = self.git("rev-parse", "HEAD^{tree}")
        parent = self.git("rev-parse", "HEAD^2")
        self.git("reset", "--hard", "-q", base)
        task = "TASK-2099-01-01-0002-merge"
        message = f"board integrate {task}\n\nWorker-Head: {worker}\nWorker-Base: {base}\n"
        merged = subprocess.run(
            ["git", "commit-tree", tree, "-p", base, "-p", parent],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            input=message,
        ).stdout.strip()
        self.git("reset", "--hard", "-q", merged)
        self.receipt(
            task=task,
            commit=merged,
            paths=[path],
            worker_head=worker,
            base_commit=base,
        )

        self.assertEqual(self.findings(), ())

    def test_recovered_blocked_attempt_binds_and_path_mismatch_does_not(self) -> None:
        path = "tools/runtime/check.py"
        self.write(path, "value = 3\n")
        commit = self.commit("recovered worker change")
        task = "TASK-2099-01-01-0003-recovery"
        self.receipt(task=task, commit=commit, paths=[path], field="work_recovery")
        self.assertEqual(self.findings(), ())

        receipt = next(self.board.glob("*.receipt.json"))
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload["work_recovery"]["integrated_paths"] = ["docs/not-the-change.md"]
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual([finding[0] for finding in self.findings()], [commit])

    def test_reads_latest_source_anchor_across_publish_records(self) -> None:
        ledger = self.root / "ledger.jsonl"
        ledger.write_text(
            "\n".join(
                (
                    json.dumps({"source_sha": "a" * 40}),
                    json.dumps({"event": "publish", "published_tip": "b" * 40}),
                    json.dumps({"source_sha": "c" * 40}),
                )
            )
            + "\n",
            encoding="utf-8",
        )

        self.assertEqual(_read_last_source_anchor(ledger), "c" * 40)


if __name__ == "__main__":
    unittest.main()
