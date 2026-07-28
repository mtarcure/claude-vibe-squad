"""Wave R3 — blocked settlement must publish an envelope for the common shape.

``publish_blocked_completion`` wrote a blocked *artifact* at ``return_artifact``
and then a blocked *envelope* at ``departments/<ns>/outbox/<id>-response.md``.
For the packet shape used by nearly every task those two paths are the same
file, so the second write hit ``_atomic_publish``'s no-clobber guard and the
whole settlement failed with ``blocked response envelope destination already
differs``. The artifact write had already landed, leaving a frontmatter-less
file where the reconciler expects an envelope -- which reads as status ``''``
and never settles, stranding the task in-flight with its write_scope held.

These tests pin the collapse (one envelope, no artifact write) without
weakening any containment or no-clobber guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402
import registry_reconciler as rr  # noqa: E402


TASK_ID = "TASK-2026-07-26-2031-r3-blocked-envelope"
NAMESPACE = "coding"
OUTBOX_RELATIVE = f"departments/{NAMESPACE}/outbox/{TASK_ID}-response.md"
REASON = "detached board supervisor status blocked exit 75"


class BlockedEnvelopeCollisionTests(unittest.TestCase):
    """The collapse itself: identical paths publish exactly one envelope."""

    def _publish(self, root: Path, return_artifact: str) -> dict[str, object]:
        return dcb.publish_blocked_completion(
            repo_root=root,
            task_id=TASK_ID,
            lane="claude",
            return_artifact=return_artifact,
            compatibility_namespace=NAMESPACE,
            reason=REASON,
        )

    def _repo(self, directory: str) -> Path:
        # resolve(): macOS hands out /var/... tempdirs that the builder reports
        # back in their real /private/var/... form.
        root = Path(directory).resolve() / "repo"
        (root / "departments" / NAMESPACE / "outbox").mkdir(parents=True)
        return root

    def test_artifact_equal_to_outbox_path_publishes_one_blocked_envelope(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)

            receipt = self._publish(root, OUTBOX_RELATIVE)

            destination = root / OUTBOX_RELATIVE
            self.assertEqual(receipt["status"], "blocked")
            self.assertEqual(receipt["artifact_path"], str(destination))
            self.assertEqual(receipt["envelope_path"], str(destination))
            body = destination.read_text(encoding="utf-8")
            self.assertTrue(body.startswith("---\n"), body[:40])
            self.assertIn("status: blocked", body)
            self.assertIn(f"return_artifact: {OUTBOX_RELATIVE}", body)
            self.assertIn(REASON, body)
            # The collapsed write is the envelope, never the bare artifact.
            self.assertNotIn("# Board dispatch blocked", body)
            self.assertEqual(
                sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                       if p.is_file()),
                [OUTBOX_RELATIVE],
            )

    def test_collapsed_envelope_satisfies_the_reconciler_contract(self) -> None:
        """The recipient contract: the reconciler must be able to settle it."""

        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)

            self._publish(root, OUTBOX_RELATIVE)

            status = rr.response_status(root / OUTBOX_RELATIVE)
            self.assertEqual(status, "blocked")
            self.assertTrue(rr.valid_response_status(status))

    def test_collapsed_publication_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)

            first = self._publish(root, OUTBOX_RELATIVE)
            before = (root / OUTBOX_RELATIVE).read_bytes()
            second = self._publish(root, OUTBOX_RELATIVE)

            self.assertFalse(first["envelope_idempotent"])
            self.assertFalse(first["artifact_idempotent"])
            self.assertTrue(second["envelope_idempotent"])
            self.assertTrue(second["artifact_idempotent"])
            self.assertEqual((root / OUTBOX_RELATIVE).read_bytes(), before)

    def test_cli_settles_the_common_packet_shape(self) -> None:
        """board-supervisor.sh reaches this through the `blocked` subcommand."""

        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(PYTHON_DIR / "dispatch_context_builder.py"),
                    "blocked",
                    "--repo-root", str(root),
                    "--task-id", TASK_ID,
                    "--lane", "claude",
                    "--return-artifact", OUTBOX_RELATIVE,
                    "--compatibility-namespace", NAMESPACE,
                    "--reason", REASON,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn("already differs", completed.stderr)
            receipt = json.loads(completed.stdout)
            self.assertEqual(receipt["status"], "blocked")
            self.assertIn("status: blocked", (root / OUTBOX_RELATIVE).read_text())


class BlockedEnvelopeGuardsPreservedTests(unittest.TestCase):
    """Everything the collapse must NOT weaken."""

    def _publish(self, root: Path, return_artifact: str) -> dict[str, object]:
        return dcb.publish_blocked_completion(
            repo_root=root,
            task_id=TASK_ID,
            lane="claude",
            return_artifact=return_artifact,
            compatibility_namespace=NAMESPACE,
            reason=REASON,
        )

    def _repo(self, directory: str) -> Path:
        # resolve(): macOS hands out /var/... tempdirs that the builder reports
        # back in their real /private/var/... form.
        root = Path(directory).resolve() / "repo"
        (root / "departments" / NAMESPACE / "outbox").mkdir(parents=True)
        return root

    def test_distinct_return_artifact_still_writes_both(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)

            receipt = self._publish(root, "_state/cutover-canary/blocked.md")

            artifact = root / "_state" / "cutover-canary" / "blocked.md"
            envelope = root / OUTBOX_RELATIVE
            self.assertEqual(receipt["artifact_path"], str(artifact))
            self.assertEqual(receipt["envelope_path"], str(envelope))
            self.assertNotEqual(receipt["artifact_path"], receipt["envelope_path"])
            self.assertIn("# Board dispatch blocked", artifact.read_text())
            self.assertIn("status: blocked", envelope.read_text())
            self.assertIn(
                "return_artifact: _state/cutover-canary/blocked.md",
                envelope.read_text(),
            )

    def test_absolute_return_artifact_is_still_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)
            outside = root.parent / "escaped.md"

            with self.assertRaises(dcb.DispatchContextError) as caught:
                self._publish(root, str(outside))

            self.assertIn("unsafe path", str(caught.exception))
            self.assertFalse(outside.exists())
            self.assertFalse((root / OUTBOX_RELATIVE).exists())

    def test_traversing_return_artifact_is_still_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)

            with self.assertRaises(dcb.DispatchContextError) as caught:
                self._publish(root, "departments/../../escaped.md")

            self.assertIn("traversal", str(caught.exception))
            self.assertFalse((root.parent / "escaped.md").exists())
            self.assertFalse((root / OUTBOX_RELATIVE).exists())

    def test_symlinked_outbox_destination_is_still_refused(self) -> None:
        """A symlinked response path must not be followed out of the repo."""

        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)
            outside = root.parent / "symlink-target.md"
            (root / OUTBOX_RELATIVE).symlink_to(outside)

            with self.assertRaises(dcb.DispatchContextError) as caught:
                self._publish(root, OUTBOX_RELATIVE)

            self.assertIn("symlink", str(caught.exception))
            self.assertFalse(outside.exists())

    def test_conflicting_existing_response_is_still_refused(self) -> None:
        """No-clobber holds: differing bytes at the collapsed path still raise."""

        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(directory)
            destination = root / OUTBOX_RELATIVE
            destination.write_text("a real worker response\n", encoding="utf-8")

            with self.assertRaises(dcb.DispatchContextError) as caught:
                self._publish(root, OUTBOX_RELATIVE)

            self.assertIn("already differs", str(caught.exception))
            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                "a real worker response\n",
            )


if __name__ == "__main__":
    unittest.main()
