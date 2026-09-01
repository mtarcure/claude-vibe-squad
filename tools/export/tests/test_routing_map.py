"""Tests for the TSV-derived routing-map generator and its drift check."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EXPORT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPORT_DIR.parents[1]
GENERATOR = EXPORT_DIR / "build_routing_map.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("build_routing_map", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR_MODULE = _load_generator()

HEADER = "\t".join(
    (
        "specialist",
        "source_namespace",
        "capability_class",
        "safety_level",
        "primary_lane",
        "backup_lane",
        "escalate_lane",
        "review_lane",
    )
)


def _row(
    specialist: str,
    namespace: str,
    role_class: str,
    safety: str,
    primary: str,
    backup: str,
    escalate: str,
    review: str,
) -> str:
    return "\t".join(
        (specialist, namespace, role_class, safety, primary, backup, escalate, review)
    )


class RoutingMapGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / GENERATOR_MODULE.SOURCE
        self.lane_policy = self.root / GENERATOR_MODULE.LANE_POLICY
        self.target = self.root / GENERATOR_MODULE.OUTPUT
        self.source.parent.mkdir(parents=True)
        self.target.parent.mkdir(parents=True)
        self._write_lane_policy()
        self._write_source("implementation")
        self.target.write_text(
            "<title>Static shell</title>\n"
            "<style>.kept { color: green; }</style>\n"
            f"{GENERATOR_MODULE.BEGIN_MARKER}\n"
            "stale hand-maintained rows\n"
            f"{GENERATOR_MODULE.END_MARKER}\n"
            "<!-- static suffix -->\n",
            encoding="utf-8",
        )

    def _write_lane_policy(self, *, include_grok: bool = False) -> None:
        lanes = [
            ("codex", "allow", "Heavy-hitter implementation lane."),
            ("claude", "allow", "Heavy-hitter judgment lane."),
            ("kimi", "deny", "Kimi is deny-default."),
        ]
        if include_grok:
            lanes.insert(2, ("grok", "deny", "Grok is deny-default."))
        rows = ["record_kind\tsubject\tvalue\tscope\tnotes"]
        rows.extend(
            f"primary_default\t{lane}\t{primary_default}\tall\t{notes}"
            for lane, primary_default, notes in lanes
        )
        rows.extend(
            f"vocabulary\troute_lane\t{lane}\tall\t{lane.title()} lane."
            for lane, _, _ in lanes
        )
        self.lane_policy.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def _write_source(self, alpha_class: str, *, alpha_lane: str = "codex") -> None:
        self.source.write_text(
            "\n".join(
                (
                    HEADER,
                    _row(
                        "alpha",
                        "coding",
                        alpha_class,
                        "medium",
                        alpha_lane,
                        "claude",
                        alpha_lane,
                        "claude",
                    ),
                    _row(
                        "beta",
                        "shared",
                        "judgment",
                        "high",
                        "kimi",
                        "codex",
                        "kimi",
                        "codex",
                    ),
                )
            )
            + "\n",
            encoding="utf-8",
        )

    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GENERATOR), "--root", str(self.root), *extra],
            capture_output=True,
            text=True,
        )

    def test_generate_preserves_static_shell_and_then_check_passes(self) -> None:
        generated = self._run()
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)

        page = self.target.read_text(encoding="utf-8")
        self.assertIn("<style>.kept { color: green; }</style>", page)
        self.assertIn("<!-- static suffix -->", page)
        self.assertNotIn("stale hand-maintained rows", page)
        self.assertIn("2 specialists", page)
        self.assertIn("CODING|alpha|implementation|medium|codex|claude|claude", page)
        self.assertIn("SHARED|beta|judgment|high|kimi|codex|codex", page)
        self.assertIn(r'raw.split("\n")', page)

        checked = self._run("--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("is current (2 specialists)", checked.stdout)

    def test_check_fails_on_tsv_drift_without_rewriting_page(self) -> None:
        self.assertEqual(self._run().returncode, 0)
        unchanged_page = self.target.read_text(encoding="utf-8")
        self._write_source("judgment")

        stale = self._run("--check")
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        self.assertIn("is stale", stale.stderr)
        self.assertEqual(self.target.read_text(encoding="utf-8"), unchanged_page)

    def test_registered_grok_lane_is_rendered(self) -> None:
        self._write_lane_policy(include_grok=True)
        self._write_source("judgment", alpha_lane="grok")

        generated = self._run()
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        page = self.target.read_text(encoding="utf-8")
        self.assertIn("CODING|alpha|judgment|medium|grok|claude|claude", page)
        self.assertIn('<span class="lane-name">Grok</span>', page)

    def test_unregistered_lane_fails_closed(self) -> None:
        self._write_source("judgment", alpha_lane="grok")

        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("unknown primary_lane value 'grok'", result.stderr)

    def test_missing_generated_markers_fails_closed(self) -> None:
        self.target.write_text("<style>static only</style>\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("must contain exactly one", result.stderr)

    def test_empty_tsv_fails_closed(self) -> None:
        self.source.write_text(HEADER + "\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("contains no specialist rows", result.stderr)

    def test_committed_routing_map_is_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--root", str(REPO_ROOT), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
