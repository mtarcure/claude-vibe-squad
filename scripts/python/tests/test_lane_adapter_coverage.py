from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "scripts" / "python" / "lane_adapter_registry.py"
GENERATED_MARKER = "lane-capability-registry/v1"
SOURCE_SHA_PATTERN = re.compile(
    r"(?m)^(capability_source_sha256\s*[:=]\s*)(\"?)[^\"\n]+(\"?)$"
)
REPRESENTATIVE_ADAPTERS = {
    "claude": Path("model-lanes/claude/.claude/agents/accessibility-engineer.md"),
    "gemini": Path("model-lanes/gemini/.gemini/agents/accessibility-engineer.md"),
    "gpt-codex": Path(
        "model-lanes/gpt-codex/.codex/agents/accessibility-engineer.toml"
    ),
    "kimi": Path("model-lanes/kimi/.kimi/agents/experimental-attacker.yaml"),
}


class LaneAdapterCoverageTests(unittest.TestCase):
    def test_check_rejects_capability_source_sha_drift_per_lane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            for source in ("model-lanes", "shared", "departments"):
                shutil.copytree(ROOT / source, temporary_root / source)

            for lane, relative in REPRESENTATIVE_ADAPTERS.items():
                with self.subTest(lane=lane):
                    adapter = temporary_root / relative
                    original = adapter.read_text(encoding="utf-8")
                    self.assertIn(GENERATED_MARKER, original)

                    def stale_sha(match: re.Match[str]) -> str:
                        quote = match.group(2) or match.group(3)
                        return f"{match.group(1)}{quote}deadbeef{quote}"

                    drifted, replacements = SOURCE_SHA_PATTERN.subn(
                        stale_sha,
                        original,
                        count=1,
                    )
                    self.assertEqual(replacements, 1)
                    adapter.write_text(drifted, encoding="utf-8")
                    try:
                        result = subprocess.run(
                            [
                                "python3",
                                str(REGISTRY),
                                "--repo-root",
                                str(temporary_root),
                                "--check",
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                        )
                    finally:
                        adapter.write_text(original, encoding="utf-8")
                    self.assertNotEqual(
                        result.returncode,
                        0,
                        msg=f"{lane} drift was not rejected: {result.stdout}",
                    )
                    self.assertIn(f"projection:{lane}:{adapter.stem}", result.stdout)
                    self.assertIn("stale capability source metadata", result.stdout)


if __name__ == "__main__":
    unittest.main()
