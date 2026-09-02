from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


EXPORT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPORT_DIR))

from gitleaks_filter import filter_report, project_public_paths  # noqa: E402


ALLOWLIST = EXPORT_DIR / "policy" / "gitleaks-fingerprints.json"


class GitleaksFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.report = self.root / "raw.json"

    def _write_finding(self, *, path: str, secret: str, rule_id: str = "generic-api-key") -> None:
        self.report.write_text(
            json.dumps(
                [
                    {
                        "RuleID": rule_id,
                        "Description": "test finding",
                        "StartLine": 1,
                        "EndLine": 1,
                        "File": path,
                        "Secret": secret,
                        "Match": f"key='{secret}'",
                        "Fingerprint": f"{path}:{rule_id}:1",
                    }
                ]
            ),
            encoding="utf-8",
        )

    def test_exact_rule_path_and_secret_hash_is_allowed(self) -> None:
        exact_secret = "bm25" + "_weights"
        self._write_finding(path="plugins/chrono-vault/recall.py", secret=exact_secret)
        unresolved, allowed, total = filter_report(
            root=self.root,
            report_path=self.report,
            allowlist_path=ALLOWLIST,
        )
        self.assertEqual((unresolved, allowed, total), ([], 1, 1))

    def test_same_secret_elsewhere_or_changed_secret_at_path_is_not_allowed(self) -> None:
        exact_secret = "bm25" + "_weights"
        self._write_finding(path="README.md", secret=exact_secret)
        unresolved, allowed, _total = filter_report(
            root=self.root,
            report_path=self.report,
            allowlist_path=ALLOWLIST,
        )
        self.assertEqual(allowed, 0)
        self.assertEqual(len(unresolved), 1)
        self.assertNotIn("Secret", unresolved[0])
        self.assertNotIn("Match", unresolved[0])

        self._write_finding(
            path="plugins/chrono-vault/recall.py",
            secret=exact_secret + "_changed",
        )
        changed, allowed, _total = filter_report(
            root=self.root,
            report_path=self.report,
            allowlist_path=ALLOWLIST,
        )
        self.assertEqual(allowed, 0)
        self.assertEqual(len(changed), 1)

    def test_project_public_paths_excludes_private_and_unknown_tracked_paths(self) -> None:
        tracked_nul = self.root / "tracked.nul"
        projected_nul = self.root / "projected.nul"
        tracked_nul.write_bytes(
            b"README.md\0_state/private.log\0novel-surface/unknown.txt\0"
        )

        counts = project_public_paths(
            tracked_nul_path=tracked_nul,
            policy_path=EXPORT_DIR / "policy" / "path-policy.json",
            output_path=projected_nul,
        )

        self.assertEqual(counts, (3, 1, 2))
        self.assertEqual(projected_nul.read_bytes(), b"README.md\0")


if __name__ == "__main__":
    unittest.main()
