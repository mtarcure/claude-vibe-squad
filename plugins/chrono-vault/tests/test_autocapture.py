from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import autocapture  # noqa: E402
import recall as vault_recall  # noqa: E402


def parse_note(path: Path) -> tuple[dict[str, object], str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    closing = lines.index("---", 1)
    frontmatter: dict[str, object] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(": ")
        if not separator:
            raise AssertionError(f"malformed canonical note line: {line!r}")
        frontmatter[key] = json.loads(value)
    return frontmatter, "\n".join(lines[closing + 1 :]).lstrip("\n")


class AutoCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-autocapture-vault-"))
        )
        self.mailbox_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-autocapture-mailbox-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.mailbox_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "autocapture-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _response(
        self,
        namespace: str,
        task_id: str,
        *,
        specialist: str,
        status: str,
        mode: str | None,
        verdict: str,
        body: str,
    ) -> tuple[Path, bytes]:
        outbox = self.mailbox_root / "departments" / namespace / "outbox"
        outbox.mkdir(parents=True)
        path = outbox / f"{task_id}-response.md"
        mode_line = "" if mode is None else f"mode: {json.dumps(mode)}\n"
        raw = (
            "---\n"
            f"specialist: {json.dumps(specialist)}\n"
            f"status: {json.dumps(status)}\n"
            f"{mode_line}"
            f"in_reply_to: {json.dumps(task_id)}\n"
            f"verdict: {json.dumps(verdict)}\n"
            'artifacts: ["reports/result.md", "poc/repro.py"]\n'
            "---\n\n"
            f"{body}\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        return path, raw

    def test_bounty_response_creates_one_restricted_recallable_candidate(self) -> None:
        path, raw = self._response(
            "security",
            "TASK-2026-07-14-9000-deadbeef",
            specialist="exploit-developer",
            status="needs_review",
            mode="bounty",
            verdict="EmitterForgeVerdict confirms an unbacked mint",
            body=(
                "# Verdict\n"
                "EmitterForgeVerdict is reproducible through the SVM emitter.\n\n"
                + ("bounded-evidence " * 200)
            ),
        )

        result = autocapture.capture_response(str(path))

        self.assertTrue(result["captured"])
        note_path = next((self.vault_root / "notes" / "learning").glob("*.md"))
        frontmatter, body = parse_note(note_path)
        self.assertEqual(frontmatter["id"], result["note_id"])
        self.assertEqual(frontmatter["status"], "candidate")
        self.assertEqual(frontmatter["sensitivity"], "restricted")
        self.assertEqual(
            frontmatter["source_task"],
            "TASK-2026-07-14-9000-deadbeef",
        )
        self.assertEqual(
            frontmatter["source_artifact_hash"],
            f"sha256:{hashlib.sha256(raw).hexdigest()}",
        )
        self.assertEqual(
            frontmatter["keywords"],
            ["specialist-exploit-developer", "status-needs_review"],
        )
        self.assertIn("EmitterForgeVerdict", frontmatter["title"])
        self.assertIn("EmitterForgeVerdict", body)
        self.assertLessEqual(len(body), autocapture.MAX_SUMMARY_CHARS)

        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_CLEARANCE": "restricted"},
        ):
            recalled = vault_recall.recall("EmitterForgeVerdict")
        self.assertIn(result["note_id"], [row["id"] for row in recalled["results"]])

    def test_envelope_without_specialist_derives_from_packet(self) -> None:
        # The canonical completion envelope (shared/protocol.md) omits
        # `specialist`; autocapture must still capture, deriving it from the
        # original task packet rather than dropping the completion.
        namespace = "coding"
        task_id = "TASK-2026-07-15-1853-73988d8b"
        outbox = self.mailbox_root / "departments" / namespace / "outbox"
        outbox.mkdir(parents=True)
        path = outbox / f"{task_id}-response.md"
        path.write_bytes(
            (
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {json.dumps(task_id)}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: needs_review\n"
                "return_artifact: /tmp/report.md\n"
                "---\n\n"
                "Implemented atomic inbox publication in bin/send-task.sh.\n"
            ).encode("utf-8")
        )
        archive = self.mailbox_root / "departments" / namespace / "archive"
        archive.mkdir(parents=True)
        (archive / f"{task_id}.md").write_text(
            "---\n"
            f"id: {task_id}\n"
            "specialist: site-reliability-engineer\n"
            "status: done\n"
            "---\n\nbody\n",
            encoding="utf-8",
        )

        result = autocapture.capture_response(str(path))

        self.assertTrue(result["captured"])
        note_path = next((self.vault_root / "notes" / "learning").glob("*.md"))
        frontmatter, _ = parse_note(note_path)
        self.assertIn(
            "specialist-site-reliability-engineer", frontmatter["keywords"]
        )

    def test_envelope_without_specialist_or_packet_defaults(self) -> None:
        namespace = "coding"
        task_id = "TASK-2026-07-15-1900-abcdef01"
        outbox = self.mailbox_root / "departments" / namespace / "outbox"
        outbox.mkdir(parents=True)
        path = outbox / f"{task_id}-response.md"
        path.write_bytes(
            (
                "---\n"
                f"in_response_to: {json.dumps(task_id)}\n"
                "status: complete\n"
                "---\n\nDid the thing.\n"
            ).encode("utf-8")
        )

        result = autocapture.capture_response(str(path))

        self.assertTrue(result["captured"])
        note_path = next((self.vault_root / "notes" / "learning").glob("*.md"))
        frontmatter, _ = parse_note(note_path)
        self.assertIn("specialist-unknown-specialist", frontmatter["keywords"])

    def test_general_response_is_internal_and_exact_reprocessing_is_idempotent(self) -> None:
        path, _ = self._response(
            "coding",
            "TASK-2026-07-14-9001-cafefeed",
            specialist="ai-engineer",
            status="complete",
            mode="build",
            verdict="GeneralQueueToken hook is green",
            body="GeneralQueueToken records a bounded learning.",
        )

        first = autocapture.capture_response(str(path))
        second = autocapture.capture_response(str(path))

        self.assertTrue(first["captured"])
        self.assertFalse(second["captured"])
        self.assertEqual(second["reason"], "duplicate")
        self.assertEqual(second["note_id"], first["note_id"])
        notes = list((self.vault_root / "notes" / "learning").glob("*.md"))
        self.assertEqual(len(notes), 1)
        frontmatter, _ = parse_note(notes[0])
        self.assertEqual(frontmatter["sensitivity"], "internal")

    def test_unknown_namespace_fails_safe_to_restricted(self) -> None:
        path, _ = self._response(
            "mystery",
            "TASK-2026-07-14-9002-1234abcd",
            specialist="ai-engineer",
            status="complete",
            mode="build",
            verdict="UnknownRouteToken completed",
            body="UnknownRouteToken came from an unrecognized source namespace.",
        )

        result = autocapture.capture_response(str(path))

        self.assertTrue(result["captured"])
        note_path = next((self.vault_root / "notes" / "learning").glob("*.md"))
        frontmatter, _ = parse_note(note_path)
        self.assertEqual(frontmatter["sensitivity"], "restricted")

    def test_missing_mode_is_captured_with_restricted_fallback(self) -> None:
        path, _ = self._response(
            "coding",
            "TASK-2026-07-14-9004-5678abcd",
            specialist="ai-engineer",
            status="needs_review",
            mode=None,
            verdict="LegacyResponseToken completed",
            body="LegacyResponseToken came from a response without mode metadata.",
        )

        result = autocapture.capture_response(str(path))

        self.assertTrue(result["captured"])
        note_path = next((self.vault_root / "notes" / "learning").glob("*.md"))
        frontmatter, _ = parse_note(note_path)
        self.assertEqual(frontmatter["target"], "unknown")
        self.assertEqual(frontmatter["sensitivity"], "restricted")

    def test_malformed_and_non_response_files_are_skipped_without_writes(self) -> None:
        outbox = self.mailbox_root / "departments" / "coding" / "outbox"
        outbox.mkdir(parents=True)
        malformed = outbox / "TASK-2026-07-14-9003-ffffffff-response.md"
        malformed.write_text("not frontmatter\n", encoding="utf-8")
        unrelated = outbox / "notes.md"
        unrelated.write_text("---\nstatus: complete\n---\n", encoding="utf-8")

        malformed_result = autocapture.capture_response(str(malformed))
        unrelated_result = autocapture.capture_response(str(unrelated))

        self.assertFalse(malformed_result["captured"])
        self.assertEqual(malformed_result["reason"], "malformed_frontmatter")
        self.assertFalse(unrelated_result["captured"])
        self.assertEqual(unrelated_result["reason"], "not_response")
        self.assertFalse((self.vault_root / "notes").exists())

    def test_watcher_has_non_blocking_guarded_autocapture_hook(self) -> None:
        watcher = REPO_ROOT / "bin" / "outbox-watcher.sh"
        syntax = subprocess.run(
            ["bash", "-n", str(watcher)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        source = watcher.read_text(encoding="utf-8")
        self.assertIn("autocapture_response_best_effort()", source)
        self.assertIn("resolve_vault_root", source)
        self.assertIn('autocapture_response_best_effort "$path" &', source)


if __name__ == "__main__":
    unittest.main()
