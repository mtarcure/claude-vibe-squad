#!/usr/bin/env python3
"""Security invariants for the supervisor-owned credential broker."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
from socketserver import TCPServer
import sys
import tempfile
import threading
import unittest
from urllib import error, request


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from cred_broker import (  # noqa: E402
    BrokerDenied,
    BrokerHTTPServer,
    Budget,
    CredentialBroker,
    HandleScope,
    LocalHTTPProviderTransport,
    LocalMockActionHandler,
    LocalMockProviderTransport,
    SupervisorAuthority,
    canonical_request_sha256,
)
from launch_hygiene import PreparedLaunch, run_preflight_canary  # noqa: E402


PROVIDER_SECRET = "mock-provider-secret-never-child-visible"
CONNECTOR_SECRET = "mock-connector-secret-never-child-visible"


class Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def scope(**overrides: object) -> HandleScope:
    values: dict[str, object] = {
        "task_id": "TASK-2099-01-01-0001-broker-test",
        "attempt_id": "d-00000000000000000000000000000000",
        "generation": 3,
        "lane": "claude",
        "authority_sha256": "a" * 64,
        "actions": ("model:claude",),
        "targets": ("mock-model",),
        "budget": Budget(
            max_calls=2,
            max_input_tokens=4096,
            max_output_tokens=40,
            max_cost_micros=100000,
            max_response_bytes=4096,
        ),
    }
    values.update(overrides)
    return HandleScope(**values)


def fake_transport() -> LocalMockProviderTransport:
    return LocalMockProviderTransport({
        "id": "mock-response",
        "content": "local mock only",
        "usage": {"input_tokens": 5, "output_tokens": 4, "cost_micros": 20},
        "access_token": PROVIDER_SECRET,
        "signed_url": f"http://127.0.0.1/download?secret={PROVIDER_SECRET}",
    })


def authority(**overrides: object) -> SupervisorAuthority:
    values: dict[str, object] = {
        "task_id": "TASK-2099-01-01-0001-broker-test",
        "attempt_id": "d-00000000000000000000000000000000",
        "generation": 3,
        "lane": "claude",
        "authority_sha256": "a" * 64,
    }
    values.update(overrides)
    return SupervisorAuthority(**values)


def model_body(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "task_id": "TASK-2099-01-01-0001-broker-test",
        "attempt_id": "d-00000000000000000000000000000000",
        "generation": 3,
        "authority_sha256": "a" * 64,
        "model": "mock-model",
        "messages": [{"role": "user", "content": "hello local mock"}],
        "max_tokens": 20,
    }
    values.update(overrides)
    return values


class HandlePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.transport = fake_transport()
        self.broker = CredentialBroker(
            expected_authority=authority(),
            provider_secrets={"claude": PROVIDER_SECRET},
            provider_transports={"claude": self.transport},
            clock=self.clock,
            signing_key=b"k" * 32,
            startup_id="startup-a",
            allow_unbound_local_mock=True,
        )

    def mint(self, **overrides: object) -> str:
        return self.broker.mint_handle(scope(**overrides), ttl_seconds=30)

    def call(self, handle: str, nonce: str = "request-1", **body: object) -> dict[str, object]:
        return self.broker.dispatch(
            "/v1/model/claude",
            handle=handle,
            request_nonce=nonce,
            body=model_body(**body),
        )

    def test_handle_is_opaque_and_not_the_provider_credential(self) -> None:
        handle = self.mint()
        self.assertTrue(handle.startswith("cb1."))
        self.assertNotIn(PROVIDER_SECRET, handle)
        self.assertNotIn("mock-model", handle)
        self.assertNotIn("TASK-", handle)

    def test_broker_injects_provider_auth_and_redacts_result_and_logs(self) -> None:
        result = self.call(self.mint())
        self.assertEqual(self.transport.headers[-1]["Authorization"], f"Bearer {PROVIDER_SECRET}")
        serialized = json.dumps({"result": result, "logs": self.broker.action_logs})
        self.assertNotIn(PROVIDER_SECRET, serialized)
        self.assertEqual(result["access_token"], "[REDACTED]")
        self.assertEqual(result["signed_url"], "[REDACTED]")

    def test_expired_replayed_wrong_lane_generation_target_and_authority_reject(self) -> None:
        stale = self.mint()
        self.clock.value += 31
        with self.assertRaisesRegex(BrokerDenied, "expired"):
            self.call(stale)

        self.clock.value = 1000
        handle = self.mint()
        self.call(handle, nonce="same")
        with self.assertRaisesRegex(BrokerDenied, "replay"):
            self.call(handle, nonce="same")

        with self.assertRaisesRegex(BrokerDenied, "lane"):
            self.broker.dispatch(
                "/v1/model/kimi", handle=self.mint(), request_nonce="n-lane", body=model_body()
            )
        with self.assertRaisesRegex(BrokerDenied, "generation"):
            self.call(self.mint(), nonce="n-gen", generation=4)
        with self.assertRaisesRegex(BrokerDenied, "target"):
            self.call(self.mint(), nonce="n-target", model="other-model")
        with self.assertRaisesRegex(BrokerDenied, "authority"):
            self.call(self.mint(), nonce="n-auth", authority_sha256="b" * 64)

    def test_count_token_dollar_and_response_budgets_reject_before_transport(self) -> None:
        def broker_for(budget: Budget) -> tuple[CredentialBroker, LocalMockProviderTransport, str]:
            transport = fake_transport()
            broker = CredentialBroker(
                expected_authority=authority(),
                provider_secrets={"claude": PROVIDER_SECRET},
                provider_transports={"claude": transport},
                allow_unbound_local_mock=True,
            )
            return broker, transport, broker.mint_handle(scope(budget=budget), ttl_seconds=30)

        cases = (
            (Budget(1, 1, 40, 1000, 4096), "input-token", {}),
            (Budget(1, 4096, 40, 100000, 4096), "output-token", {"max_tokens": 41}),
            (Budget(1, 4096, 40, 1, 4096), "dollar", {}),
            (Budget(1, 4096, 40, 100000, 8), "response-size", {}),
        )
        for budget, reason, body_overrides in cases:
            with self.subTest(reason=reason):
                broker, transport, handle = broker_for(budget)
                with self.assertRaisesRegex(BrokerDenied, reason):
                    broker.dispatch(
                        "/v1/model/claude",
                        handle=handle,
                        request_nonce=f"n-{reason}",
                        body=model_body(**body_overrides),
                    )
                self.assertEqual(transport.headers, [])

        one_call_budget = Budget(1, 4096, 40, 100000, 4096)
        broker, _, one_call = broker_for(one_call_budget)
        broker.dispatch(
            "/v1/model/claude", handle=one_call, request_nonce="first", body=model_body()
        )
        with self.assertRaisesRegex(BrokerDenied, "request-count"):
            broker.dispatch(
                "/v1/model/claude",
                handle=broker.mint_handle(scope(budget=one_call_budget), ttl_seconds=30),
                request_nonce="second",
                body=model_body(),
            )

    def test_restart_and_revocation_invalidate_handles(self) -> None:
        handle = self.mint()
        restarted = CredentialBroker(
            expected_authority=authority(),
            provider_secrets={"claude": PROVIDER_SECRET},
            provider_transports={"claude": self.transport},
            clock=self.clock,
            signing_key=b"z" * 32,
            startup_id="startup-b",
            allow_unbound_local_mock=True,
        )
        with self.assertRaisesRegex(BrokerDenied, "unknown|MAC|restart"):
            restarted.dispatch(
                "/v1/model/claude", handle=handle, request_nonce="restart", body=model_body()
            )
        self.broker.revoke(handle)
        with self.assertRaisesRegex(BrokerDenied, "revoked"):
            self.call(handle, nonce="revoked")

    def test_nonce_race_allows_exactly_one_call(self) -> None:
        handle = self.mint()

        def attempt(_: int) -> str:
            try:
                self.call(handle, nonce="race")
            except BrokerDenied:
                return "denied"
            return "allowed"

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(8)))
        self.assertEqual(outcomes.count("allowed"), 1)
        self.assertEqual(outcomes.count("denied"), 7)

    def test_settle_and_operator_endpoints_are_separate_and_fail_closed(self) -> None:
        ordinary = self.mint(actions=("vault:recall",), targets=("vault",))
        with self.assertRaisesRegex(BrokerDenied, "action|settle"):
            self.broker.dispatch(
                "/v1/vault/record",
                handle=ordinary,
                request_nonce="record",
                body={**model_body(), "note_type": "learning"},
            )
        with self.assertRaisesRegex(BrokerDenied, "operator"):
            self.mint(actions=("operator:action",), targets=("spend",))

    def test_non_model_interfaces_enforce_exact_action_target_and_settle_scope(self) -> None:
        handlers = {
            action: LocalMockActionHandler({"status": "mock-ok", "opaque": CONNECTOR_SECRET})
            for action in ("mcp:github:get", "vault:recall", "vault:record", "egress:http")
        }
        broker = CredentialBroker(
            expected_authority=authority(),
            provider_secrets={},
            provider_transports={},
            action_handlers=handlers,
            action_secrets={action: CONNECTOR_SECRET for action in handlers},
            allow_unbound_local_mock=True,
        )
        requests = (
            ("/v1/mcp/github/get", {"target": "repo:owner/name", "marker": "mcp"}),
            ("/v1/vault/recall", {"marker": "recall"}),
            (
                "/v1/egress/http",
                {"method": "GET", "url": "https://example.test/exact", "marker": "egress"},
            ),
        )
        budget = Budget(4, 1000, 40, 10000, 4096, 512)
        ordinary = scope(
            actions=("mcp:github:get", "vault:recall", "egress:http"),
            targets=("repo:owner/name", "vault", "GET:https://example.test/exact"),
            budget=budget,
            request_body_sha256s=tuple(canonical_request_sha256(body) for _, body in requests),
        )
        for index, (path, body) in enumerate(requests):
            result = broker.dispatch(
                path,
                handle=broker.mint_handle(ordinary, ttl_seconds=30),
                request_nonce=f"ordinary-{index}",
                body=body,
            )
            self.assertEqual(result["opaque"], "[REDACTED]")
        settle_body = {"note_type": "learning", "marker": "record"}
        settle = scope(
            actions=("vault:record",),
            targets=("learning",),
            budget=budget,
            settle_phase=True,
            request_body_sha256s=(canonical_request_sha256(settle_body),),
        )
        broker.dispatch(
            "/v1/vault/record",
            handle=broker.mint_handle(settle, ttl_seconds=30),
            request_nonce="settle",
            body=settle_body,
        )
        self.assertEqual(sum(len(handler.calls) for handler in handlers.values()), 4)
        with self.assertRaisesRegex(BrokerDenied, "request body"):
            broker.dispatch(
                "/v1/mcp/github/get",
                handle=broker.mint_handle(ordinary, ttl_seconds=30),
                request_nonce="widened-body",
                body={"target": "repo:owner/name", "marker": "mcp", "write": True},
            )
        with self.assertRaisesRegex(BrokerDenied, "target"):
            broker.dispatch(
                "/v1/mcp/github/get",
                handle=broker.mint_handle(ordinary, ttl_seconds=30),
                request_nonce="wrong-target",
                body={"target": "repo:other/name"},
            )

    def test_native_client_shape_needs_no_identity_headers_or_body_fields(self) -> None:
        cases = (
            ("claude", "/v1/model/claude/v1/messages", {"messages": []}),
            ("kimi", "/v1/model/kimi/chat/completions", {"messages": []}),
            ("codex", "/v1/model/codex/responses", {"input": "native shape", "max_output_tokens": 20}),
        )
        for lane, path, payload in cases:
            with self.subTest(lane=lane):
                broker = CredentialBroker(
                    expected_authority=authority(lane=lane),
                    provider_secrets={lane: PROVIDER_SECRET},
                    provider_transports={lane: fake_transport()},
                    allow_unbound_local_mock=True,
                )
                native_scope = scope(
                    lane=lane,
                    actions=(f"model:{lane}",),
                    budget=Budget(2, 4096, 40, 100000, 4096),
                )
                handle = broker.mint_handle(native_scope, ttl_seconds=30)
                body = {"model": "mock-model", "max_tokens": 20, **payload}
                result = broker.dispatch(path, handle=handle, request_nonce="", body=body)
                self.assertEqual(result["content"], "local mock only")
                second = {**body, "input": "second distinct native request"}
                broker.dispatch(path, handle=handle, request_nonce="", body=second)
                with self.assertRaisesRegex(BrokerDenied, "replay"):
                    broker.dispatch(path, handle=handle, request_nonce="", body=second)

    def test_forged_prepared_launch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact Task 1.2 PreparedLaunch"):
            self.broker.bind_prepared_launch(object())  # type: ignore[arg-type]

    def test_arbitrary_transport_cannot_bypass_local_mock_boundary(self) -> None:
        def arbitrary(**_: object) -> tuple[int, dict[str, object]]:
            return 200, {}

        with self.assertRaisesRegex(ValueError, "confined local mock"):
            CredentialBroker(
                expected_authority=authority(),
                provider_secrets={"claude": PROVIDER_SECRET},
                provider_transports={"claude": arbitrary},
                allow_unbound_local_mock=True,
            )

    def test_provider_overreported_usage_and_transport_secret_fail_closed(self) -> None:
        broker = CredentialBroker(
            expected_authority=authority(),
            provider_secrets={"claude": PROVIDER_SECRET},
            provider_transports={"claude": LocalMockProviderTransport({
                "usage": {"input_tokens": 1, "output_tokens": 21, "cost_micros": 1}
            })},
            allow_unbound_local_mock=True,
        )
        with self.assertRaisesRegex(BrokerDenied, "exceeded"):
            broker.dispatch(
                "/v1/model/claude",
                handle=broker.mint_handle(scope(), ttl_seconds=30),
                request_nonce="",
                body=model_body(),
            )

        broker = CredentialBroker(
            expected_authority=authority(),
            provider_secrets={"claude": PROVIDER_SECRET},
            provider_transports={"claude": LocalMockProviderTransport({}, failure=PROVIDER_SECRET)},
            allow_unbound_local_mock=True,
        )
        with self.assertRaisesRegex(BrokerDenied, "provider transport failed") as raised:
            broker.dispatch(
                "/v1/model/claude",
                handle=broker.mint_handle(scope(), ttl_seconds=30),
                request_nonce="",
                body=model_body(),
            )
        self.assertNotIn(PROVIDER_SECRET, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn(PROVIDER_SECRET, json.dumps(broker.action_logs))


class MockProviderHandler(BaseHTTPRequestHandler):
    seen_authorization = ""
    started_event: threading.Event | None = None
    release_event: threading.Event | None = None

    def do_POST(self) -> None:  # noqa: N802
        type(self).seen_authorization = self.headers.get("Authorization", "")
        if type(self).started_event is not None:
            type(self).started_event.set()
        if type(self).release_event is not None:
            type(self).release_event.wait(timeout=2)
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if type(self).seen_authorization != f"Bearer {PROVIDER_SECRET}":
            self.send_response(401)
            self.end_headers()
            return
        payload = json.dumps(
            {
                "content": "local-only",
                "usage": {"input_tokens": 4, "output_tokens": 3, "cost_micros": 10},
                "secret": PROVIDER_SECRET,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class LocalHTTPIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = LoopbackHTTPServer(("127.0.0.1", 0), MockProviderHandler)
        self.provider_thread = threading.Thread(target=self.provider.serve_forever, daemon=True)
        self.provider_thread.start()
        provider_url = f"http://127.0.0.1:{self.provider.server_address[1]}/mock"
        transport = LocalHTTPProviderTransport(provider_url, PROVIDER_SECRET)
        self.broker = CredentialBroker(
            expected_authority=authority(),
            provider_secrets={"claude": PROVIDER_SECRET},
            provider_transports={"claude": transport},
            signing_key=b"b" * 32,
            startup_id="integration-startup",
            allow_unbound_local_mock=True,
        )
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        self.server = BrokerHTTPServer(listener, self.broker)
        self.server.start()

    def tearDown(self) -> None:
        self.server.close()
        self.provider.shutdown()
        self.provider.server_close()

    def test_handle_cannot_authenticate_directly_but_brokered_call_succeeds(self) -> None:
        handle = self.broker.mint_handle(scope(), ttl_seconds=30)
        direct = request.Request(
            f"http://127.0.0.1:{self.provider.server_address[1]}/mock",
            data=b"{}",
            headers={"Authorization": f"Bearer {handle}"},
            method="POST",
        )
        with self.assertRaises(error.HTTPError) as direct_error:
            request.urlopen(direct, timeout=2)
        self.assertEqual(direct_error.exception.code, 401)
        direct_error.exception.close()

        brokered = request.Request(
            f"{self.server.base_url}/v1/model/claude/v1/messages",
            data=json.dumps({
                "model": "mock-model",
                "messages": [{"role": "user", "content": "native request"}],
                "max_tokens": 20,
            }).encode(),
            headers={
                "x-api-key": handle,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(brokered, timeout=2) as response:
            payload = json.load(response)
        self.assertEqual(response.status, 200)
        self.assertEqual(MockProviderHandler.seen_authorization, f"Bearer {PROVIDER_SECRET}")
        self.assertNotIn(PROVIDER_SECRET, json.dumps(payload))
        self.assertEqual(payload["secret"], "[REDACTED]")

    def test_transport_rejects_non_loopback_provider_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            LocalHTTPProviderTransport("https://provider.example/v1", PROVIDER_SECRET)

    def test_server_close_revokes_all_handles(self) -> None:
        handle = self.broker.mint_handle(scope(), ttl_seconds=30)
        self.server.close()
        with self.assertRaisesRegex(BrokerDenied, "closed|revoked"):
            self.broker.dispatch(
                "/v1/model/claude", handle=handle, request_nonce="after-close", body=model_body()
            )

    def test_inflight_result_is_denied_after_terminal_revocation(self) -> None:
        started = threading.Event()
        release = threading.Event()
        MockProviderHandler.started_event = started
        MockProviderHandler.release_event = release
        handle = self.broker.mint_handle(scope(), ttl_seconds=30)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self.broker.dispatch,
                    "/v1/model/claude",
                    handle=handle,
                    request_nonce="inflight",
                    body=model_body(),
                )
                self.assertTrue(started.wait(timeout=2))
                self.broker.revoke_all()
                release.set()
                with self.assertRaisesRegex(BrokerDenied, "revoked"):
                    future.result(timeout=3)
        finally:
            release.set()
            MockProviderHandler.started_event = None
            MockProviderHandler.release_event = None


@unittest.skipUnless(sys.platform == "darwin", "PreparedLaunch integration requires macOS Seatbelt")
class PreparedLaunchIntegrationTests(unittest.TestCase):
    def test_broker_borrows_the_exact_canaried_listener(self) -> None:
        fixture_root = ROOT / "_state" / "v2-finalization-2026-07-21-build" / "probe-fixtures"
        fixture_root.mkdir(parents=True, exist_ok=True)
        task_root = Path(tempfile.mkdtemp(prefix="t1p3-prepared-", dir=fixture_root)).resolve()
        prepared = run_preflight_canary(task_root, request_sha256="c" * 64, retain_launch=True)
        self.assertIsInstance(prepared, PreparedLaunch)
        assert isinstance(prepared, PreparedLaunch)
        expected_port = int(prepared.broker_listener.getsockname()[1])
        broker = CredentialBroker(
            expected_authority=authority(
                profile_sha256=prepared.canary.profile_sha256,
                request_sha256=prepared.canary.request_sha256,
                scope_sha256=prepared.canary.scope_sha256,
            ),
            provider_secrets={"claude": PROVIDER_SECRET},
            provider_transports={"claude": fake_transport()},
            signing_key=b"p" * 32,
            startup_id="prepared-startup",
        )
        server = BrokerHTTPServer.from_prepared_launch(prepared, broker)
        self.assertEqual(int(parse_url_port(server.base_url)), expected_port)
        server.start()
        try:
            handle = broker.mint_handle(
                scope(
                    profile_sha256=prepared.canary.profile_sha256,
                    request_sha256=prepared.canary.request_sha256,
                    scope_sha256=prepared.canary.scope_sha256,
                ),
                ttl_seconds=30,
            )
            outbound = request.Request(
                f"{server.base_url}/v1/model/claude/v1/messages",
                data=json.dumps({
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "prepared"}],
                    "max_tokens": 20,
                }).encode(),
                headers={
                    "x-api-key": handle,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with request.urlopen(outbound, timeout=2) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.close()
            self.assertEqual(prepared.broker_listener.fileno(), -1)
            prepared.close()


def parse_url_port(value: str) -> int:
    return int(value.rsplit(":", 1)[1])


if __name__ == "__main__":
    unittest.main()
