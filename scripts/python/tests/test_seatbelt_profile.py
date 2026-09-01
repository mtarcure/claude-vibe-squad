from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "python"))

import seatbelt_profile as seatbelt  # noqa: E402
import seatbelt_probe  # noqa: E402
from seatbelt_probe import ProbeEffect, ProbeSuiteResult, run_probe_suite  # noqa: E402


VERIFIED_HOST = seatbelt.HostCompatibility(
    sandbox_exec=Path("/usr/bin/sandbox-exec"),
    macos_build="25E253",
    canary_sha256="0" * 64,
)


def compile_for_test(spec: seatbelt.ProfileSpec) -> seatbelt.CompiledProfile:
    return seatbelt.compile_profile(
        spec,
        compatibility_verifier=lambda: VERIFIED_HOST,
    )


class AccountHomeValidationTests(unittest.TestCase):
    def test_synthetic_account_home_derives_all_lexical_lane_roots(self) -> None:
        script = """
import json
import os
import sys
import types

fake_pwd = types.ModuleType("pwd")
fake_pwd.getpwuid = lambda uid: types.SimpleNamespace(
    pw_dir=os.environ["SYNTHETIC_ACCOUNT_HOME"]
)
sys.modules["pwd"] = fake_pwd
import seatbelt_profile

print(json.dumps({
    "host_home": str(seatbelt_profile.HOST_HOME),
    "local_bin_root": str(seatbelt_profile.LOCAL_BIN_ROOT),
    "grok_bin_root": str(seatbelt_profile.GROK_BIN_ROOT),
    "uv_root": str(seatbelt_profile.UV_ROOT),
    "uv_tools_root": str(seatbelt_profile.UV_TOOLS_ROOT),
    "uv_python_root": str(seatbelt_profile.UV_PYTHON_ROOT),
    "claude": str(seatbelt_profile.LANE_CLI_PATHS["claude"]),
    "grok": str(seatbelt_profile.LANE_CLI_PATHS["grok"]),
    "kimi": str(seatbelt_profile.LANE_CLI_PATHS["kimi"]),
    "default_path": seatbelt_profile.DEFAULT_LANE_PATH,
}, sort_keys=True))
"""
        with tempfile.TemporaryDirectory() as directory:
            synthetic_home = Path(directory).resolve()
            environment = dict(os.environ)
            environment.update(
                {
                    "HOME": str(synthetic_home),
                    "PYTHONPATH": str(ROOT / "scripts" / "python"),
                    "SYNTHETIC_ACCOUNT_HOME": str(synthetic_home),
                }
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                env=environment,
                timeout=10,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        paths = json.loads(completed.stdout)
        local_bin_root = synthetic_home / ".local" / "bin"
        grok_bin_root = synthetic_home / ".grok" / "bin"
        uv_root = synthetic_home / ".local" / "share" / "uv"
        self.assertEqual(paths["host_home"], str(synthetic_home))
        self.assertEqual(paths["local_bin_root"], str(local_bin_root))
        self.assertEqual(paths["grok_bin_root"], str(grok_bin_root))
        self.assertEqual(paths["uv_root"], str(uv_root))
        self.assertEqual(paths["uv_tools_root"], str(uv_root / "tools"))
        self.assertEqual(paths["uv_python_root"], str(uv_root / "python"))
        self.assertEqual(paths["claude"], str(local_bin_root / "claude"))
        self.assertEqual(paths["grok"], str(grok_bin_root / "grok"))
        self.assertEqual(paths["kimi"], str(local_bin_root / "kimi"))
        self.assertTrue(
            paths["default_path"].startswith(f"{grok_bin_root}:{local_bin_root}:")
        )
        maintainer_home = "/" + "Users" + "/chrono"
        self.assertNotIn(maintainer_home, json.dumps(paths, sort_keys=True))

    def test_mismatched_or_relative_home_is_ignored_at_import(self) -> None:
        # $HOME is not authoritative: the passwd euid home is. A sandboxed
        # board spawn runs with a differing (or even relative) $HOME and must
        # still import cleanly, deriving HOST_HOME from the euid record rather
        # than raising. This guards against re-introducing the import-time
        # ProfileValidationError that broke every board launch.
        probe = (
            "import os, pwd, seatbelt_profile as s; "
            "assert str(s.HOST_HOME) == pwd.getpwuid(os.geteuid()).pw_dir, s.HOST_HOME"
        )
        with tempfile.TemporaryDirectory() as directory:
            mismatched_home = str(Path(directory).resolve())
            for environment_home in (mismatched_home, "relative-home"):
                with self.subTest(environment_home=environment_home):
                    environment = dict(os.environ)
                    environment.update(
                        {
                            "HOME": environment_home,
                            "PYTHONPATH": str(ROOT / "scripts" / "python"),
                        }
                    )
                    completed = subprocess.run(
                        [sys.executable, "-c", probe],
                        check=False,
                        capture_output=True,
                        text=True,
                        cwd=str(ROOT),
                        env=environment,
                        timeout=10,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_account_home_must_be_owned_by_effective_uid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            synthetic_home = Path(directory).resolve()
            with self.assertRaisesRegex(
                seatbelt.ProfileValidationError,
                "owned by the effective UID",
            ):
                seatbelt._validate_account_home(
                    synthetic_home,
                    effective_uid=os.geteuid() + 1,
                    environment_home=str(synthetic_home),
                )

    def test_board_trusted_and_strict_paths_share_the_validated_default(self) -> None:
        source = (ROOT / "bin" / "board-supervisor.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'candidate = os.environ.get("TRUSTED_HOST_PATH", DEFAULT_LANE_PATH)',
            source,
        )
        self.assertIn(
            'environment["PATH"] = _validated_trusted_host_path()',
            source,
        )
        self.assertIn(
            'prepared.environment["PATH"] = DEFAULT_LANE_PATH',
            source,
        )
        self.assertIn(
            "not Path(component).is_absolute()",
            source,
        )
        maintainer_home = "/" + "Users" + "/chrono"
        self.assertNotIn(maintainer_home, source)


class SeatbeltProfileCompilerTests(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: Seatbelt profile rendering uses Darwin profile semantics",
    )
    def test_profile_is_deny_default_and_grants_only_declared_operations(self) -> None:
        compiled = compile_for_test(
            seatbelt.ProfileSpec(
                read_paths=(ROOT / "docs",),
                write_paths=(ROOT / "_state",),
                executable_paths=(Path("/bin/sh"),),
                allow_fork=True,
                broker_port=43123,
            )
        )

        self.assertTrue(compiled.text.startswith("(version 1)\n(deny default)\n"))
        self.assertIn('(allow file-read*', compiled.text)
        self.assertIn('(allow file-write*', compiled.text)
        self.assertIn('(allow process-exec (literal "/bin/sh"))', compiled.text)
        self.assertIn("(allow process-fork)", compiled.text)
        self.assertIn(
            '(allow network-outbound (remote tcp "localhost:43123"))',
            compiled.text,
        )
        self.assertNotIn("127.0.0.1:43123", compiled.text)
        self.assertNotIn("(allow default)", compiled.text)
        self.assertNotIn("(allow network*)", compiled.text)
        self.assertNotIn('(subpath "/")', compiled.text)

    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: Seatbelt profile rendering uses Darwin profile semantics",
    )
    def test_profile_hash_is_deterministic_and_scope_bound(self) -> None:
        base = seatbelt.ProfileSpec(
            read_paths=(ROOT / "docs",),
            write_paths=(ROOT / "_state",),
            executable_paths=(Path("/bin/sh"),),
            broker_port=43123,
        )
        reordered = seatbelt.ProfileSpec(
            read_paths=(ROOT / "docs", ROOT / "docs"),
            write_paths=(ROOT / "_state",),
            executable_paths=(Path("/bin/sh"), Path("/bin/sh")),
            broker_port=43123,
        )
        changed = seatbelt.ProfileSpec(
            read_paths=(ROOT / "docs",),
            write_paths=(ROOT / "scripts" / "python",),
            executable_paths=(Path("/bin/sh"),),
            broker_port=43123,
        )

        first = compile_for_test(base)
        second = compile_for_test(base)
        canonical_duplicate = compile_for_test(reordered)
        scope_changed = compile_for_test(changed)

        self.assertEqual(first.text, second.text)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.sha256, canonical_duplicate.sha256)
        self.assertNotEqual(first.sha256, scope_changed.sha256)

    def test_paths_are_realpaths_and_identity_change_is_rejected(self) -> None:
        normalized = seatbelt.normalize_realpath(ROOT / "scripts" / "python")
        self.assertEqual(normalized.path, (ROOT / "scripts" / "python").resolve())

        before = mock.Mock(st_dev=1, st_ino=2, st_mode=0o040755)
        after = mock.Mock(st_dev=1, st_ino=3, st_mode=0o040755)
        stat_fn = mock.Mock(side_effect=(before, after))
        with self.assertRaises(seatbelt.PathIdentityError):
            seatbelt.normalize_realpath(
                ROOT / "scripts" / "python",
                stat_fn=stat_fn,
                realpath_fn=lambda value: str(value),
            )

    def test_invalid_broker_port_is_rejected(self) -> None:
        for port in (0, 65536, True):
            with self.subTest(port=port):
                with self.assertRaises(seatbelt.ProfileValidationError):
                    compile_for_test(
                        seatbelt.ProfileSpec(
                            read_paths=(ROOT / "docs",),
                            write_paths=(ROOT / "_state",),
                            executable_paths=(Path("/bin/sh"),),
                            broker_port=port,
                        )
                    )

    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: exercises Darwin Seatbelt profile compilation",
    )
    def test_root_read_scope_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            seatbelt.ProfileValidationError,
            "root read scope",
        ):
            compile_for_test(
                seatbelt.ProfileSpec(
                    read_paths=(Path("/"),),
                    write_paths=(ROOT / "_state",),
                    executable_paths=(Path("/bin/sh"),),
                )
            )

    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: exercises Darwin Seatbelt profile compilation",
    )
    def test_root_write_scope_and_non_executable_grant_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            seatbelt.ProfileValidationError,
            "root write scope",
        ):
            compile_for_test(
                seatbelt.ProfileSpec(
                    write_paths=(Path("/"),),
                    executable_paths=(Path("/bin/sh"),),
                )
            )

        with self.assertRaisesRegex(
            seatbelt.ProfileValidationError,
            "executable",
        ):
            compile_for_test(
                seatbelt.ProfileSpec(
                    write_paths=(ROOT / "_state",),
                    # Any existing non-executable file proves the point. This
                    # named a doc under docs/superpowers/plans/, and when that
                    # directory was deleted the fixture vanished -- so a security
                    # test started failing on a FileNotFoundError that had
                    # nothing to do with executable-bit validation. CLAUDE.md is
                    # load-bearing for the repo and cannot quietly disappear.
                    executable_paths=(ROOT / "CLAUDE.md",),
                )
            )

    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: Seatbelt profile rendering uses Darwin profile semantics",
    )
    def test_broker_port_is_bound_into_profile_hash(self) -> None:
        common = dict(
            read_paths=(ROOT / "docs",),
            write_paths=(ROOT / "_state",),
            executable_paths=(Path("/bin/sh"),),
        )
        first = compile_for_test(seatbelt.ProfileSpec(**common, broker_port=43123))
        second = compile_for_test(seatbelt.ProfileSpec(**common, broker_port=43124))
        self.assertNotEqual(first.sha256, second.sha256)

    def test_missing_or_renamed_sandbox_exec_fails_closed(self) -> None:
        with self.assertRaises(seatbelt.SandboxCompatibilityError):
            seatbelt.verify_sandbox_compatibility(
                sandbox_exec=ROOT / "not-sandbox-exec",
                build_reader=lambda: "25E253",
            )

    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: sandbox compatibility check requires the Darwin sandbox-exec host",
    )
    def test_unrecognized_host_build_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            seatbelt.SandboxCompatibilityError,
            "unrecognized macOS build",
        ):
            seatbelt.verify_sandbox_compatibility(
                build_reader=lambda: "UNKNOWN-BUILD",
                runner=mock.Mock(),
            )

    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: sandbox compatibility check requires the Darwin sandbox-exec host",
    )
    def test_failed_sandbox_canary_raises_typed_error(self) -> None:
        failed = mock.Mock(returncode=1, stdout="", stderr="canary denied")
        with self.assertRaisesRegex(
            seatbelt.SandboxCompatibilityError,
            "compatibility canary failed",
        ):
            seatbelt.verify_sandbox_compatibility(
                build_reader=lambda: "25E253",
                runner=mock.Mock(return_value=failed),
            )

    def test_compatibility_failure_emits_no_profile(self) -> None:
        failure = seatbelt.SandboxCompatibilityError("sandbox unavailable")
        verifier = mock.Mock(side_effect=failure)
        with mock.patch.object(seatbelt, "_render_profile") as render:
            with self.assertRaises(seatbelt.SandboxCompatibilityError):
                seatbelt.compile_profile(
                    seatbelt.ProfileSpec(
                        read_paths=(ROOT / "docs",),
                        write_paths=(ROOT / "_state",),
                        executable_paths=(Path("/bin/sh"),),
                        broker_port=43123,
                    ),
                    compatibility_verifier=verifier,
                )
        render.assert_not_called()

    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: exercises Darwin Seatbelt profile compilation",
    )
    def test_lane_derived_root_read_is_rejected_before_render(self) -> None:
        with (
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_executable_paths",
                return_value=(),
            ),
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_executable_aliases",
                return_value=(),
            ),
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_library_grants",
                return_value=((), (), ()),
            ),
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_read_paths",
                return_value=(Path("/"),),
            ),
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_read_literals",
                return_value=(),
            ),
            self.assertRaisesRegex(
                seatbelt.ProfileValidationError,
                "lane runtime read scope may not be root",
            ),
            seatbelt.scoped_lane_launch_profile(lane="kimi"),
        ):
            compile_for_test(
                seatbelt.ProfileSpec(
                    read_paths=(ROOT / "docs",),
                    write_paths=(ROOT / "_state",),
                    executable_paths=(Path("/bin/sh"),),
                )
            )

    def test_kimi_reads_exact_bounded_tool_and_python_distribution_roots(
        self,
    ) -> None:
        alias = seatbelt.LOCAL_BIN_ROOT / "kimi"
        entrypoint = seatbelt.UV_TOOLS_ROOT / "kimi-cli" / "bin" / "kimi"
        distribution = "cpython-3.13.5-macos-aarch64-none"
        interpreter = (
            seatbelt.UV_PYTHON_ROOT
            / distribution
            / "bin"
            / "python3"
        )

        def fake_realpath(value: object) -> str:
            return str(entrypoint if Path(value) == alias else value)

        with (
            mock.patch.dict(
                seatbelt.LANE_CLI_PATHS,
                {"kimi": alias},
                clear=True,
            ),
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_executable_paths",
                return_value=(entrypoint, interpreter),
            ),
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_library_grants",
                return_value=((), (), ()),
            ),
            mock.patch.object(
                seatbelt,
                "_shebang_interpreter",
                return_value=interpreter,
            ),
            mock.patch.object(
                seatbelt.os.path,
                "realpath",
                side_effect=fake_realpath,
            ),
        ):
            reads = seatbelt.installed_lane_cli_read_paths(
                lanes=("kimi",),
                include_offline=False,
            )
            literals = seatbelt.installed_lane_cli_read_literals(
                lanes=("kimi",),
                include_offline=False,
            )

        self.assertIn(seatbelt.UV_TOOLS_ROOT / "kimi-cli", reads)
        self.assertIn(seatbelt.UV_PYTHON_ROOT / distribution, reads)
        self.assertNotIn(Path("/"), reads)
        self.assertNotIn(Path("/"), literals)

    def test_unexpected_uv_relative_interpreter_is_rejected(self) -> None:
        alias = seatbelt.LOCAL_BIN_ROOT / "kimi"
        entrypoint = seatbelt.UV_TOOLS_ROOT / "kimi-cli" / "bin" / "kimi"
        interpreter = seatbelt.UV_ROOT / "unreviewed" / "bin" / "python3"

        def fake_realpath(value: object) -> str:
            return str(entrypoint if Path(value) == alias else value)

        with (
            mock.patch.dict(
                seatbelt.LANE_CLI_PATHS,
                {"kimi": alias},
                clear=True,
            ),
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_executable_paths",
                return_value=(entrypoint, interpreter),
            ),
            mock.patch.object(
                seatbelt,
                "installed_lane_cli_library_grants",
                return_value=((), (), ()),
            ),
            mock.patch.object(
                seatbelt,
                "_shebang_interpreter",
                return_value=interpreter,
            ),
            mock.patch.object(
                seatbelt.os.path,
                "realpath",
                side_effect=fake_realpath,
            ),
            self.assertRaisesRegex(
                seatbelt.ProfileValidationError,
                "outside the reviewed Python subtree",
            ),
        ):
            seatbelt.installed_lane_cli_read_paths(
                lanes=("kimi",),
                include_offline=False,
            )


class ProbeHarnessResultTests(unittest.TestCase):
    def test_probe_report_passes_only_when_every_effect_matches(self) -> None:
        success = ProbeEffect(True, 0, None, "", "", True)
        denied = ProbeEffect(False, 73, errno.EPERM, "", "", False)
        report = ProbeSuiteResult(
            fixture_root="fixture",
            deny_profile_sha256="a" * 64,
            broker_profile_sha256="b" * 64,
            declared_write=success,
            undeclared_write=denied,
            network_deny=denied,
            exact_broker_port=success,
            wrong_broker_port=denied,
        )
        self.assertTrue(report.passed)
        self.assertFalse(
            ProbeSuiteResult(
                **{
                    **report.__dict__,
                    "wrong_broker_port": ProbeEffect(True, 0, None, "", ""),
                }
            ).passed
        )


@unittest.skipUnless(
    sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file(),
    "real Seatbelt probes require macOS sandbox-exec",
)
class RealSeatbeltProbeTests(unittest.TestCase):
    def test_declared_write_denied_write_and_loopback_port_invariants(self) -> None:
        fixture_root = (
            ROOT
            / "_state"
            / "v2-finalization-2026-07-21-build"
            / "probe-fixtures"
            / f"unittest-{time.time_ns()}"
        )
        real_subprocess_run = subprocess.run

        def run_with_compiler_temp(*args: object, **kwargs: object):
            command = args[0] if args else kwargs.get("args")
            if (
                isinstance(command, (list, tuple))
                and command
                and command[0] == "/usr/bin/clang"
            ):
                environment = dict(kwargs.get("env") or {})
                environment["TMPDIR"] = tempfile.gettempdir()
                kwargs["env"] = environment
            return real_subprocess_run(*args, **kwargs)

        # Managed test runners may deny Darwin's confstr-backed temp lookup.
        # Give only the retained probe compiler a known writable temp root;
        # the compiled Seatbelt profiles and every effect probe remain real.
        with mock.patch.object(
            seatbelt_probe.subprocess,
            "run",
            side_effect=run_with_compiler_temp,
        ):
            result = run_probe_suite(fixture_root)

        self.assertTrue(result.declared_write.succeeded)
        self.assertTrue(result.declared_write.target_exists)
        self.assertFalse(result.undeclared_write.succeeded)
        self.assertEqual(result.undeclared_write.errno, errno.EPERM)
        self.assertFalse(result.undeclared_write.target_exists)
        self.assertFalse(result.network_deny.succeeded)
        self.assertEqual(result.network_deny.errno, errno.EPERM)
        self.assertTrue(result.exact_broker_port.succeeded)
        self.assertFalse(result.wrong_broker_port.succeeded)
        self.assertEqual(result.wrong_broker_port.errno, errno.EPERM)


if __name__ == "__main__":
    unittest.main()
