from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT = REPO_ROOT / "scripts" / "audit-orphans.sh"


class OrphanAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="chrono-orphan-audit-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for relative in (
            "plugins/chrono-vault",
            "shared/specialists",
            "departments/coding/specialists",
        ):
            (self.root / relative).mkdir(parents=True)
        (self.root / "plugins/chrono-vault/mcp_server.py").write_text(
            "def recall(query):\n    return canonical_recall(query)\n",
            encoding="utf-8",
        )
        (self.root / "shared/tool-catalog.md").write_text(
            "# Tools\n\n- `chrono-vault:recall`\n",
            encoding="utf-8",
        )
        (self.root / "shared/specialist-runtime-map.tsv").write_text(
            "specialist\trequired_tools\nfixture\t[chrono-vault]\n",
            encoding="utf-8",
        )
        (self.root / "departments/coding/specialists/fixture.md").write_text(
            "# Fixture\n\nUse `chrono-vault:recall`.\n",
            encoding="utf-8",
        )

    def _run(self, root: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["ORPHAN_AUDIT_ROOT"] = str(root)
        return subprocess.run(
            ["bash", str(AUDIT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_clean_fixture_passes_and_injected_orphans_fail(self) -> None:
        clean = self._run(self.root)
        self.assertEqual(clean.returncode, 0, clean.stderr or clean.stdout)

        specialist = self.root / "departments/coding/specialists/fixture.md"
        original = specialist.read_text(encoding="utf-8")
        for orphan in (
            "chrono-vault:kg_query",
            "chrono-vault:read_specialist",
            "chrono-vault:write_specialist",
            "chrono-vault:obsidian_search",
        ):
            with self.subTest(orphan=orphan):
                specialist.write_text(
                    original + f"Call the removed `{orphan}` tool.\n",
                    encoding="utf-8",
                )
                dirty = self._run(self.root)

                self.assertNotEqual(dirty.returncode, 0)
                self.assertIn(orphan.split(":")[-1], dirty.stdout + dirty.stderr)

    def test_repository_has_no_live_orphan_references(self) -> None:
        result = self._run(REPO_ROOT)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
