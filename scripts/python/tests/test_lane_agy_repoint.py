from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402
import seatbelt_profile as seatbelt  # noqa: E402


class AgyLaneRepointTests(unittest.TestCase):
    def test_gemini_lane_points_to_exact_agy_native_entrypoint(self) -> None:
        self.assertEqual(
            seatbelt.LANE_CLI_PATHS["gemini"],
            seatbelt.LOCAL_BIN_ROOT / "agy",
        )

    def test_regular_native_entrypoint_needs_no_alias_or_shebang_grant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "agy"
            executable.write_bytes(b"native-fixture\x00")
            executable.chmod(0o700)
            with mock.patch.dict(
                seatbelt.LANE_CLI_PATHS,
                {"gemini": executable},
                clear=True,
            ):
                paths = seatbelt.installed_lane_cli_executable_paths(
                    lanes=("gemini",),
                    include_offline=False,
                )
                normalized = tuple(
                    seatbelt.normalize_realpath(path) for path in paths
                )
                aliases = seatbelt.installed_lane_cli_executable_aliases(
                    normalized,
                    lanes=("gemini",),
                )

            self.assertEqual(paths, (executable.resolve(),))
            self.assertEqual(aliases, ())
            self.assertIsNone(seatbelt._shebang_interpreter(executable))

    def test_board_launcher_uses_only_supported_agy_flags(self) -> None:
        source = (ROOT / "bin" / "board-supervisor.sh").read_text(
            encoding="utf-8"
        )
        launcher = source.split("    def gemini_ordered_launcher(", 1)[1].split(
            "\n    def kimi_role_launcher(", 1
        )[0]
        for retired in (
            "--allowed-mcp-server-names",
            "--allowed-tools",
            "--approval-mode",
            "--include-directories",
            "--skip-trust",
        ):
            self.assertNotIn(retired, launcher)
        self.assertIn('"--add-dir"', launcher)
        self.assertIn('"--output-format",\n            "text"', launcher)
        self.assertIn('"--print",\n            concise_prompt', launcher)
        self.assertIn("agent_system_context.rstrip()", launcher)
        self.assertIn(dcb.AGY_EXTERNAL_MCP_MAX_CALLS_FIELD, launcher)

    def test_board_does_not_override_agy_login_with_gemini_api_key(self) -> None:
        source = (ROOT / "bin" / "board-supervisor.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            'environment["GEMINI_API_KEY"] = load_gemini_api_key()',
            source,
        )
        # The old acknowledgment helper remains for compatibility history but
        # the agy launch path no longer mutates Gemini CLI acknowledgment state.
        self.assertEqual(source.count("acknowledge_gemini_agents("), 1)

    def test_bootstrap_registers_all_four_chrono_mcps_with_agy(self) -> None:
        source = (ROOT / "scripts" / "bootstrap-mcps.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("AGY_LIST", source)
        self.assertIn("register_agy()", source)
        self.assertIn('local agy_args=("mcp" "add")', source)
        self.assertIn('agy "${agy_args[@]}"', source)
        self.assertIn('register_agy "${name}" "${args_str}" "${env_vars}"', source)
        self.assertIn("AGY_REGISTRATION_FAILED=1", source)
        for name in (
            "chrono-vault",
            "chrono-obsidian",
            "chrono-research-arsenal",
            "chrono-media-studio",
        ):
            self.assertIn(f'"{name}|', source)


if __name__ == "__main__":
    unittest.main()
