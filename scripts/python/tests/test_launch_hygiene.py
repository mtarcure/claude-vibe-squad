#!/usr/bin/env python3
"""Invariant tests for V2 supervisor launch hygiene."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import launch_hygiene as hygiene  # noqa: E402


FIXTURE_ROOT = ROOT / "_state" / "v2-finalization-2026-07-21-build" / "test-fixtures"


def retained_fixture(label: str) -> Path:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{label}-", dir=FIXTURE_ROOT))


class WritableScopeAuditTests(unittest.TestCase):
    def test_hardlink_in_writable_tree_is_rejected(self) -> None:
        root = retained_fixture("hardlink")
        original = root / "original.txt"
        alias = root / "alias.txt"
        original.write_text("sentinel", encoding="utf-8")
        os.link(original, alias)

        with self.assertRaisesRegex(hygiene.HygieneError, "hardlink"):
            hygiene.audit_writable_scopes((root,))

    def test_single_link_regular_file_scope_is_audited(self) -> None:
        root = retained_fixture("regular-file")
        writable = root / "result.md"
        writable.write_text("", encoding="utf-8")
        scopes = hygiene.audit_writable_scopes((writable,))
        try:
            hygiene.reaudit_writable_scopes(scopes)
            self.assertEqual(scopes[0].path, writable)
        finally:
            hygiene.close_writable_scopes(scopes)

    def test_symlink_device_and_fifo_are_rejected(self) -> None:
        symlink_root = retained_fixture("symlink")
        (symlink_root / "escape").symlink_to("/private/tmp")
        with self.assertRaisesRegex(hygiene.HygieneError, "symlink"):
            hygiene.audit_writable_scopes((symlink_root,))

        fifo_root = retained_fixture("fifo")
        os.mkfifo(fifo_root / "pipe")
        with self.assertRaisesRegex(hygiene.HygieneError, "FIFO"):
            hygiene.audit_writable_scopes((fifo_root,))

        socket_root = retained_fixture("socket")
        node = socket_root / "worker.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        previous_cwd = Path.cwd()
        try:
            os.chdir(socket_root)
            listener.bind(node.name)
        finally:
            os.chdir(previous_cwd)
        try:
            with self.assertRaisesRegex(hygiene.HygieneError, "socket"):
                hygiene.audit_writable_scopes((socket_root,))
        finally:
            listener.close()

        with self.assertRaisesRegex(hygiene.HygieneError, "special node"):
            hygiene.audit_writable_scopes((Path("/dev/null"),))

    def test_high_assurance_requires_dedicated_volume_attestation(self) -> None:
        root = retained_fixture("high-assurance")
        with self.assertRaisesRegex(hygiene.HygieneError, "dedicated volume"):
            hygiene.audit_writable_scopes((root,), high_assurance=True)

    def test_scope_identity_change_is_rejected_before_exec(self) -> None:
        parent = retained_fixture("identity")
        root = parent / "scope"
        replacement = parent / "replacement"
        root.mkdir()
        replacement.mkdir()
        scopes = hygiene.audit_writable_scopes((root,))
        root.rename(parent / "old-scope")
        replacement.rename(root)
        try:
            with self.assertRaisesRegex(hygiene.HygieneError, "identity"):
                hygiene.reaudit_writable_scopes(scopes)
        finally:
            hygiene.close_writable_scopes(scopes)


class ChildNormalizationTests(unittest.TestCase):
    def test_environment_is_allowlist_only_and_task_local(self) -> None:
        task_root = retained_fixture("env")
        built = hygiene.build_task_environment(
            task_root,
            inherited={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "ANTHROPIC_API_KEY": "secret",
                "HTTPS_PROXY": "http://proxy.invalid",
                "SSH_AUTH_SOCK": "/private/tmp/agent.sock",
            },
            allow_keys=("PATH", "LANG"),
        )

        self.assertEqual(
            set(built),
            {"HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "TMPDIR", "PATH", "LANG"},
        )
        self.assertTrue(Path(built["HOME"]).is_relative_to(task_root))
        self.assertNotIn("ANTHROPIC_API_KEY", built)
        self.assertNotIn("HTTPS_PROXY", built)
        self.assertNotIn("SSH_AUTH_SOCK", built)

    def test_task_environment_rejects_symlink_escape(self) -> None:
        root = retained_fixture("env-symlink")
        outside = retained_fixture("env-outside")
        (root / "home").symlink_to(outside)
        with self.assertRaisesRegex(hygiene.HygieneError, "symlink|no-follow"):
            hygiene.build_task_environment(root)

    def test_inherited_fd3_is_closed_before_child_exec(self) -> None:
        task_root = retained_fixture("fd3")
        target = task_root / "inherited-target.txt"
        helper = """
import json, os
from pathlib import Path
import launch_hygiene as h
target = Path(os.environ['TARGET'])
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.dup2(fd, 3)
os.set_inheritable(3, True)
if fd != 3:
    os.close(fd)
result = h.run_sanitized(
    ['/bin/sh', '-c', 'echo inherited-bypass >&3'],
    env={'PATH': '/usr/bin:/bin'},
    cwd=target.parent,
    timeout=5,
)
print(json.dumps({'returncode': result.returncode, 'stderr': result.stderr}))
"""
        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(PYTHON_DIR),
            "TARGET": str(target),
        }
        completed = subprocess.run(
            [sys.executable, "-c", helper],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        observed = json.loads(completed.stdout)
        self.assertNotEqual(observed["returncode"], 0)
        self.assertIn("Bad file descriptor", observed["stderr"])
        self.assertEqual(target.read_bytes(), b"")

    def test_high_numbered_inherited_fd_is_closed_before_child_exec(self) -> None:
        task_root = retained_fixture("fd-high")
        target = task_root / "inherited-target.txt"
        helper = """
import json, os
from pathlib import Path
import launch_hygiene as h
target = Path(os.environ['TARGET'])
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.dup2(fd, 100)
os.set_inheritable(100, True)
if fd != 100:
    os.close(fd)
result = h.run_sanitized(
    ['/bin/sh', '-c', 'echo inherited-bypass >&100'],
    env={'PATH': '/usr/bin:/bin'}, cwd=target.parent, timeout=5,
)
print(json.dumps({'returncode': result.returncode, 'stderr': result.stderr}))
"""
        completed = subprocess.run(
            [sys.executable, "-c", helper],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(PYTHON_DIR), "TARGET": str(target)},
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        observed = json.loads(completed.stdout)
        self.assertNotEqual(observed["returncode"], 0)
        self.assertEqual(target.read_bytes(), b"")

    def test_failing_canary_prevents_launch(self) -> None:
        failed = hygiene.CanaryResult.failed("wrong-port unexpectedly connected")
        task_root = retained_fixture("failed-canary")
        marker = task_root / "must-not-exist"

        with self.assertRaisesRegex(hygiene.HygieneError, "canary"):
            hygiene.launch_if_canary_passes(
                lambda: failed,
                ["/bin/sh", "-c", f"touch {marker}"],
                expected_profile_sha256="a" * 64,
                expected_request_sha256="b" * 64,
                expected_scope_sha256="c" * 64,
            )

        self.assertFalse(marker.exists())

    def test_canary_receipt_must_match_launch_profile_request_and_scopes(self) -> None:
        receipt = hygiene.CanaryResult(
            profile_sha256="a" * 64,
            allowed_write=True,
            denied_write=True,
            exact_broker_port=True,
            wrong_port_denied=True,
            fd3_closed=True,
            request_sha256="b" * 64,
            scope_sha256="c" * 64,
        )
        with self.assertRaisesRegex(hygiene.HygieneError, "sealed launch object"):
            hygiene.launch_if_canary_passes(
                lambda: receipt,
                ["/bin/sh", "-c", "exit 0"],
                expected_profile_sha256="d" * 64,
                expected_request_sha256="b" * 64,
                expected_scope_sha256="c" * 64,
            )

    def test_child_gets_new_session_and_bounded_rlimits(self) -> None:
        task_root = retained_fixture("limits")
        command = [
            sys.executable,
            "-c",
            (
                "import json, os, resource; "
                "print(json.dumps({'pid': os.getpid(), 'sid': os.getsid(0), "
                "'nofile': resource.getrlimit(resource.RLIMIT_NOFILE)[0], "
                "'fsize': resource.getrlimit(resource.RLIMIT_FSIZE)[0]}))"
            ),
        ]
        result = hygiene.run_sanitized(
            command,
            env={"PATH": "/usr/bin:/bin"},
            cwd=task_root,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["pid"], observed["sid"])
        self.assertLessEqual(observed["nofile"], 64)
        self.assertLessEqual(observed["fsize"], 64 * 1024 * 1024)

    def test_timeout_reaps_same_group_and_attributable_setsid_descendants(self) -> None:
        with tempfile.TemporaryDirectory(prefix="launch-timeout-") as raw:
            root = Path(raw)
            identities = root / "children.json"
            token = f"VS_LAUNCH_TIMEOUT_{os.getpid()}_{time.time_ns()}"
            program = (
                "import json,os,pathlib,subprocess,sys,time; "
                "same=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)',sys.argv[2]]); "
                "escaped=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)',sys.argv[2]+'-escaped'],start_new_session=True); "
                "pathlib.Path(sys.argv[1]).write_text(json.dumps([same.pid,escaped.pid])); "
                "time.sleep(30)"
            )
            pids: list[int] = []
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    hygiene.run_sanitized(
                        [sys.executable, "-c", program, str(identities), token],
                        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                        cwd=root,
                        timeout=1,
                        limits=hygiene.ResourceLimits(process_count=4096),
                    )
                pids = json.loads(identities.read_text(encoding="utf-8"))
                self.assertTrue(all(hygiene.observe_process(pid) is None for pid in pids))
            finally:
                if not pids and identities.exists():
                    pids = json.loads(identities.read_text(encoding="utf-8"))
                for pid in pids:
                    command = subprocess.run(
                        ["/bin/ps", "-ww", "-p", str(pid), "-o", "command="],
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout
                    if token in command:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_cleanup_failures_remain_controller_failures(self) -> None:
        manager = hygiene.ProcessGroupReaper()
        manager.register(123)
        identity = {
            "pid": 123, "pgid": 123, "process_start_token": "x", "argv_sha256": "0" * 64
        }
        with mock.patch.object(hygiene, "observe_process", return_value=identity), mock.patch.object(
            hygiene, "terminate_attributable_tree", side_effect=PermissionError("denied")
        ):
            with self.assertRaises(hygiene.ProcessTruthError):
                manager.terminate(123)
        # A second communicate timeout is the inherited-pipe-holder failure seam.
        process, reaper = mock.Mock(pid=123), mock.Mock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired([], 1), subprocess.TimeoutExpired([], 1)
        ]
        with mock.patch.object(hygiene.subprocess, "Popen", return_value=process):
            with self.assertRaises(hygiene.ProcessTruthError):
                hygiene.run_sanitized(["/bin/sleep", "1"], env={"PATH": "/bin"}, cwd=Path("/"), timeout=1, reaper=reaper)

    def test_board_supervisor_is_non_model_and_sender_owns_host_admission(self) -> None:
        supervisor = ROOT / "bin" / "board-supervisor.sh"
        completed = subprocess.run(
            ["bash", str(supervisor), "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("NON-model", completed.stdout)
        script = supervisor.read_text(encoding="utf-8")
        self.assertNotIn("host_admission.py", script)
        self.assertIn("from launch_hygiene import", script)
        self.assertIn(
            "host_admission.py",
            (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8"),
        )
        self.assertNotIn("--broker-port-available", script)
        self.assertNotIn("--provider-budget-available", script)
        self.assertNotIn("claude -p", script)
        self.assertNotIn("codex exec", script)

    def test_task_request_must_bind_settled_profile_bundle(self) -> None:
        task_root = retained_fixture("request")
        request = task_root / "request.json"
        payload = {
            "task_id": "TASK-2099-01-01-0001-fixture",
            "attempt_id": "d-00000000000000000000000000000000",
            "generation": 1,
            "branch": "v2",
            "task_root": str(task_root),
            "write_paths": [str(task_root)],
            "profile_bundle_sha256": "0" * 64,
        }
        request.write_text(json.dumps(payload), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(PYTHON_DIR / "launch_hygiene.py"), "validate", "--request", str(request)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(completed.returncode, 74)
        self.assertIn("settled Task-1.1 bundle", completed.stdout)

    def test_parent_traversal_is_rejected_without_creating_escape(self) -> None:
        parent = retained_fixture("request-traversal")
        allowed = parent / "allowed"
        allowed.mkdir()
        escape = parent / "escape"
        request = parent / "request.json"
        payload = {
            "task_id": "TASK-2099-01-01-0002-fixture",
            "attempt_id": "d-00000000000000000000000000000000",
            "generation": 1,
            "branch": "v2",
            "task_root": f"{allowed}/../escape",
            "write_paths": [str(allowed)],
            "profile_bundle_sha256": hygiene.SETTLED_T1P1_BUNDLE_SHA256,
        }
        request.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(hygiene.HygieneError, "parent traversal"):
            hygiene._load_task_request(request)
        self.assertFalse(escape.exists())


@unittest.skipUnless(sys.platform == "darwin", "real Seatbelt probe requires macOS")
class RealHostCanaryTests(unittest.TestCase):
    def test_exact_profile_canary_closes_fd3_and_denies_wrong_effects(self) -> None:
        root = retained_fixture("real-canary")
        result = hygiene.run_preflight_canary(root)
        self.assertTrue(result.passed, result.to_json())
        self.assertTrue(result.allowed_write)
        self.assertTrue(result.denied_write)
        self.assertTrue(result.exact_broker_port)
        self.assertTrue(result.wrong_port_denied)
        self.assertTrue(result.fd3_closed)

    def test_retained_canary_object_is_the_one_consumed_by_launcher(self) -> None:
        root = retained_fixture("retained-canary")
        prepared = hygiene.run_preflight_canary(
            root,
            request_sha256="b" * 64,
            retain_launch=True,
        )
        self.assertIsInstance(prepared, hygiene.PreparedLaunch)
        assert isinstance(prepared, hygiene.PreparedLaunch)
        observed = hygiene.launch_if_canary_passes(
            lambda: prepared,
            ["/bin/sh", "-c", "exit 0"],
            expected_profile_sha256=prepared.canary.profile_sha256,
            expected_request_sha256=prepared.canary.request_sha256,
            expected_scope_sha256=prepared.canary.scope_sha256,
        )
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertTrue(prepared.consumed)
        self.assertEqual(prepared.broker_listener.fileno(), -1)


if __name__ == "__main__":
    unittest.main()
