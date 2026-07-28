#!/usr/bin/env python3
"""Supervisor-owned, loopback-only broker for opaque task capabilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import base64
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
from typing import Callable, Mapping, Union
from urllib import error, parse, request

from launch_hygiene import PreparedLaunch


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ATTEMPT_RE = re.compile(r"^d-[0-9a-f]{32}$")
TASK_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
HANDLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
MAX_REQUEST_BYTES = 1024 * 1024
REDACTED = "[REDACTED]"
SECRET_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "client_secret",
    "cookie",
    "private_key",
    "password",
    "refresh_token",
    "secret",
    "session",
    "signed_url",
    "token",
}


class BrokerDenied(RuntimeError):
    """A capability or request failed closed."""


@dataclass(frozen=True)
class Budget:
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_micros: int
    max_response_bytes: int
    max_request_bytes: int = MAX_REQUEST_BYTES

    def validate(self) -> None:
        for key, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{key} must be a positive integer")


@dataclass(frozen=True)
class HandleScope:
    task_id: str
    attempt_id: str
    generation: int
    lane: str
    authority_sha256: str
    actions: tuple[str, ...]
    targets: tuple[str, ...]
    budget: Budget
    profile_sha256: str = ""
    request_sha256: str = ""
    scope_sha256: str = ""
    request_body_sha256s: tuple[str, ...] = ()
    settle_phase: bool = False
    operator_approved: bool = False

    def validate(self) -> None:
        if not TASK_RE.fullmatch(self.task_id):
            raise ValueError("invalid task id")
        if not ATTEMPT_RE.fullmatch(self.attempt_id):
            raise ValueError("invalid attempt id")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        if self.lane not in {"claude", "kimi", "codex", "gemini"}:
            raise ValueError("unsupported lane")
        if not SHA256_RE.fullmatch(self.authority_sha256):
            raise ValueError("authority hash must be lowercase SHA-256")
        if not self.actions or not self.targets:
            raise ValueError("actions and targets must be non-empty")
        for values, label in ((self.actions, "action"), (self.targets, "target")):
            if len(set(values)) != len(values):
                raise ValueError(f"duplicate {label}")
            if any(not value or len(value) > 512 or "\x00" in value or "\n" in value for value in values):
                raise ValueError(f"invalid {label}")
        self.budget.validate()
        for value, label in (
            (self.profile_sha256, "profile"),
            (self.request_sha256, "request"),
            (self.scope_sha256, "scope"),
        ):
            if value and not SHA256_RE.fullmatch(value):
                raise ValueError(f"{label} hash must be lowercase SHA-256")
        if len(set(self.request_body_sha256s)) != len(self.request_body_sha256s):
            raise ValueError("duplicate request body hash")
        if any(not SHA256_RE.fullmatch(value) for value in self.request_body_sha256s):
            raise ValueError("request body hash must be lowercase SHA-256")


@dataclass(frozen=True)
class SupervisorAuthority:
    """Trusted task identity supplied by the supervisor, never by the worker."""

    task_id: str
    attempt_id: str
    generation: int
    lane: str
    authority_sha256: str
    profile_sha256: str = ""
    request_sha256: str = ""
    scope_sha256: str = ""

    def validate(self) -> None:
        HandleScope(
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            generation=self.generation,
            lane=self.lane,
            authority_sha256=self.authority_sha256,
            actions=("authority:validate",),
            targets=("authority",),
            budget=Budget(1, 1, 1, 1, 1),
            profile_sha256=self.profile_sha256,
            request_sha256=self.request_sha256,
            scope_sha256=self.scope_sha256,
        ).validate()

    def matches(self, scope: HandleScope) -> bool:
        return (
            scope.task_id,
            scope.attempt_id,
            scope.generation,
            scope.lane,
            scope.authority_sha256,
            scope.profile_sha256,
            scope.request_sha256,
            scope.scope_sha256,
        ) == (
            self.task_id,
            self.attempt_id,
            self.generation,
            self.lane,
            self.authority_sha256,
            self.profile_sha256,
            self.request_sha256,
            self.scope_sha256,
        )


@dataclass
class _StoredHandle:
    scope: HandleScope
    expires_at: float
    startup_id: str
    revoked: bool = False
    request_nonces: set[str] = field(default_factory=set)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0


@dataclass
class _AttemptBudget:
    budget: Budget
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0


@dataclass(frozen=True)
class ProviderHTTPResponse:
    """Provider-native response retained only long enough to return to the CLI."""

    status: int
    body: bytes
    content_type: str
    usage: dict[str, int]
    outbound_sha256: str


ProviderTransport = Callable[
    ...,
    Union[tuple[int, dict[str, object]], ProviderHTTPResponse],
]
ActionHandler = Callable[[dict[str, object]], dict[str, object]]


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def canonical_request_sha256(body: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def _estimate_input_tokens(body: Mapping[str, object]) -> int:
    # One token per serialized byte is deliberately conservative for the local
    # proof and covers system/tool/schema/content fields, not just prompts.
    return max(1, len(_canonical_json(body)))


def _redact(value: object, provider_secrets: tuple[str, ...]) -> object:
    if isinstance(value, dict):
        return {
            str(key): REDACTED
            if str(key).lower() in SECRET_KEYS
            else _redact(item, provider_secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, provider_secrets) for item in value]
    if isinstance(value, str):
        if any(secret and secret in value for secret in provider_secrets):
            return REDACTED
        lowered = value.lower()
        if any(marker in lowered for marker in ("signature=", "x-amz-signature=", "sig=", "token=", "key=")):
            return REDACTED
    return value


def _validated_usage(
    response: Mapping[str, object],
    *,
    reserved_input: int,
    reserved_output: int,
    reserved_cost: int,
) -> tuple[int, int, int]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise BrokerDenied("provider usage is missing")
    limits = {
        "input_tokens": reserved_input,
        "output_tokens": reserved_output,
        "cost_micros": reserved_cost,
    }
    for key, maximum in limits.items():
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BrokerDenied("provider usage is malformed")
        if value > maximum:
            raise BrokerDenied(f"provider {key.replace('_', '-')} exceeded reserved budget")
    return (
        int(usage["input_tokens"]),
        int(usage["output_tokens"]),
        int(usage["cost_micros"]),
    )


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req: object, fp: object, code: int, msg: str, headers: object, newurl: str) -> None:
        return None


class LocalHTTPProviderTransport:
    """Outbound transport that can reach only one literal loopback mock URL."""

    def __init__(self, provider_url: str, provider_secret: str) -> None:
        parsed = parse.urlsplit(provider_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("local mock provider URL must use loopback HTTP")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise ValueError("local mock provider must use a literal loopback address") from exc
        if not address.is_loopback:
            raise ValueError("local mock provider must be loopback-only")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("local mock provider URL contains forbidden components")
        if not provider_secret or "\n" in provider_secret or "\x00" in provider_secret:
            raise ValueError("invalid provider secret")
        self.provider_url = provider_url
        self._provider_secret_fingerprint = hashlib.sha256(provider_secret.encode()).hexdigest()
        self._opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())

    def __call__(
        self,
        *,
        lane: str,
        target: str,
        body: dict[str, object],
        headers: dict[str, str],
        response_limit: int,
    ) -> tuple[int, dict[str, object]]:
        authorization = headers.get("Authorization", "")
        if hashlib.sha256(authorization.removeprefix("Bearer ").encode()).hexdigest() != self._provider_secret_fingerprint:
            raise BrokerDenied("broker auth injection mismatch")
        outbound = request.Request(
            self.provider_url,
            data=_canonical_json(body),
            headers={"Authorization": authorization, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(outbound, timeout=3) as response:
                raw = response.read(response_limit + 1)
                status = int(response.status)
        except error.HTTPError as exc:
            raise BrokerDenied(f"local mock provider rejected request with HTTP {exc.code}") from exc
        except (error.URLError, TimeoutError, socket.timeout) as exc:
            raise BrokerDenied("local mock provider unavailable") from exc
        if len(raw) > response_limit:
            raise BrokerDenied("response-size budget exceeded")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BrokerDenied("local mock provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise BrokerDenied("local mock provider response must be an object")
        return status, payload


REAL_PROVIDER_ORIGINS = {
    "claude": "https://api.anthropic.com",
    "codex": "https://api.openai.com/v1",
    "kimi": "https://api.moonshot.ai/v1",
    "gemini": "https://generativelanguage.googleapis.com",
}


def _provider_payloads(raw: bytes, content_type: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    if content_type.split(";", 1)[0].strip().lower() == "text/event-stream":
        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if not data or data == b"[DONE]":
                continue
            try:
                value = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                payloads.append(value)
    else:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BrokerDenied("provider returned invalid JSON") from exc
        if isinstance(value, list):
            payloads.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            payloads.append(value)
    if not payloads:
        raise BrokerDenied("provider response contains no usable payload")
    return payloads


def _usage_candidates(value: object) -> list[Mapping[str, object]]:
    candidates: list[Mapping[str, object]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"usage", "usageMetadata"} and isinstance(item, dict):
                candidates.append(item)
            candidates.extend(_usage_candidates(item))
    elif isinstance(value, list):
        for item in value:
            candidates.extend(_usage_candidates(item))
    return candidates


def _provider_usage(payloads: list[dict[str, object]], body: Mapping[str, object]) -> dict[str, int]:
    input_keys = ("input_tokens", "prompt_tokens", "promptTokenCount", "inputTokenCount")
    output_keys = ("output_tokens", "completion_tokens", "candidatesTokenCount", "outputTokenCount")
    observed_input = 0
    observed_output = 0
    for payload in payloads:
        for usage in _usage_candidates(payload):
            for key in input_keys:
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    observed_input = max(observed_input, value)
            for key in output_keys:
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    observed_output = max(observed_output, value)
    if observed_input == 0:
        observed_input = _estimate_input_tokens(body)
    if observed_output == 0:
        observed_output = 1
    return {
        "input_tokens": observed_input,
        "output_tokens": observed_output,
        # A deliberately conservative accounting rate. This is an internal
        # spend upper bound, not a claim about a provider's invoice.
        "cost_micros": observed_input * 5 + observed_output * 25,
    }


def _bounded_provider_body(lane: str, body: Mapping[str, object]) -> dict[str, object]:
    bounded = json.loads(_canonical_json(body))
    if lane in {"claude", "kimi"}:
        current = bounded.get("max_tokens", 8)
        bounded["max_tokens"] = min(current, 8) if isinstance(current, int) and not isinstance(current, bool) else 8
    elif lane == "codex":
        current = bounded.get("max_output_tokens", 16)
        bounded["max_output_tokens"] = min(current, 16) if isinstance(current, int) and not isinstance(current, bool) else 16
    else:
        generation = bounded.get("generationConfig")
        if not isinstance(generation, dict):
            generation = {}
            bounded["generationConfig"] = generation
        current = generation.get("maxOutputTokens", 8)
        generation["maxOutputTokens"] = min(current, 8) if isinstance(current, int) and not isinstance(current, bool) else 8
    if lane == "kimi" and bounded.get("stream") is True:
        stream_options = bounded.get("stream_options")
        if not isinstance(stream_options, dict):
            stream_options = {}
            bounded["stream_options"] = stream_options
        stream_options["include_usage"] = True
    return bounded


class RealHTTPSProviderTransport:
    """Fixed-origin HTTPS egress with broker-only credential injection."""

    def __init__(self, lane: str, *, timeout_seconds: int = 15) -> None:
        if lane not in REAL_PROVIDER_ORIGINS:
            raise ValueError("unsupported real provider lane")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 30:
            raise ValueError("provider timeout must be an integer in 1..30")
        self.lane = lane
        self.provider_origin = REAL_PROVIDER_ORIGINS[lane]
        self.timeout_seconds = timeout_seconds
        self._opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())

    def _upstream_url(self, request_path: str, target: str) -> str:
        parsed = parse.urlsplit(request_path)
        if parsed.scheme or parsed.netloc or parsed.fragment or "\\" in parsed.path:
            raise BrokerDenied("invalid native provider path")
        prefix = f"/v1/model/{self.lane}"
        if not parsed.path.startswith(prefix + "/"):
            raise BrokerDenied("wrong native provider path")
        suffix = parsed.path[len(prefix):]
        if any(part in {"", ".", ".."} for part in suffix.split("/")[1:]):
            raise BrokerDenied("non-canonical native provider path")
        query = parse.parse_qsl(parsed.query, keep_blank_values=True)
        if self.lane == "claude":
            if suffix != "/v1/messages" or query:
                raise BrokerDenied("unsupported Claude provider path")
        elif self.lane == "codex":
            if suffix != "/responses" or query:
                raise BrokerDenied("unsupported Codex provider path")
        elif self.lane == "kimi":
            if suffix != "/chat/completions" or query:
                raise BrokerDenied("unsupported Kimi provider path")
        else:
            match = re.fullmatch(
                r"/v1beta/models/([A-Za-z0-9._-]{1,128}):(generateContent|streamGenerateContent)",
                suffix,
            )
            if match is None or match.group(1) != target:
                raise BrokerDenied("unsupported Gemini provider path")
            if query not in ([], [("alt", "sse")]):
                raise BrokerDenied("unsupported Gemini provider query")
        return self.provider_origin + suffix + (f"?{parse.urlencode(query)}" if query else "")

    def __call__(
        self,
        *,
        lane: str,
        target: str,
        body: dict[str, object],
        headers: dict[str, str],
        response_limit: int,
        request_path: str,
        client_headers: Mapping[str, str],
    ) -> ProviderHTTPResponse:
        if lane != self.lane:
            raise BrokerDenied("real provider transport lane mismatch")
        authorization = headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise BrokerDenied("broker-owned provider credential is missing")
        provider_secret = authorization.removeprefix("Bearer ")
        if not provider_secret or any(character in provider_secret for character in ("\n", "\r", "\x00")):
            raise BrokerDenied("broker-owned provider credential is invalid")
        bounded_body = _bounded_provider_body(lane, body)
        outbound_body = _canonical_json(bounded_body)
        if provider_secret.encode() in outbound_body:
            raise BrokerDenied("provider credential appeared in request body")
        upstream_url = self._upstream_url(request_path, target)
        outbound_headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if lane == "claude":
            outbound_headers["x-api-key"] = provider_secret
            outbound_headers["anthropic-version"] = client_headers.get("anthropic-version", "2023-06-01")
            if "anthropic-beta" in client_headers:
                outbound_headers["anthropic-beta"] = client_headers["anthropic-beta"]
        elif lane == "gemini":
            outbound_headers["x-goog-api-key"] = provider_secret
        else:
            outbound_headers["Authorization"] = f"Bearer {provider_secret}"
        outbound = request.Request(
            upstream_url,
            data=outbound_body,
            headers=outbound_headers,
            method="POST",
        )
        try:
            with self._opener.open(outbound, timeout=self.timeout_seconds) as response:
                raw = response.read(response_limit + 1)
                status = int(response.status)
                content_type = response.headers.get("Content-Type", "application/json")
        except error.HTTPError as exc:
            raise BrokerDenied(f"provider rejected request with HTTP {exc.code}") from None
        except (error.URLError, TimeoutError, socket.timeout):
            raise BrokerDenied("provider unavailable") from None
        if len(raw) > response_limit:
            raise BrokerDenied("response-size budget exceeded")
        if provider_secret.encode() in raw:
            raise BrokerDenied("provider credential appeared in response")
        payloads = _provider_payloads(raw, content_type)
        usage = _provider_usage(payloads, bounded_body)
        return ProviderHTTPResponse(
            status=status,
            body=raw,
            content_type=content_type,
            usage=usage,
            outbound_sha256=hashlib.sha256(outbound_body).hexdigest(),
        )


class LocalMockProviderTransport:
    """Deterministic in-memory transport with no network operation."""

    def __init__(self, response: Mapping[str, object], *, status: int = 200, failure: str = "") -> None:
        self._response = json.loads(_canonical_json(dict(response)))
        self._status = status
        self._failure = failure
        self.headers: list[dict[str, str]] = []

    def __call__(
        self,
        *,
        lane: str,
        target: str,
        body: dict[str, object],
        headers: dict[str, str],
        response_limit: int,
    ) -> tuple[int, dict[str, object]]:
        self.headers.append(dict(headers))
        if self._failure:
            raise RuntimeError(self._failure)
        return self._status, json.loads(_canonical_json(self._response))


class LocalMockActionHandler:
    """Deterministic non-model adapter used only for the no-spend local proof."""

    def __init__(self, response: Mapping[str, object]) -> None:
        self._response = json.loads(_canonical_json(dict(response)))
        self.calls: list[str] = []

    def __call__(self, body: dict[str, object]) -> dict[str, object]:
        self.calls.append(canonical_request_sha256(body))
        return json.loads(_canonical_json(self._response))


class CredentialBroker:
    """Thread-safe capability store and policy engine owned by the supervisor."""

    def __init__(
        self,
        *,
        expected_authority: SupervisorAuthority,
        provider_secrets: Mapping[str, str],
        provider_transports: Mapping[str, ProviderTransport],
        action_handlers: Mapping[str, ActionHandler] | None = None,
        action_secrets: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        signing_key: bytes | None = None,
        startup_id: str | None = None,
        allow_unbound_local_mock: bool = False,
    ) -> None:
        self._clock = clock
        expected_authority.validate()
        self._expected_authority = expected_authority
        self._key = bytes(signing_key or secrets.token_bytes(32))
        if len(self._key) < 32:
            raise ValueError("broker signing key must be at least 32 bytes")
        self.startup_id = startup_id or secrets.token_hex(16)
        self._provider_secrets = dict(provider_secrets)
        self._provider_transports = dict(provider_transports)
        self._action_handlers = dict(action_handlers or {})
        self._action_secrets = dict(action_secrets or {})
        if set(self._action_secrets) - set(self._action_handlers):
            raise ValueError("action secrets require a matching action handler")
        for action, handler in self._action_handlers.items():
            if not action.startswith(("mcp:", "vault:", "egress:")):
                raise ValueError("unsupported non-model action handler")
            if type(handler) is not LocalMockActionHandler:
                raise ValueError("action handler must be a confined local mock handler")
        for secret in self._action_secrets.values():
            if not secret or "\n" in secret or "\x00" in secret:
                raise ValueError("invalid broker-owned action secret")
        if set(self._provider_transports) - set(self._provider_secrets):
            raise ValueError("each provider transport requires a broker-owned secret")
        for transport in self._provider_transports.values():
            if type(transport) not in {
                LocalHTTPProviderTransport,
                LocalMockProviderTransport,
                RealHTTPSProviderTransport,
            }:
                raise ValueError(
                    "provider transport must be an approved exact transport; "
                    "arbitrary callables cannot bypass the confined local mock boundary"
                )
        if allow_unbound_local_mock and any(
            type(transport) is RealHTTPSProviderTransport
            for transport in self._provider_transports.values()
        ):
            raise ValueError("real provider transport cannot use the unbound local mock escape hatch")
        for lane, secret in self._provider_secrets.items():
            if lane not in {"claude", "kimi", "codex", "gemini"} or not secret or "\n" in secret:
                raise ValueError("invalid broker-owned provider secret")
        self._handles: dict[str, _StoredHandle] = {}
        self._attempt_budgets: dict[tuple[str, str, int, str, str], _AttemptBudget] = {}
        self._prepared_binding: tuple[str, str, str, int] | None = None
        self._allow_unbound_local_mock = allow_unbound_local_mock
        self._closed = False
        self._lock = threading.RLock()
        self.action_logs: list[dict[str, object]] = []

    def bind_prepared_launch(self, prepared: PreparedLaunch) -> None:
        if not isinstance(prepared, PreparedLaunch):
            raise ValueError("exact Task 1.2 PreparedLaunch type is required")
        if prepared.consumed or not prepared.canary.passed:
            raise ValueError("PreparedLaunch is consumed or its canary failed")
        if prepared.profile.sha256 != prepared.canary.profile_sha256:
            raise ValueError("PreparedLaunch profile hash mismatch")
        if not SHA256_RE.fullmatch(prepared.canary.request_sha256) or not SHA256_RE.fullmatch(prepared.canary.scope_sha256):
            raise ValueError("PreparedLaunch request/scope binding is incomplete")
        listener = prepared.broker_listener
        if listener.fileno() < 0 or listener.family != socket.AF_INET:
            raise ValueError("PreparedLaunch listener must be live AF_INET")
        try:
            accepting = listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
        except OSError as exc:
            if exc.errno != errno.ENOPROTOOPT:
                raise ValueError("PreparedLaunch listener state is unreadable") from exc
        else:
            if accepting != 1:
                raise ValueError("PreparedLaunch listener must already be listening")
        host, port = listener.getsockname()[:2]
        if host != "127.0.0.1" or f"localhost:{port}" not in prepared.profile.text:
            raise ValueError("PreparedLaunch listener does not match the canaried profile")
        binding = (
            prepared.canary.profile_sha256,
            prepared.canary.request_sha256,
            prepared.canary.scope_sha256,
            int(port),
        )
        expected = (
            self._expected_authority.profile_sha256,
            self._expected_authority.request_sha256,
            self._expected_authority.scope_sha256,
            int(port),
        )
        if binding != expected:
            raise ValueError("PreparedLaunch does not match supervisor authority")
        with self._lock:
            if self._prepared_binding is not None and self._prepared_binding != binding:
                raise ValueError("broker is already bound to another PreparedLaunch")
            self._prepared_binding = binding

    def _mac(self, handle_id: str) -> str:
        material = f"{self.startup_id}\0{handle_id}".encode()
        return _b64url(hmac.new(self._key, material, hashlib.sha256).digest())

    def mint_handle(self, scope: HandleScope, *, ttl_seconds: int) -> str:
        scope.validate()
        if not self._expected_authority.matches(scope):
            for field_name, label in (
                ("task_id", "task"),
                ("attempt_id", "attempt"),
                ("generation", "generation"),
                ("lane", "lane"),
                ("authority_sha256", "authority"),
                ("profile_sha256", "profile"),
                ("request_sha256", "request"),
                ("scope_sha256", "scope"),
            ):
                if getattr(scope, field_name) != getattr(self._expected_authority, field_name):
                    raise BrokerDenied(f"wrong or stale {label}")
            raise BrokerDenied("handle scope is outside supervisor authority")
        if self._closed:
            raise BrokerDenied("broker is closed")
        if "operator:action" in scope.actions or scope.operator_approved:
            raise BrokerDenied("operator actions are held and cannot be minted in Task 1.3")
        if self._prepared_binding is None:
            if not self._allow_unbound_local_mock:
                raise BrokerDenied("broker is not bound to a PreparedLaunch")
        else:
            expected = self._prepared_binding[:3]
            observed = (scope.profile_sha256, scope.request_sha256, scope.scope_sha256)
            if observed != expected:
                raise BrokerDenied("handle scope does not match PreparedLaunch hashes")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            raise ValueError("TTL must be an integer in 1..3600")
        handle_id = _b64url(secrets.token_bytes(32))
        token = f"cb1.{handle_id}.{self._mac(handle_id)}"
        with self._lock:
            attempt_key = (
                scope.task_id,
                scope.attempt_id,
                scope.generation,
                scope.lane,
                scope.authority_sha256,
            )
            ledger = self._attempt_budgets.get(attempt_key)
            if ledger is None:
                self._attempt_budgets[attempt_key] = _AttemptBudget(scope.budget)
            elif ledger.budget != scope.budget:
                raise BrokerDenied("attempt budget cannot be widened or replaced")
            self._handles[handle_id] = _StoredHandle(
                scope=scope,
                expires_at=self._clock() + ttl_seconds,
                startup_id=self.startup_id,
            )
        return token

    def _parse_handle(self, handle: str) -> tuple[str, str]:
        if not isinstance(handle, str) or len(handle) > 256 or "\n" in handle or "\x00" in handle:
            raise BrokerDenied("invalid handle")
        parts = handle.split(".")
        if len(parts) != 3 or parts[0] != "cb1" or not HANDLE_ID_RE.fullmatch(parts[1]):
            raise BrokerDenied("invalid handle")
        expected = self._mac(parts[1])
        if not hmac.compare_digest(parts[2], expected):
            raise BrokerDenied("handle MAC or broker restart mismatch")
        return parts[1], parts[2]

    def revoke(self, handle: str) -> None:
        handle_id, _ = self._parse_handle(handle)
        with self._lock:
            stored = self._handles.get(handle_id)
            if stored is None:
                raise BrokerDenied("unknown handle")
            stored.revoked = True

    def revoke_all(self) -> None:
        with self._lock:
            self._closed = True
            for stored in self._handles.values():
                stored.revoked = True

    @staticmethod
    def _attempt_key(scope: HandleScope) -> tuple[str, str, int, str, str]:
        return (
            scope.task_id,
            scope.attempt_id,
            scope.generation,
            scope.lane,
            scope.authority_sha256,
        )

    def _endpoint(self, path: str, body: Mapping[str, object]) -> tuple[str, str, str | None, bool, bool]:
        parsed = parse.urlsplit(path)
        if parsed.fragment:
            raise BrokerDenied("broker endpoint fragment is forbidden")
        parts = [parse.unquote(part) for part in parsed.path.split("/") if part]
        if any("/" in part or part in {".", ".."} for part in parts):
            raise BrokerDenied("non-canonical broker endpoint")
        native_suffixes = {
            "claude": ["v1", "messages"],
            "kimi": ["chat", "completions"],
            "codex": ["responses"],
        }
        if len(parts) >= 3 and parts[:2] == ["v1", "model"]:
            lane = parts[2]
            if lane not in {"claude", "kimi", "codex", "gemini"}:
                raise BrokerDenied("unknown broker lane")
            suffix = parts[3:]
            if lane == "gemini" and suffix:
                if len(suffix) != 3 or suffix[:2] != ["v1beta", "models"]:
                    raise BrokerDenied("unknown Gemini broker endpoint")
                match = re.fullmatch(
                    r"([A-Za-z0-9._-]{1,128}):(generateContent|streamGenerateContent)",
                    suffix[2],
                )
                if match is None:
                    raise BrokerDenied("unknown Gemini broker endpoint")
                query = parse.parse_qsl(parsed.query, keep_blank_values=True)
                if query not in ([], [("alt", "sse")]):
                    raise BrokerDenied("unknown Gemini broker query")
                if match.group(2) == "generateContent" and query:
                    raise BrokerDenied("non-stream Gemini endpoint cannot request SSE")
                target = match.group(1)
            else:
                if parsed.query or suffix not in ([], native_suffixes.get(lane, [])):
                    raise BrokerDenied("unknown broker endpoint")
                target = str(body.get("model", ""))
            return f"model:{lane}", target, lane, False, False
        if parsed.query:
            raise BrokerDenied("broker endpoint query is forbidden")
        if len(parts) == 4 and parts[:2] == ["v1", "mcp"]:
            return f"mcp:{parts[2]}:{parts[3]}", str(body.get("target", "")), None, False, False
        if parts == ["v1", "vault", "recall"]:
            return "vault:recall", "vault", None, False, False
        if parts == ["v1", "vault", "record"]:
            return "vault:record", str(body.get("note_type", "")), None, True, False
        if parts == ["v1", "egress", "http"]:
            return "egress:http", f"{body.get('method', '')}:{body.get('url', '')}", None, False, False
        if parts == ["v1", "operator-action"]:
            return "operator:action", str(body.get("category", "")), None, False, True
        raise BrokerDenied("unknown broker endpoint")

    def _reserve(
        self,
        *,
        handle: str,
        request_nonce: str,
        action: str,
        target: str,
        lane: str | None,
        settle_required: bool,
        operator_required: bool,
        body: Mapping[str, object],
    ) -> tuple[_StoredHandle, _AttemptBudget, int, int, int]:
        handle_id, _ = self._parse_handle(handle)
        if request_nonce and not NONCE_RE.fullmatch(request_nonce):
            raise BrokerDenied("invalid request nonce")
        with self._lock:
            if self._closed:
                raise BrokerDenied("broker is closed")
            stored = self._handles.get(handle_id)
            if stored is None or stored.startup_id != self.startup_id:
                raise BrokerDenied("unknown handle after broker restart")
            scope = stored.scope
            if stored.revoked:
                raise BrokerDenied("revoked handle")
            if self._clock() >= stored.expires_at:
                raise BrokerDenied("expired handle")
            replay_key = request_nonce or hashlib.sha256(_canonical_json(body)).hexdigest()
            if replay_key in stored.request_nonces:
                raise BrokerDenied("request replay")
            if lane is not None and lane != scope.lane:
                raise BrokerDenied("wrong lane")
            if action not in scope.actions:
                raise BrokerDenied("action is outside handle authority")
            if target not in scope.targets:
                raise BrokerDenied("wrong target")
            if settle_required and not scope.settle_phase:
                raise BrokerDenied("settle-phase handle required")
            if operator_required and not scope.operator_approved:
                raise BrokerDenied("operator action is unavailable without a held token")
            expected_identity = {
                "task_id": scope.task_id,
                "attempt_id": scope.attempt_id,
                "generation": scope.generation,
                "authority_sha256": scope.authority_sha256,
            }
            for key, expected in expected_identity.items():
                if key in body and body.get(key) != expected:
                    label = "authority" if key == "authority_sha256" else key.replace("_", "-")
                    raise BrokerDenied(f"wrong {label}")

            request_bytes = _canonical_json(body)
            request_digest = hashlib.sha256(request_bytes).hexdigest()
            if len(request_bytes) > scope.budget.max_request_bytes:
                raise BrokerDenied("request-size budget exceeded")
            if lane is None and request_digest not in scope.request_body_sha256s:
                raise BrokerDenied("request body is outside exact action authority")
            estimated_input = _estimate_input_tokens(body)
            max_output = body.get("max_tokens", body.get("max_output_tokens", 1))
            if lane == "gemini":
                generation = body.get("generationConfig", {})
                max_output = generation.get("maxOutputTokens", 8) if isinstance(generation, dict) else 8
            if isinstance(max_output, bool) or not isinstance(max_output, int) or max_output <= 0:
                raise BrokerDenied("invalid output-token request")
            estimated_cost = estimated_input * 5 + max_output * 25
            minimum_response = max_output
            attempt = self._attempt_budgets[self._attempt_key(scope)]
            budget = attempt.budget
            if attempt.calls + 1 > budget.max_calls:
                raise BrokerDenied("request-count budget exceeded")
            if attempt.input_tokens + estimated_input > budget.max_input_tokens:
                raise BrokerDenied("input-token budget exceeded")
            if attempt.output_tokens + max_output > budget.max_output_tokens:
                raise BrokerDenied("output-token budget exceeded")
            if attempt.cost_micros + estimated_cost > budget.max_cost_micros:
                raise BrokerDenied("dollar budget exceeded")
            if minimum_response > budget.max_response_bytes:
                raise BrokerDenied("response-size budget exceeded")
            stored.request_nonces.add(replay_key)
            attempt.calls += 1
            attempt.input_tokens += estimated_input
            attempt.output_tokens += max_output
            attempt.cost_micros += estimated_cost
            return stored, attempt, estimated_input, max_output, estimated_cost

    def _reconcile_actual_usage(
        self,
        attempt: _AttemptBudget,
        reserved: tuple[int, int, int],
        actual: tuple[int, int, int],
    ) -> None:
        with self._lock:
            attempt.input_tokens += actual[0] - reserved[0]
            attempt.output_tokens += actual[1] - reserved[1]
            attempt.cost_micros += actual[2] - reserved[2]

    def _log(
        self,
        *,
        stored: _StoredHandle,
        attempt: _AttemptBudget,
        action: str,
        target: str,
        request_nonce: str,
        request_body: Mapping[str, object],
        response: object,
        decision: str,
    ) -> None:
        record = {
            "decision": decision,
            "task_sha256": hashlib.sha256(stored.scope.task_id.encode()).hexdigest(),
            "attempt_sha256": hashlib.sha256(stored.scope.attempt_id.encode()).hexdigest(),
            "generation": stored.scope.generation,
            "lane": stored.scope.lane,
            "action": action,
            "target_sha256": hashlib.sha256(target.encode()).hexdigest(),
            "nonce_sha256": hashlib.sha256(request_nonce.encode()).hexdigest() if request_nonce else None,
            "request_sha256": hashlib.sha256(_canonical_json(request_body)).hexdigest(),
            "response_sha256": hashlib.sha256(_canonical_json(response)).hexdigest(),
            "calls": attempt.calls,
            "input_tokens": attempt.input_tokens,
            "output_tokens": attempt.output_tokens,
            "cost_micros": attempt.cost_micros,
        }
        with self._lock:
            self.action_logs.append(record)

    def _log_reservation_denial(
        self,
        *,
        action: str,
        target: str,
        request_nonce: str,
        request_body: Mapping[str, object],
    ) -> None:
        record = {
            "decision": "deny",
            "phase": "reserve",
            "action": action,
            "target_sha256": hashlib.sha256(target.encode()).hexdigest(),
            "nonce_sha256": hashlib.sha256(request_nonce.encode()).hexdigest() if request_nonce else None,
            "request_sha256": hashlib.sha256(_canonical_json(request_body)).hexdigest(),
        }
        with self._lock:
            self.action_logs.append(record)

    def dispatch(
        self,
        path: str,
        *,
        handle: str,
        request_nonce: str,
        body: dict[str, object],
        raw_http: bool = False,
        client_headers: Mapping[str, str] | None = None,
    ) -> dict[str, object] | ProviderHTTPResponse:
        if not isinstance(body, dict):
            raise BrokerDenied("request body must be an object")
        action, target, lane, settle_required, operator_required = self._endpoint(path, body)
        try:
            stored, attempt, reserved_input, reserved_output, reserved_cost = self._reserve(
                handle=handle,
                request_nonce=request_nonce,
                action=action,
                target=target,
                lane=lane,
                settle_required=settle_required,
                operator_required=operator_required,
                body=body,
            )
        except BrokerDenied:
            self._log_reservation_denial(
                action=action,
                target=target,
                request_nonce=request_nonce,
                request_body=body,
            )
            raise
        try:
            if lane is not None:
                transport = self._provider_transports.get(lane)
                secret = self._provider_secrets.get(lane)
                if transport is None or secret is None:
                    raise BrokerDenied("provider adapter unavailable")
                if type(transport) is RealHTTPSProviderTransport:
                    provider_http = transport(
                        lane=lane,
                        target=target,
                        body=body,
                        headers={"Authorization": f"Bearer {secret}"},
                        response_limit=stored.scope.budget.max_response_bytes,
                        request_path=path,
                        client_headers=dict(client_headers or {}),
                    )
                    if not 200 <= provider_http.status < 300:
                        raise BrokerDenied(f"provider returned HTTP {provider_http.status}")
                    response = {
                        "usage": provider_http.usage,
                        "provider_status": provider_http.status,
                        "provider_body_sha256": hashlib.sha256(provider_http.body).hexdigest(),
                        "outbound_sha256": provider_http.outbound_sha256,
                    }
                else:
                    status, response = transport(
                        lane=lane,
                        target=target,
                        body=body,
                        headers={"Authorization": f"Bearer {secret}"},
                        response_limit=stored.scope.budget.max_response_bytes,
                    )
                    provider_http = None
                    if not 200 <= status < 300:
                        raise BrokerDenied(f"provider returned HTTP {status}")
                actual_usage = _validated_usage(
                    response,
                    reserved_input=reserved_input,
                    reserved_output=reserved_output,
                    reserved_cost=reserved_cost,
                )
                self._reconcile_actual_usage(
                    attempt,
                    (reserved_input, reserved_output, reserved_cost),
                    actual_usage,
                )
            else:
                handler = self._action_handlers.get(action)
                if handler is None:
                    if operator_required:
                        raise BrokerDenied("operator action unavailable")
                    raise BrokerDenied("broker action adapter unavailable")
                response = handler(body)
            with self._lock:
                if self._closed or stored.revoked:
                    raise BrokerDenied("handle revoked during broker action")
            redacted = _redact(
                response,
                tuple(self._provider_secrets.values()) + tuple(self._action_secrets.values()),
            )
            if not isinstance(redacted, dict):
                raise BrokerDenied("broker response must be an object")
            if len(_canonical_json(redacted)) > stored.scope.budget.max_response_bytes:
                raise BrokerDenied("response-size budget exceeded")
            self._log(
                stored=stored,
                attempt=attempt,
                action=action,
                target=target,
                request_nonce=request_nonce,
                request_body=body,
                response=redacted,
                decision="allow",
            )
            if lane is not None and provider_http is not None:
                if not raw_http:
                    raise BrokerDenied("provider-native response requires HTTP dispatch")
                return provider_http
            return redacted
        except BrokerDenied:
            self._log(
                stored=stored,
                attempt=attempt,
                action=action,
                target=target,
                request_nonce=request_nonce,
                request_body=body,
                response={"status": "denied"},
                decision="deny",
            )
            raise
        except Exception:
            self._log(
                stored=stored,
                attempt=attempt,
                action=action,
                target=target,
                request_nonce=request_nonce,
                request_body=body,
                response={"status": "denied"},
                decision="deny",
            )
            raise BrokerDenied("provider transport failed") from None


class _BrokerHandler(BaseHTTPRequestHandler):
    server: "_ExistingSocketServer"

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.headers.get("Transfer-Encoding") is not None:
                raise BrokerDenied("transfer encoding is forbidden")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise BrokerDenied("exactly one content length is required")
            length = int(lengths[0])
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise BrokerDenied("invalid request size")
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise BrokerDenied("content type must be application/json")
            expected_host = f"{self.server.server_address[0]}:{self.server.server_address[1]}"
            if self.headers.get("Host", "") != expected_host:
                raise BrokerDenied("host override is forbidden")
            raw = self.rfile.read(length)
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise BrokerDenied("request body must be an object")
            authorization_values = self.headers.get_all("Authorization", [])
            api_key_values = self.headers.get_all("x-api-key", [])
            google_api_key_values = self.headers.get_all("x-goog-api-key", [])
            if len(authorization_values) + len(api_key_values) + len(google_api_key_values) != 1:
                raise BrokerDenied("exactly one broker authorization value is required")
            if authorization_values:
                authorization = authorization_values[0]
                if not authorization.startswith("Bearer "):
                    raise BrokerDenied("unsupported broker authorization scheme")
                handle = authorization.removeprefix("Bearer ")
            elif api_key_values:
                handle = api_key_values[0]
            else:
                handle = google_api_key_values[0]
            result = self.server.broker.dispatch(
                self.path,
                handle=handle,
                request_nonce=self.headers.get("X-Broker-Nonce", ""),
                body=body,
                raw_http=True,
                client_headers={
                    key: value
                    for key in ("anthropic-version", "anthropic-beta", "user-agent")
                    if (value := self.headers.get(key)) is not None
                },
            )
            if isinstance(result, ProviderHTTPResponse):
                status = result.status
                payload = result.body
                response_content_type = result.content_type
            else:
                status = 200
                payload = _canonical_json(result)
                response_content_type = "application/json"
        except Exception:
            status = 403
            payload = _canonical_json({"status": "denied", "reason": "request denied"})
            response_content_type = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", response_content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class _ExistingSocketServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, listener: socket.socket, broker: CredentialBroker) -> None:
        address = listener.getsockname()
        if len(address) < 2 or address[0] not in {"127.0.0.1", "::1"}:
            raise ValueError("broker listener must be loopback-only")
        super().__init__(address, _BrokerHandler, bind_and_activate=False)
        self.socket.close()
        self.socket = listener
        self.server_address = address
        self.broker = broker
        self._worker_slots = threading.BoundedSemaphore(8)

    def get_request(self) -> tuple[socket.socket, object]:
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address

    def process_request(self, request_socket: socket.socket, client_address: object) -> None:
        if not self._worker_slots.acquire(blocking=False):
            self.shutdown_request(request_socket)
            return
        try:
            super().process_request(request_socket, client_address)
        except Exception:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request_socket: socket.socket, client_address: object) -> None:
        try:
            super().process_request_thread(request_socket, client_address)
        finally:
            self._worker_slots.release()

    def join_workers(self, timeout: float) -> bool:
        threads = getattr(self, "_threads", None)
        if threads is None:
            return True
        try:
            active = list(threads)
        except TypeError:
            return True
        deadline = time.monotonic() + timeout
        for thread in active:
            thread.join(max(0.0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in active)


class BrokerHTTPServer:
    """Lifecycle wrapper around a task-exclusive supervisor listener."""

    def __init__(self, listener: socket.socket, broker: CredentialBroker) -> None:
        self._server = _ExistingSocketServer(listener, broker)
        self._thread: threading.Thread | None = None

    @classmethod
    def from_prepared_launch(cls, prepared: PreparedLaunch, broker: CredentialBroker) -> "BrokerHTTPServer":
        broker.bind_prepared_launch(prepared)
        return cls(prepared.broker_listener, broker)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        literal = f"[{host}]" if ":" in host else host
        return f"http://{literal}:{port}"

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("broker server already started")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="task-credential-broker",
            daemon=False,
        )
        self._thread.start()

    def close(self) -> None:
        self._server.broker.revoke_all()
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                raise RuntimeError("broker server did not terminate")
        workers_stopped = self._server.join_workers(5.0)
        self._server.server_close()
        if not workers_stopped:
            raise RuntimeError("broker request workers did not terminate within deadline")
        self._thread = None
