#!/usr/bin/env python3
"""Security regressions for CC-05/CC-06 in vibecoding_check.py."""

from __future__ import annotations

import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts/python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

import vibecoding_check as checker  # noqa: E402


def dns_answer(address: str, port: int = 443) -> list[tuple[object, ...]]:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr: tuple[object, ...]
    if family == socket.AF_INET6:
        sockaddr = (address, port, 0, 0)
    else:
        sockaddr = (address, port)
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


class FakeHTTPSocket:
    def __init__(self, response: bytes | None = None) -> None:
        self.connected_to: tuple[object, ...] | None = None
        self.sent = bytearray()
        self.timeout: object = None
        self.closed = False
        self.response = response or (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Length: 0\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )

    def settimeout(self, timeout: object) -> None:
        self.timeout = timeout

    def bind(self, source_address: tuple[str, int]) -> None:
        raise AssertionError(f"unexpected source bind: {source_address}")

    def connect(self, address: tuple[object, ...]) -> None:
        self.connected_to = address

    def setsockopt(self, *_: object) -> None:
        return None

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def makefile(self, *_: object, **__: object) -> io.BytesIO:
        return io.BytesIO(self.response)

    def close(self) -> None:
        self.closed = True


class SecurityFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.holder = Path(tempfile.mkdtemp(prefix="sec-cc0506-"))
        self.addCleanup(shutil.rmtree, self.holder, True)
        self.root = self.holder / "vault"
        self.root.mkdir()
        self.state = self.root / "_state"
        (self.state / "runs").mkdir(parents=True)
        (self.state / "approvals").mkdir()
        old = (
            checker.VAULT_ROOT,
            checker.STATE_DIR,
            checker.RUNS_DIR,
            checker.APPROVALS_DIR,
            checker.CHECK_DIR,
        )
        checker.VAULT_ROOT = self.root
        checker.STATE_DIR = self.state
        checker.RUNS_DIR = self.state / "runs"
        checker.APPROVALS_DIR = self.state / "approvals"
        checker.CHECK_DIR = self.state / "vibecoding-check"
        self.addCleanup(self._restore, old)

    @staticmethod
    def _restore(old: tuple[Path, Path, Path, Path, Path]) -> None:
        (
            checker.VAULT_ROOT,
            checker.STATE_DIR,
            checker.RUNS_DIR,
            checker.APPROVALS_DIR,
            checker.CHECK_DIR,
        ) = old

    def write_approval(self, run_id: str, content: str) -> Path:
        path = checker.APPROVALS_DIR / f"{run_id}.md"
        path.write_text(content, encoding="utf-8")
        return path


class CommandBoundaryTests(SecurityFixture):
    def test_string_and_metacharacter_commands_are_rejected_without_execution(self) -> None:
        attacks: tuple[object, ...] = (
            f"{sys.executable} -m unittest",
            f"{sys.executable} -m unittest; touch sentinel",
            [sys.executable, "-m", "unittest", "test_ok.py;touch sentinel"],
        )
        for attack in attacks:
            with self.subTest(attack=attack), mock.patch.object(
                checker.subprocess, "run"
            ) as run:
                result = checker.check_project_tests_pass(
                    {"test_command": attack, "test_cwd": str(self.root)}
                )
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)
                run.assert_not_called()

    def test_test_cwd_traversal_and_symlink_escape_are_rejected(self) -> None:
        outside = self.holder / "outside"
        outside.mkdir()
        escape = self.root / "escape"
        escape.symlink_to(outside, target_is_directory=True)
        command = [sys.executable, "-m", "unittest", "-q"]
        for cwd in (outside, escape):
            with self.subTest(cwd=cwd), mock.patch.object(
                checker.subprocess, "run"
            ) as run:
                result = checker.check_project_tests_pass(
                    {"test_command": command, "test_cwd": str(cwd)}
                )
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)
                run.assert_not_called()

    def test_allowlisted_argv_uses_no_shell_and_drops_ambient_secrets(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "ok", "")
        command = [sys.executable, "-m", "unittest", "-q"]
        with (
            mock.patch.dict(
                os.environ, {"AWS_SECRET_ACCESS_KEY": "must-not-propagate"}
            ),
            mock.patch.object(checker.subprocess, "run", return_value=completed) as run,
        ):
            result = checker.check_project_tests_pass(
                {"test_command": command, "test_cwd": str(self.root)}
            )
        self.assertTrue(result.passed, result.detail)
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["cwd"], str(self.root.resolve()))
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", kwargs["env"])
        self.assertEqual(kwargs["env"]["HOME"], str(self.root.resolve()))

    def test_bare_symlink_test_selector_is_rejected_without_execution(self) -> None:
        outside = self.holder / "outside-tests"
        outside.mkdir()
        (self.root / "evilsym").symlink_to(outside, target_is_directory=True)
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "evilsym",
        ]
        with mock.patch.object(checker.subprocess, "run") as run:
            result = checker.check_project_tests_pass(
                {"test_command": command, "test_cwd": str(self.root)}
            )
        self.assertFalse(result.passed)
        self.assertEqual(result.tier, checker.TIER_OPERATOR)
        self.assertIn("selector escapes test_cwd", result.detail)
        run.assert_not_called()


class FilesystemBoundaryTests(SecurityFixture):
    def test_run_id_traversal_is_rejected_before_path_construction(self) -> None:
        for value in ("../escape", "..", "run/id", "/absolute", "bad.run"):
            with self.subTest(value=value):
                with self.assertRaises(checker.ManifestContractError):
                    checker.validate_run_id(value)
                with self.assertRaises(checker.ManifestContractError):
                    checker._run_state_path(value, "manifest.yaml", must_exist=False)
                with self.assertRaises(checker.ManifestContractError):
                    checker._state_output_path(value)

    def test_manifest_and_output_symlink_escapes_are_rejected(self) -> None:
        outside = self.holder / "outside"
        outside.mkdir()
        (outside / "manifest.yaml").write_text("{}\n", encoding="utf-8")
        (checker.RUNS_DIR / "RUN-SAFE").symlink_to(
            outside, target_is_directory=True
        )
        with self.assertRaises(checker.ManifestContractError):
            checker._run_state_path(
                "RUN-SAFE", "manifest.yaml", must_exist=True
            )

        checker.CHECK_DIR.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(checker.ManifestContractError):
            checker._state_output_path("RUN-SAFE")

    def test_manifest_artifact_path_cannot_read_outside_vault(self) -> None:
        outside = self.holder / "outside.txt"
        outside.write_text("private\n", encoding="utf-8")
        result = checker.check_artifacts_exist({"artifacts": [str(outside)]})
        self.assertFalse(result.passed)
        self.assertEqual(result.tier, checker.TIER_OPERATOR)
        citation = checker.check_citations_resolve({"citations": [str(outside)]})
        self.assertFalse(citation.passed)
        self.assertEqual(citation.tier, checker.TIER_OPERATOR)


class CitationBoundaryTests(SecurityFixture):
    def test_literal_loopback_private_and_metadata_addresses_are_denied(self) -> None:
        cases = (
            ("http://127.0.0.1/", "127.0.0.1"),
            ("http://10.1.2.3/", "10.1.2.3"),
            ("http://192.168.4.5/", "192.168.4.5"),
            ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
            ("http://[::1]/", "::1"),
        )
        for url, address in cases:
            with self.subTest(url=url), mock.patch.object(
                checker.socket, "getaddrinfo", return_value=dns_answer(address, 80)
            ):
                with self.assertRaises(checker.CitationPolicyError):
                    checker._validate_citation_url(url)
                result = checker.check_citations_resolve({"citations": [url]})
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_dns_resolved_private_address_is_denied(self) -> None:
        with mock.patch.object(
            checker.socket,
            "getaddrinfo",
            return_value=dns_answer("172.16.1.2"),
        ):
            with self.assertRaises(checker.CitationPolicyError):
                checker._validate_citation_url("https://citation.example/source")

    def test_redirect_to_private_and_cross_scheme_redirect_are_denied(self) -> None:
        request = urllib.request.Request("https://public.example/source")
        handler = checker._SafeCitationRedirectHandler()

        def resolve(host: str, port: int, **_: object) -> list[tuple[object, ...]]:
            address = "10.0.0.8" if host == "private.example" else "93.184.216.34"
            return dns_answer(address, port)

        with mock.patch.object(checker.socket, "getaddrinfo", side_effect=resolve):
            with self.assertRaises(checker.CitationPolicyError):
                handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    "https://private.example/admin",
                )
            with self.assertRaises(checker.CitationPolicyError):
                handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    "http://public.example/downgrade",
                )

    def test_public_dns_answer_is_allowed_without_network_request(self) -> None:
        with mock.patch.object(
            checker.socket,
            "getaddrinfo",
            return_value=dns_answer("93.184.216.34"),
        ):
            target = checker._validate_citation_url("https://example.com/source")
        self.assertEqual(target.scheme, "https")
        self.assertEqual(target.hostname, "example.com")
        self.assertEqual(str(target.ip), "93.184.216.34")

    def test_rebinding_cannot_change_the_address_used_by_connector(self) -> None:
        fake_socket = FakeHTTPSocket()
        answers = [
            dns_answer("93.184.216.34", 80),
            dns_answer("127.0.0.1", 80),
        ]
        with (
            mock.patch.object(
                checker.socket,
                "getaddrinfo",
                side_effect=answers,
            ) as getaddrinfo,
            mock.patch.object(
                checker.socket,
                "socket",
                return_value=fake_socket,
            ),
        ):
            status = checker._probe_http("http://rebind.example/internal-admin")

        self.assertEqual(status, 200)
        self.assertEqual(getaddrinfo.call_count, 1)
        self.assertEqual(fake_socket.connected_to, ("93.184.216.34", 80))
        self.assertNotEqual(fake_socket.connected_to, ("127.0.0.1", 80))
        self.assertIn(b"Host: rebind.example\r\n", bytes(fake_socket.sent))

    def test_https_pin_preserves_original_hostname_for_tls_sni(self) -> None:
        fake_socket = FakeHTTPSocket()
        context = mock.Mock()
        context.wrap_socket.return_value = fake_socket
        with mock.patch.object(
            checker.socket,
            "socket",
            return_value=fake_socket,
        ):
            connection = checker._PinnedHTTPSConnection(
                "secure.example",
                443,
                pinned_ip=checker.ipaddress.ip_address("93.184.216.34"),
                timeout=15,
                context=context,
            )
            connection.connect()

        self.assertEqual(fake_socket.connected_to, ("93.184.216.34", 443))
        context.wrap_socket.assert_called_once_with(
            fake_socket,
            server_hostname="secure.example",
        )

    def test_redirect_hop_gets_its_own_validated_address_pin(self) -> None:
        first_socket = FakeHTTPSocket(
            b"HTTP/1.1 302 Found\r\n"
            b"Location: http://redirect.example/next\r\n"
            b"Content-Length: 0\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        second_socket = FakeHTTPSocket()
        with (
            mock.patch.object(
                checker.socket,
                "getaddrinfo",
                side_effect=[
                    dns_answer("93.184.216.34", 80),
                    dns_answer("93.184.216.35", 80),
                ],
            ) as getaddrinfo,
            mock.patch.object(
                checker.socket,
                "socket",
                side_effect=[first_socket, second_socket],
            ),
        ):
            status = checker._probe_http("http://origin.example/start")

        self.assertEqual(status, 200)
        self.assertEqual(getaddrinfo.call_count, 2)
        self.assertEqual(first_socket.connected_to, ("93.184.216.34", 80))
        self.assertEqual(second_socket.connected_to, ("93.184.216.35", 80))
        self.assertIn(b"Host: origin.example\r\n", bytes(first_socket.sent))
        self.assertIn(b"Host: redirect.example\r\n", bytes(second_socket.sent))


class ApprovalBoundaryTests(SecurityFixture):
    def test_approval_words_inside_free_text_do_not_authorize(self) -> None:
        run_id = "RUN-APPROVAL-TEST"
        attacks = (
            "DO NOT APPROVE this run\n",
            "notes: OVERRIDE would be unsafe\n",
            "# APPROVE\n",
        )
        for content in attacks:
            with self.subTest(content=content):
                self.write_approval(run_id, content)
                result = checker.check_operator_approval({"run_id": run_id})
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_typed_approval_is_bound_to_run_id_and_decision(self) -> None:
        run_id = "RUN-APPROVAL-TEST"
        self.write_approval(
            run_id,
            "---\n"
            "schema_version: vibecoding-approval/v1\n"
            f"run_id: {run_id}\n"
            "decision: approve\n"
            "deletion_approved: false\n"
            "---\n"
            "Operator approval audit trail.\n",
        )
        result = checker.check_operator_approval({"run_id": run_id})
        self.assertTrue(result.passed, result.detail)

        self.write_approval(
            run_id,
            "---\n"
            "schema_version: vibecoding-approval/v1\n"
            "run_id: RUN-DIFFERENT\n"
            "decision: approve\n"
            "---\n",
        )
        result = checker.check_operator_approval({"run_id": run_id})
        self.assertFalse(result.passed)
        self.assertEqual(result.tier, checker.TIER_OPERATOR)


if __name__ == "__main__":
    unittest.main()
