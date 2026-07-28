#!/usr/bin/env python3
"""F2 real-transport and zero-raw-key closure invariants."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
from urllib import error, request


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from broker_adapters import build_adapter  # noqa: E402
from cred_broker import (  # noqa: E402
    Budget,
    BrokerHTTPServer,
    CredentialBroker,
    HandleScope,
    LocalMockProviderTransport,
    ProviderHTTPResponse,
    RealHTTPSProviderTransport,
    SupervisorAuthority,
)
from launch_hygiene import CanaryResult, PreparedLaunch  # noqa: E402
from lane_launch_broker import (  # noqa: E402
    SUPPORTED_LIVE_LANES,
    SpendLedger,
    launch_gemini,
    resolve_lane_runtime,
    scan_observation_surface,
)
from seatbelt_profile import CompiledProfile, HostCompatibility, ProfileSpec, compile_profile  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)


OPAQUE_HANDLE = "cb1.opaque-handle.mac"
PROVIDER_SECRET = "provider-secret-must-remain-supervisor-only"
HOST = HostCompatibility(Path("/usr/bin/sandbox-exec"), "25E253", "0" * 64)


class _FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "application/json") -> None:
        self.status = 200
        self.headers = {"Content-Type": content_type}
        self._payload = payload
        self._read = False

    def read(self, _limit: int) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests: list[object] = []

    def open(self, outbound: object, timeout: float) -> _FakeResponse:
        self.requests.append(outbound)
        if timeout <= 0:
            raise AssertionError("timeout must be finite and positive")
        return self.response


def _authority(lane: str) -> SupervisorAuthority:
    return SupervisorAuthority(
        task_id="TASK-2099-01-01-0001-f2-test",
        attempt_id="d-00000000000000000000000000000000",
        generation=1,
        lane=lane,
        authority_sha256="a" * 64,
    )


class RealProviderTransportTests(unittest.TestCase):
    def test_exact_lane_egress_and_auth_injection_never_put_secret_in_url_or_body(self) -> None:
        cases = {
            "claude": (
                "/v1/model/claude/v1/messages",
                {"model": "claude-haiku-test", "messages": [], "max_tokens": 8},
                {"usage": {"input_tokens": 2, "output_tokens": 1}},
                "https://api.anthropic.com/v1/messages",
                "X-api-key",
            ),
            "codex": (
                "/v1/model/codex/responses",
                {"model": "gpt-test", "input": "ok", "max_output_tokens": 8},
                {"usage": {"input_tokens": 2, "output_tokens": 1}},
                "https://api.openai.com/v1/responses",
                "Authorization",
            ),
            "kimi": (
                "/v1/model/kimi/chat/completions",
                {"model": "kimi-test", "messages": [], "max_tokens": 8},
                {"usage": {"prompt_tokens": 2, "completion_tokens": 1}},
                "https://api.moonshot.ai/v1/chat/completions",
                "Authorization",
            ),
            "gemini": (
                "/v1/model/gemini/v1beta/models/gemini-test:generateContent",
                {"contents": [{"role": "user", "parts": [{"text": "ok"}]}]},
                {"usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1}},
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent",
                "X-goog-api-key",
            ),
        }
        for lane, (path, body, response, expected_url, auth_header) in cases.items():
            with self.subTest(lane=lane):
                transport = RealHTTPSProviderTransport(lane)
                fake = _FakeOpener(_FakeResponse(json.dumps(response).encode()))
                transport._opener = fake  # type: ignore[attr-defined]
                result = transport(
                    lane=lane,
                    target=str(body.get("model", "gemini-test")),
                    body=body,
                    headers={"Authorization": f"Bearer {PROVIDER_SECRET}"},
                    response_limit=4096,
                    request_path=path,
                    client_headers={},
                )
                self.assertIsInstance(result, ProviderHTTPResponse)
                request = fake.requests[-1]
                self.assertEqual(request.full_url, expected_url)
                self.assertIn(PROVIDER_SECRET, request.headers[auth_header])
                self.assertNotIn(PROVIDER_SECRET, request.full_url)
                self.assertNotIn(PROVIDER_SECRET, request.data.decode())
                self.assertNotIn(PROVIDER_SECRET, result.body.decode())
                self.assertEqual(result.usage["input_tokens"], 2)
                self.assertEqual(result.usage["output_tokens"], 1)
                self.assertGreater(result.usage["cost_micros"], 0)

    def test_real_transport_is_fixed_to_reviewed_https_origins(self) -> None:
        for lane in ("claude", "codex", "kimi", "gemini"):
            transport = RealHTTPSProviderTransport(lane)
            self.assertTrue(transport.provider_origin.startswith("https://"))
            self.assertNotIn("localhost", transport.provider_origin)
            self.assertNotIn("127.0.0.1", transport.provider_origin)
        with self.assertRaisesRegex(ValueError, "lane"):
            RealHTTPSProviderTransport("other")

    def test_real_transport_cannot_use_unbound_local_mock_escape_hatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "unbound local mock"):
            CredentialBroker(
                expected_authority=_authority("gemini"),
                provider_secrets={"gemini": PROVIDER_SECRET},
                provider_transports={"gemini": RealHTTPSProviderTransport("gemini")},
                allow_unbound_local_mock=True,
            )

    def test_gemini_native_route_accepts_only_canonical_stream_query(self) -> None:
        broker = CredentialBroker(
            expected_authority=_authority("gemini"),
            provider_secrets={"gemini": PROVIDER_SECRET},
            provider_transports={"gemini": LocalMockProviderTransport({})},
            allow_unbound_local_mock=True,
        )
        action, target, lane, _settle, _operator = broker._endpoint(  # noqa: SLF001
            "/v1/model/gemini/v1beta/models/gemini-test:streamGenerateContent?alt=sse",
            {},
        )
        self.assertEqual((action, target, lane), ("model:gemini", "gemini-test", "gemini"))
        for invalid in (
            "/v1/model/gemini/v1beta/models/gemini-test:delete",
            "/v1/model/gemini/v1beta/models/gemini-test:streamGenerateContent?key=raw",
            "/v1/model/gemini/../codex/responses",
        ):
            with self.subTest(path=invalid), self.assertRaises(Exception):
                broker._endpoint(invalid, {})  # noqa: SLF001

    def test_native_http_gateway_accepts_one_opaque_google_header_and_returns_provider_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            port = int(listener.getsockname()[1])
            profile_hash = "b" * 64
            request_hash = "c" * 64
            scope_hash = "d" * 64
            profile = CompiledProfile(
                text=f'(version 1)\n(deny default)\n(allow network-outbound (remote tcp "localhost:{port}"))\n',
                sha256=profile_hash,
                compatibility=HOST,
            )
            canary = CanaryResult(
                profile_sha256=profile_hash,
                allowed_write=True,
                denied_write=True,
                exact_broker_port=True,
                wrong_port_denied=True,
                fd3_closed=True,
                request_sha256=request_hash,
                scope_sha256=scope_hash,
            )
            prepared = PreparedLaunch(profile, listener, canary, root, {}, (), ())
            transport = RealHTTPSProviderTransport("gemini")
            provider_payload = {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
            }
            fake = _FakeOpener(_FakeResponse(json.dumps(provider_payload).encode()))
            transport._opener = fake  # type: ignore[attr-defined]
            broker = CredentialBroker(
                expected_authority=SupervisorAuthority(
                    task_id="TASK-2099-01-01-0001-f2-test",
                    attempt_id="d-00000000000000000000000000000000",
                    generation=1,
                    lane="gemini",
                    authority_sha256="a" * 64,
                    profile_sha256=profile_hash,
                    request_sha256=request_hash,
                    scope_sha256=scope_hash,
                ),
                provider_secrets={"gemini": PROVIDER_SECRET},
                provider_transports={"gemini": transport},
            )
            server = BrokerHTTPServer.from_prepared_launch(prepared, broker)
            handle = broker.mint_handle(
                HandleScope(
                    task_id="TASK-2099-01-01-0001-f2-test",
                    attempt_id="d-00000000000000000000000000000000",
                    generation=1,
                    lane="gemini",
                    authority_sha256="a" * 64,
                    profile_sha256=profile_hash,
                    request_sha256=request_hash,
                    scope_sha256=scope_hash,
                    actions=("model:gemini",),
                    targets=("gemini-test",),
                    budget=Budget(1, 4096, 8, 100_000, 16_384),
                ),
                ttl_seconds=30,
            )
            server.start()
            endpoint = server.base_url + "/v1/model/gemini/v1beta/models/gemini-test:generateContent"
            body = json.dumps({"contents": [{"parts": [{"text": "ok"}]}]}).encode()
            try:
                duplicate = request.Request(
                    endpoint,
                    data=body,
                    headers={
                        "Authorization": f"Bearer {handle}",
                        "x-goog-api-key": handle,
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with self.assertRaises(error.HTTPError) as denied:
                    request.urlopen(duplicate, timeout=3)
                self.assertEqual(denied.exception.code, 403)
                denied.exception.close()

                outbound = request.Request(
                    endpoint,
                    data=body,
                    headers={"x-goog-api-key": handle, "Content-Type": "application/json"},
                    method="POST",
                )
                with request.urlopen(outbound, timeout=3) as response:
                    observed = json.loads(response.read())
                self.assertEqual(observed["candidates"][0]["content"]["parts"][0]["text"], "ok")
                self.assertIn(PROVIDER_SECRET, fake.requests[-1].headers["X-goog-api-key"])
                self.assertNotIn(PROVIDER_SECRET, json.dumps(broker.action_logs))
                self.assertGreater(broker.action_logs[-1]["cost_micros"], 0)
            finally:
                server.close()


class AdapterAndProfileTests(unittest.TestCase):
    def test_no_lane_is_publicly_launchable_without_a_successful_live_receipt(self) -> None:
        self.assertEqual(SUPPORTED_LIVE_LANES, frozenset())
        for lane in ("claude", "codex", "kimi"):
            with self.subTest(lane=lane), self.assertRaisesRegex(Exception, "not F2-proven"):
                resolve_lane_runtime(lane)

    def test_gemini_adapter_exposes_only_opaque_handle_to_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            bundle = build_adapter(
                "gemini",
                "http://127.0.0.1:43210",
                OPAQUE_HANDLE,
                home,
                Path("/opt/homebrew/bin/node"),
            )
            serialized = json.dumps(
                {
                    "environment": bundle.base_environment,
                    "files": {str(path): content for path, content in bundle.files.items()},
                    "argv": bundle.argv,
                },
                sort_keys=True,
            )
            self.assertIn("GOOGLE_GEMINI_BASE_URL", serialized)
            self.assertIn("GEMINI_API_KEY", serialized)
            self.assertIn(OPAQUE_HANDLE, serialized)
            self.assertNotIn(PROVIDER_SECRET, serialized)
            self.assertNotIn("generativelanguage.googleapis.com", serialized)

    @unittest.skipUnless(
        sys.platform == "darwin",
        "macOS-only: exact executable grants are rendered as a Seatbelt profile",
    )
    def test_lane_executables_are_exact_literals_not_directory_exec_grants(self) -> None:
        compiled = compile_profile(
            ProfileSpec(
                write_paths=(ROOT / "_state",),
                executable_paths=(Path("/bin/sh"),),
                lane_executable_paths=(Path("/usr/bin/env"), Path("/usr/bin/true")),
                broker_port=43210,
            ),
            compatibility_verifier=lambda: HOST,
        )
        self.assertIn('(allow process-exec (literal "/usr/bin/env"))', compiled.text)
        self.assertIn('(allow process-exec (literal "/usr/bin/true"))', compiled.text)
        self.assertNotIn('(subpath "/usr/bin")', compiled.text.split("process-exec")[-1])


class ObservationAndSpendTests(unittest.TestCase):
    def test_observation_report_records_booleans_and_hashes_never_raw_secret(self) -> None:
        report = scan_observation_surface(
            provider_secret=PROVIDER_SECRET,
            opaque_handle=OPAQUE_HANDLE,
            environment={"GEMINI_API_KEY": OPAQUE_HANDLE},
            argv=("/opt/homebrew/bin/node", "gemini.js"),
            files={Path("handle"): OPAQUE_HANDLE},
            stdout="ok",
            stderr="",
            process_snapshot="GEMINI_API_KEY=" + OPAQUE_HANDLE,
        )
        serialized = json.dumps(report.to_dict(), sort_keys=True)
        self.assertFalse(report.raw_secret_observed)
        self.assertTrue(report.opaque_handle_observed)
        self.assertNotIn(PROVIDER_SECRET, serialized)
        self.assertNotIn(OPAQUE_HANDLE, serialized)

        leaked = scan_observation_surface(
            provider_secret=PROVIDER_SECRET,
            opaque_handle=OPAQUE_HANDLE,
            environment={"BAD": PROVIDER_SECRET},
            argv=("/bin/true",),
            files={},
            stdout="",
            stderr="",
            process_snapshot="",
        )
        self.assertTrue(leaked.raw_secret_observed)

    def test_shared_spend_ledger_stops_before_one_dollar(self) -> None:
        ledger = SpendLedger(ceiling_micros=999_999)
        ledger.record("gemini", 125_000)
        self.assertEqual(ledger.total_micros, 125_000)
        with self.assertRaisesRegex(RuntimeError, "ceiling"):
            ledger.reserve(900_000)
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            ledger.record("gemini", 1)

    @skip_in_host_independent_ci(
        "needs the live Stage-1 branch and Gemini launch-broker path"
    )
    def test_actual_gemini_cli_reaches_provider_compatible_broker_with_no_raw_key(self) -> None:
        event = {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "ok"}]},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
        }
        sse = ("data: " + json.dumps(event) + "\n\n").encode()
        transport = RealHTTPSProviderTransport("gemini")
        transport._opener = _FakeOpener(_FakeResponse(sse, "text/event-stream"))  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            root = parent / "task"
            root.mkdir()
            request_path = parent / "request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "task_id": "TASK-2099-01-01-0001-f2-live-test",
                        "attempt_id": "d-00000000000000000000000000000000",
                        "generation": 1,
                        "branch": "v2",
                        "task_root": str(root),
                        "write_paths": [str(root)],
                        "profile_bundle_sha256": "95438e2cc6b06ab3f12622ad0a0f3e0a6654e6cf3a7b35f3908b3487f883f376",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"GEMINI_API_KEY": PROVIDER_SECRET}, clear=False):
                receipt = launch_gemini(
                    request_path,
                    model="gemini-test",
                    prompt="Reply exactly: ok. Do not use tools.",
                    max_cost_micros=250_000,
                    transport=transport,
                )
        self.assertEqual(receipt["status"], "f2-closed")
        self.assertFalse(receipt["observation"]["raw_secret_observed"])
        self.assertTrue(receipt["observation"]["opaque_handle_observed"])
        self.assertEqual(receipt["spend"]["total_micros"], 35)


if __name__ == "__main__":
    unittest.main()
