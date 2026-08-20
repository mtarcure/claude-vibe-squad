"""The episodic tier (spec 13, Task 12).

Autocapture output that fails Stage 2's bar -- refused by the mechanical
filter, or lost to a broken or timed-out distiller -- is preserved for audit
and replay in an episodic tier that recall does not index.

**The one fact this whole file exists to pin:** that tier lives under the
repo's `_state/`, never under `CHRONO_VAULT_ROOT`. Obsidian's "Excluded
files" setting only hides files from parts of the UI -- it does not stop
indexing or parsing -- so an in-vault episodic tier would slow Obsidian while
contributing nothing to recall. The negative assertion (nothing lands under
the vault) matters more than the positive one: it is what stops a future
refactor from quietly moving this back in.

Hermetic throughout: no live model call, no network. The vault and the
episodic spool are both redirected into per-test tempdirs so the suite never
touches `~/Obsidian-Chrono` or this repo's real `_state/`.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import autocapture  # noqa: E402
from autocapture import DistillationFailed  # noqa: E402


class LocationIsMechanicalTests(unittest.TestCase):
    """The location is a fixed path shape, not something a mock can hide."""

    def test_the_spool_dir_is_under_state_never_under_notes_or_episodic_pending(
        self,
    ) -> None:
        self.assertEqual(autocapture.EPISODIC_SPOOL_DIR, Path("_state") / "episodic")

    def test_the_resolver_is_repo_root_relative_unpatched(self) -> None:
        # No mocking here -- this is the real REPO_ROOT this module resolved
        # at import time, proving the default (not just a test double) is
        # the repo, not the vault.
        self.assertEqual(
            autocapture._episodic_root(), REPO_ROOT / "_state" / "episodic"
        )


class EpisodicTierTests(unittest.TestCase):
    """`capture_response` end to end, with the vault and the spool in
    separate tempdirs so a leak of one into the other cannot hide."""

    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-episodic-vault-"))
        )
        self.mailbox_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-episodic-mailbox-"))
        )
        self.episodic_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-episodic-state-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.mailbox_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.episodic_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "episodic-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.episodic_patch = mock.patch.object(
            autocapture, "_episodic_root", lambda: self.episodic_root
        )
        self.episodic_patch.start()
        self.addCleanup(self.episodic_patch.stop)
        # Redirected for the same reason `_episodic_root` is: a distillation
        # failure below records one row, and unredirected that row lands in
        # the operator's real `_state/`. Test residue in the live tree is
        # exactly what this suite is otherwise careful not to leave.
        self.failure_log = self.mailbox_root / "autocapture-failures.jsonl"
        self.failure_patch = mock.patch.object(
            autocapture, "_failure_log_path", lambda: self.failure_log
        )
        self.failure_patch.start()
        self.addCleanup(self.failure_patch.stop)
        self.env = mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.vault_root),
                "CHRONO_AUTOCAPTURE_DISTILL": "off",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _write_response(
        self, *, task_id: str, body: str, verdict: str = ""
    ) -> Path:
        outbox = self.mailbox_root / "departments" / "coding" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{task_id}-response.md"
        path.write_text(
            "---\n"
            f"in_response_to: {json.dumps(task_id)}\n"
            'specialist: "systems-engineer"\n'
            'status: "complete"\n'
            'mode: "build"\n'
            f"verdict: {json.dumps(verdict)}\n"
            "---\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return path

    def _vault_files(self) -> list[Path]:
        """Every regular file under the vault, excluding the pre-existing
        sentinel setUp writes -- so a check for "nothing new landed here"
        does not trip on fixture setup itself."""
        found: list[Path] = []
        for root, _dirs, files in os.walk(self.vault_root):
            for name in files:
                candidate = Path(root) / name
                if candidate != self.vault_root / ".chrono-vault":
                    found.append(candidate)
        return found

    def _spooled_lines(self) -> list[dict]:
        entries: list[dict] = []
        for path in sorted(self.episodic_root.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    # -- The test the task exists for --------------------------------------

    def test_a_refused_capture_lands_in_the_repo_tier_and_never_in_the_vault(
        self,
    ) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-19-0001-episodic", body="APPROVE"
        )

        result = autocapture.capture_response(str(path))

        self.assertFalse(result["captured"])
        self.assertEqual(result["reason"], "refused:bare_verdict")

        # Positive half: the raw material has a home.
        spool_files = sorted(self.episodic_root.glob("*.jsonl"))
        self.assertEqual(len(spool_files), 1, spool_files)
        entries = self._spooled_lines()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["raw_body"], "APPROVE")
        self.assertEqual(entries[0]["source_task"], "TASK-2026-08-19-0001-episodic")

        # Negative half, the one that matters: nothing exists under the
        # vault. Not "no note" -- no file at all, anywhere in the tree.
        self.assertEqual(self._vault_files(), [])

    def test_a_refusal_still_spools_when_the_vault_root_is_unreachable(self) -> None:
        # Vault resolution is deferred past the spool and the filter (see
        # capture_response): a refusal never needs the vault at all, so an
        # unset or broken CHRONO_VAULT_ROOT cannot turn into a lost capture
        # for anything that was going to be refused anyway.
        path = self._write_response(
            task_id="TASK-2026-08-19-0008-episodic", body="APPROVE"
        )
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONO_VAULT_ROOT", None)
            result = autocapture.capture_response(str(path))

        self.assertFalse(result["captured"])
        self.assertEqual(result["reason"], "refused:bare_verdict")
        self.assertEqual(len(self._spooled_lines()), 1)

    def test_a_distillation_failure_also_lands_in_the_repo_tier(self) -> None:
        # "A failed or timed-out distillation must also land its raw capture
        # here" -- losing a capture to a broken model call is this plan's
        # own defect class.
        path = self._write_response(
            task_id="TASK-2026-08-19-0002-episodic",
            body="A substantive paragraph describing a real root cause, well "
            "over the minimum length the mechanical filter requires.",
        )

        def broken(capture_fields, context):
            raise DistillationFailed("distiller timed out after 120s")

        with mock.patch.dict(os.environ, {"CHRONO_AUTOCAPTURE_DISTILL": "on"}):
            result = autocapture.capture_response(str(path), distiller=broken)

        self.assertFalse(result["captured"])
        self.assertTrue(str(result["reason"]).startswith("distillation_failed:"))
        entries = self._spooled_lines()
        self.assertEqual(len(entries), 1)
        self.assertIn("substantive paragraph", entries[0]["raw_body"])
        self.assertEqual(self._vault_files(), [])

    def test_a_successful_capture_still_writes_only_to_the_vault_notes_tree(
        self,
    ) -> None:
        # The episodic spool is unconditional (spec 12's operator decision:
        # raw output goes to episodic ALWAYS), but the *semantic* note is
        # vault-only -- the two tiers never share a write target.
        path = self._write_response(
            task_id="TASK-2026-08-19-0003-episodic",
            body="A substantive paragraph describing a real root cause, well "
            "over the minimum length the mechanical filter requires.",
        )

        result = autocapture.capture_response(str(path))

        self.assertTrue(result["captured"], result)
        # The vault gains its ordinary record() artifacts (the note itself
        # plus its lock/audit/index bookkeeping) -- none of that is the
        # episodic tier's concern. What matters here is the negative: no
        # JSONL spool file, the episodic tier's own shape, ever appears
        # inside the vault tree.
        note_files = list((self.vault_root / "notes" / "learning").glob("*.md"))
        self.assertEqual(len(note_files), 1, note_files)
        self.assertEqual(list(self.vault_root.rglob("*.jsonl")), [])
        self.assertEqual(len(self._spooled_lines()), 1)

    def test_the_spool_file_is_named_for_the_utc_capture_date(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-19-0004-episodic", body="APPROVE"
        )
        autocapture.capture_response(str(path))
        files = list(self.episodic_root.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        entries = self._spooled_lines()
        expected_name = entries[0]["captured_at"][:10] + ".jsonl"
        self.assertEqual(files[0].name, expected_name)

    def test_repeated_captures_on_the_same_day_append_one_file(self) -> None:
        first = self._write_response(
            task_id="TASK-2026-08-19-0005-episodic", body="APPROVE"
        )
        second = self._write_response(
            task_id="TASK-2026-08-19-0006-episodic", body="REJECT"
        )
        autocapture.capture_response(str(first))
        autocapture.capture_response(str(second))
        files = list(self.episodic_root.glob("*.jsonl"))
        self.assertEqual(len(files), 1, files)
        self.assertEqual(len(self._spooled_lines()), 2)

    def test_spool_file_and_directory_are_private(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-19-0007-episodic", body="APPROVE"
        )
        autocapture.capture_response(str(path))
        self.assertEqual(
            self.episodic_root.stat().st_mode & 0o777,
            0o700,
        )
        files = list(self.episodic_root.glob("*.jsonl"))
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
