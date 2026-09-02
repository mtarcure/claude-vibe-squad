#!/usr/bin/env python3
"""Behavior checks for operator text that must not query the live squad."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import doctor_fixture


ROOT = Path(__file__).resolve().parents[3]


TMUX_FIXTURE = """#!/bin/bash
case "$1" in
    list-panes) printf '0: fixture pane\\n' ;;
    display-message) printf '160\\n' ;;
esac
exit 0
"""


class SidebarOperatorTextTest(unittest.TestCase):
    def test_sidebar_reports_the_live_specialist_swarm(self):
        """The sidebar is a task dashboard, not a standing lane roster."""
        with tempfile.TemporaryDirectory(prefix="sidebar-text-") as temp:
            fixture = Path(temp)
            (fixture / "bin").mkdir()
            (fixture / "shared").mkdir()
            shutil.copy2(ROOT / "bin" / "sidebar.sh", fixture / "bin" / "sidebar.sh")
            shutil.copy2(
                ROOT / "shared" / "repo-root.sh", fixture / "shared" / "repo-root.sh"
            )
            local_bin = fixture / "stub-bin"
            local_bin.mkdir()
            tmux = local_bin / "tmux"
            tmux.write_text(TMUX_FIXTURE, encoding="utf-8")
            tmux.chmod(0o755)

            result = subprocess.run(
                ["/bin/bash", str(fixture / "bin" / "sidebar.sh")],
                env={
                    **os.environ,
                    "PATH": f"{local_bin}:/usr/bin:/bin",
                    "VAULT_ROOT": str(fixture),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Dashboard: live specialist swarm.", result.stdout)
        self.assertNotIn("Dashboard: gpt-codex", result.stdout)


class SetupDocumentationAuthorityTests(unittest.TestCase):
    def test_setup_docs_use_the_launch_dependency_authority(self) -> None:
        for relative in ("docs/getting-started.md", "docs/install/provider-clis.md"):
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("source shared/launch-dependencies.sh", source)
                self.assertIn('${SQUAD_REQUIRED_COMMANDS[@]}', source)

    def test_rewritten_runtime_docs_name_every_required_lane_cli(self) -> None:
        required = set(doctor_fixture.launch_dependencies(ROOT))
        non_lane = {"tmux", "fswatch", "jq", "curl", "uv"}
        lane_clis = required - non_lane
        self.assertTrue(lane_clis, "launch dependency authority exposed no lane CLIs")
        for relative in (
            "chrono/operator-setup.md",
            "docs/architecture.md",
            "docs/getting-started.md",
            "docs/install/provider-clis.md",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                for cli in sorted(lane_clis):
                    self.assertIn(
                        f"`{cli}`",
                        source,
                        f"{relative} omits the {cli} lane required by "
                        "shared/launch-dependencies.sh",
                    )

    def test_effort_transport_table_names_every_profile_lane(self) -> None:
        with (ROOT / "shared" / "registries" / "profiles.tsv").open(
            encoding="utf-8", newline=""
        ) as stream:
            lanes = {row["lane"] for row in csv.DictReader(stream, delimiter="\t")}
        lifecycle = (ROOT / "shared" / "lifecycle.md").read_text(encoding="utf-8")
        section = lifecycle.split("## 7. Effort tiering", 1)[1].split("## 8.", 1)[0]
        for lane in sorted(lanes):
            with self.subTest(lane=lane):
                self.assertIn(f"`{lane}`", section)


if __name__ == "__main__":
    unittest.main()
