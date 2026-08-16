#!/usr/bin/env python3
"""Per-attempt chrono-vault broker and path-free worker stdio relay.

The supervisor owns :class:`VaultBroker` outside the worker's Seatbelt domain.
The worker launches only ``broker.py relay``.  That relay knows a loopback port
and a one-attempt bearer token; it never receives a vault filesystem address.

The transport deliberately relays MCP stdio bytes without interpreting them.
Memory aperture and clearance remain owned by the ordinary chrono-vault MCP
server, which the broker starts with the controller-authenticated environment.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import hmac
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Mapping, Sequence


LOOPBACK_HOST = "127.0.0.1"
TOKEN_ENV = "CHRONO_VAULT_BROKER_TOKEN"
CONTEXT_ENV = "CHRONO_VAULT_CONTEXT"
ROOT_ENV = "CHRONO_VAULT_ROOT"
ROOT_ALIASES = (ROOT_ENV, "OBSIDIAN_VAULT_ROOT")
AUTH_SCHEMA = "chrono-vault-broker-auth/v1"
AUTH_RESULT_SCHEMA = "chrono-vault-broker-auth-result/v1"
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
MAX_AUTH_LINE = 2048
STARTUP_GRACE_SECONDS = 0.15
READY_TIMEOUT_SECONDS = 2.0
AUTH_TIMEOUT_SECONDS = 3.0


class BrokerError(RuntimeError):
    """The broker boundary could not be established safely."""


class BrokerDenied(BrokerError):
    """A stable, typed broker denial safe to expose to the relay."""

    def __init__(self, code: str, message: str) -> None:
        if IDENTITY_RE.fullmatch(code) is None:
            raise ValueError("broker denial code is invalid")
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BrokerBinding:
    task_id: str
    attempt_id: str
    generation: int
    server_name: str = "chrono-vault"


@dataclass(frozen=True)
class BrokerStatus:
    port: int
    backend_pid: int
    authenticated: bool
    backend_returncode: int | None


def _valid_binding(value: BrokerBinding) -> BrokerBinding:
    if not isinstance(value, BrokerBinding):
        raise BrokerError("broker binding is invalid")
    if (
        IDENTITY_RE.fullmatch(value.task_id) is None
        or IDENTITY_RE.fullmatch(value.attempt_id) is None
        or IDENTITY_RE.fullmatch(value.server_name) is None
        or isinstance(value.generation, bool)
        or not isinstance(value.generation, int)
        or value.generation < 1
    ):
        raise BrokerError("broker binding is invalid")
    return value


def _valid_port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise BrokerError(f"broker port must be an integer in 1..65535, got {value!r}")
    return value


def _valid_token(value: object) -> str:
    if not isinstance(value, str) or TOKEN_RE.fullmatch(value) is None:
        raise BrokerError("broker token must be exactly 32 lowercase-hex bytes")
    return value


def _decode_context(environment: Mapping[str, str]) -> dict[str, object]:
    raw = environment.get(CONTEXT_ENV)
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > 4096:
        raise BrokerError("broker memory context is missing or invalid")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BrokerError("broker memory context is not JSON") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != "chrono-vault-context/v1"
        or value.get("aperture")
        not in {"rich", "focused", "cold", "pool_blind", "none"}
    ):
        raise BrokerError("broker memory context has an invalid schema or aperture")
    return value


def _validate_backend_environment(environment: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(environment, Mapping):
        raise BrokerError("broker backend environment must be a mapping")
    result: dict[str, str] = {}
    for name, value in environment.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or not name
            or "\x00" in name
            or "\x00" in value
        ):
            raise BrokerError("broker backend environment contains an invalid value")
        result[name] = value
    context = _decode_context(result)
    root = result.get(ROOT_ENV)
    if context["aperture"] == "none":
        # `none` must be testable on a host with no private vault at all.  The
        # authenticated relay receives a typed denial before a backend exists.
        for name in ROOT_ALIASES:
            result.pop(name, None)
    else:
        if (
            not isinstance(root, str)
            or not root
            or "\x00" in root
            or "${" in root
            or not Path(root).is_absolute()
        ):
            raise BrokerError("permitted aperture requires one absolute vault root")
        try:
            canonical_root = Path(os.path.realpath(root)).resolve(strict=True)
        except (OSError, RuntimeError):
            raise BrokerError("permitted aperture vault root is unavailable") from None
        if not canonical_root.is_dir():
            raise BrokerError("permitted aperture vault root is unavailable")
        for name in ROOT_ALIASES:
            alias = result.get(name)
            if alias is None:
                continue
            if not Path(alias).is_absolute() or "${" in alias:
                raise BrokerError("vault root alias is invalid")
            try:
                canonical_alias = Path(os.path.realpath(alias)).resolve(strict=True)
            except (OSError, RuntimeError):
                raise BrokerError("vault root alias is unavailable") from None
            if canonical_alias != canonical_root:
                raise BrokerError("vault root aliases resolve to different directories")
        try:
            from vaultroot import PUBLIC_ROOTS, read_sentinel

            for public_root in PUBLIC_ROOTS:
                if os.path.commonpath((canonical_root, Path(public_root).resolve())) == str(
                    Path(public_root).resolve()
                ):
                    raise BrokerError("vault root cannot be inside a public worktree")
            read_sentinel(canonical_root)
        except BrokerError:
            raise
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            raise BrokerError(f"vault root validation failed: {exc}") from exc
        result[ROOT_ENV] = str(canonical_root)
        result.pop("OBSIDIAN_VAULT_ROOT", None)
    return result


def _validate_backend_command(command: Sequence[str]) -> tuple[str, ...]:
    if (
        not isinstance(command, Sequence)
        or isinstance(command, (str, bytes))
        or not command
        or any(not isinstance(item, str) or not item or "\x00" in item for item in command)
    ):
        raise BrokerError("broker backend command is invalid")
    executable = Path(command[0])
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise BrokerError("broker backend executable is unavailable")
    return tuple(command)


def _socket_port(listener: socket.socket) -> int:
    if not isinstance(listener, socket.socket) or listener.family != socket.AF_INET:
        raise BrokerError("broker requires one IPv4 loopback listener")
    try:
        host, port = listener.getsockname()[:2]
        accepting = listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
    except OSError as exc:
        raise BrokerError(f"broker listener is unavailable: {exc}") from exc
    if host != LOOPBACK_HOST or accepting != 1:
        raise BrokerError("broker listener must be bound and listening on 127.0.0.1")
    return _valid_port(port)


def _read_line(connection: socket.socket) -> bytes:
    value = bytearray()
    while len(value) < MAX_AUTH_LINE:
        chunk = connection.recv(1)
        if not chunk:
            break
        value.extend(chunk)
        if chunk == b"\n":
            break
    return bytes(value)


def _canonical_json_line(value: Mapping[str, object]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise BrokerError(f"broker protocol value is invalid: {exc}") from exc
    if len(encoded) > MAX_AUTH_LINE:
        raise BrokerError("broker protocol value exceeds its size bound")
    return encoded


def _auth_payload(token: str, binding: BrokerBinding) -> dict[str, object]:
    return {
        "schema": AUTH_SCHEMA,
        "token": token,
        "task_id": binding.task_id,
        "attempt_id": binding.attempt_id,
        "generation": binding.generation,
        "server_name": binding.server_name,
    }


def _auth_result(*, ok: bool, code: str | None = None) -> bytes:
    payload: dict[str, object] = {"schema": AUTH_RESULT_SCHEMA, "ok": ok}
    if code is not None:
        payload["code"] = code
    return _canonical_json_line(payload)


def _write_all_fd(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


class VaultBroker:
    """One authenticated connection to one per-attempt MCP backend."""

    def __init__(
        self,
        *,
        listener: socket.socket,
        token: str,
        binding: BrokerBinding,
        backend_command: Sequence[str],
        backend_environment: Mapping[str, str],
        backend_cwd: Path | None = None,
    ) -> None:
        self._listener = listener
        self._port = _socket_port(listener)
        self._token = _valid_token(token)
        self._binding = _valid_binding(binding)
        self._backend_command = _validate_backend_command(backend_command)
        self._backend_environment = _validate_backend_environment(backend_environment)
        self._aperture = _decode_context(self._backend_environment)["aperture"]
        self._backend_cwd = Path(backend_cwd) if backend_cwd is not None else None
        if self._backend_cwd is not None and (
            not self._backend_cwd.is_absolute() or not self._backend_cwd.is_dir()
        ):
            raise BrokerError("broker backend cwd is unavailable")
        self._backend: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._authenticated = threading.Event()
        self._failure: BrokerError | None = None
        self._stderr = bytearray()
        self._lock = threading.Lock()
        self._closed = False

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> BrokerStatus:
        if self._backend is not None or self._thread is not None:
            raise BrokerError("broker is one-shot and has already started")
        # A permitted aperture must prove that its MCP backend is alive before
        # the supervisor launches the worker.  Deferring this until the relay
        # authenticates turns a missing interpreter/import into a post-launch
        # outage and makes the caller appear fail-closed when it is not.
        # Aperture ``none`` deliberately has no backend: the broker returns its
        # stable typed denial without requiring a private vault to exist.
        if self._aperture != "none":
            self._start_backend()
        # The retained preflight listener carries a short canary timeout.  Once
        # ownership transfers to the broker it must remain alive until the
        # selected worker actually opens its relay.
        try:
            self._listener.settimeout(None)
        except OSError as exc:
            raise BrokerError(f"broker listener ownership transfer failed: {exc}") from exc
        self._thread = threading.Thread(
            target=self._serve,
            name=f"vault-broker-{self._port}",
            daemon=True,
        )
        try:
            self._thread.start()
        except RuntimeError as exc:
            raise BrokerError(f"broker thread could not start: {exc}") from exc
        if not self._ready.wait(READY_TIMEOUT_SECONDS) or not self._thread.is_alive():
            raise BrokerError("broker listener did not become ready")
        # Give an immediate accept failure one scheduling turn to become
        # visible.  Readiness means the serve loop is alive, not merely that
        # the thread reached its first line.
        time.sleep(0.01)
        if self._failure is not None or not self._thread.is_alive():
            raise BrokerError(
                "broker listener failed during startup"
                + (f": {self._failure}" if self._failure is not None else "")
            )
        return self.require_ready()

    def require_ready(self) -> BrokerStatus:
        """Fail if the listener/backend can no longer serve this attempt."""

        thread = self._thread
        if (
            thread is None
            or not thread.is_alive()
            or self._listener.fileno() < 0
            or self._failure is not None
        ):
            raise BrokerError(
                "broker is not ready"
                + (f": {self._failure}" if self._failure is not None else "")
            )
        backend = self._backend
        if self._aperture != "none" and (
            backend is None or backend.poll() is not None
        ):
            raise BrokerError("chrono-vault backend is not ready")
        return self.status()

    def _start_backend(self) -> subprocess.Popen[bytes]:
        if self._backend is not None:
            raise BrokerError("chrono-vault backend was already started")
        try:
            backend = subprocess.Popen(
                self._backend_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self._backend_cwd) if self._backend_cwd is not None else None,
                env=self._backend_environment,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise BrokerError(f"chrono-vault backend could not start: {exc}") from exc
        self._backend = backend
        threading.Thread(
            target=self._drain_stderr,
            name="vault-broker-stderr",
            daemon=True,
        ).start()
        time.sleep(STARTUP_GRACE_SECONDS)
        if backend.poll() is not None:
            message = self.diagnostics()
            raise BrokerError(
                "chrono-vault backend exited during startup"
                + (f": {message}" if message else f" (exit {backend.returncode})")
            )
        return backend

    def _drain_stderr(self) -> None:
        backend = self._backend
        if backend is None or backend.stderr is None:
            return
        try:
            descriptor = backend.stderr.fileno()
            for chunk in iter(lambda: os.read(descriptor, 4096), b""):
                with self._lock:
                    self._stderr.extend(chunk)
                    if len(self._stderr) > 8192:
                        del self._stderr[:-8192]
        except OSError:
            return

    def _serve(self) -> None:
        self._ready.set()
        expected = _auth_payload(self._token, self._binding)
        while not self._stop.is_set():
            try:
                connection, address = self._listener.accept()
            except OSError:
                if not self._stop.is_set():
                    self._failure = BrokerError("broker listener failed before authentication")
                return
            if not address or address[0] != LOOPBACK_HOST:
                connection.close()
                continue
            try:
                connection.settimeout(AUTH_TIMEOUT_SECONDS)
                supplied_line = _read_line(connection)
                try:
                    supplied = json.loads(supplied_line)
                except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                    supplied = None
                canonical_supplied = (
                    _canonical_json_line(supplied)
                    if isinstance(supplied, dict)
                    else b""
                )
                canonical_expected = _canonical_json_line(expected)
                if not hmac.compare_digest(canonical_supplied, canonical_expected):
                    connection.sendall(_auth_result(ok=False, code="broker_auth_denied"))
                    connection.close()
                    continue
                self._authenticated.set()
                if self._aperture == "none":
                    connection.sendall(
                        _auth_result(ok=False, code="memory_aperture_denied")
                    )
                    connection.close()
                    self._failure = BrokerDenied(
                        "memory_aperture_denied",
                        "chrono-vault is unavailable for memory aperture none",
                    )
                    return
                backend = self._backend
                if backend is None or backend.poll() is not None:
                    connection.sendall(
                        _auth_result(ok=False, code="broker_backend_unavailable")
                    )
                    connection.close()
                    raise BrokerError("chrono-vault backend is unavailable")
                if backend.stdin is None or backend.stdout is None:
                    connection.sendall(
                        _auth_result(ok=False, code="broker_backend_unavailable")
                    )
                    connection.close()
                    raise BrokerError("chrono-vault backend pipes are unavailable")
                connection.sendall(_auth_result(ok=True))
                connection.settimeout(None)
                self._bridge(connection, backend.stdin, backend.stdout)
                return
            except (BrokerError, OSError) as exc:
                connection.close()
                self._failure = BrokerError(f"broker relay failed: {exc}")
                return

    def _bridge(
        self,
        connection: socket.socket,
        backend_stdin: BinaryIO,
        backend_stdout: BinaryIO,
    ) -> None:
        def client_to_backend() -> None:
            try:
                for chunk in iter(lambda: connection.recv(65536), b""):
                    backend_stdin.write(chunk)
                    backend_stdin.flush()
            except (OSError, ValueError):
                pass
            finally:
                try:
                    backend_stdin.close()
                except OSError:
                    pass

        inbound = threading.Thread(
            target=client_to_backend,
            name="vault-broker-input",
            daemon=True,
        )
        inbound.start()
        try:
            descriptor = backend_stdout.fileno()
            for chunk in iter(lambda: os.read(descriptor, 65536), b""):
                connection.sendall(chunk)
        finally:
            try:
                connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            connection.close()
            inbound.join(timeout=2)

    def status(self) -> BrokerStatus:
        backend = self._backend
        return BrokerStatus(
            port=self._port,
            backend_pid=backend.pid if backend is not None else 0,
            authenticated=self._authenticated.is_set(),
            backend_returncode=backend.poll() if backend is not None else None,
        )

    def diagnostics(self) -> str:
        with self._lock:
            value = bytes(self._stderr)
        if self._failure is not None:
            value += ("\n" + str(self._failure)).encode("utf-8", "replace")
        return value.decode("utf-8", "replace").strip()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failures: list[str] = []
        self._stop.set()
        try:
            self._listener.close()
        except OSError as exc:
            failures.append(f"listener close failed: {exc}")
        backend = self._backend
        if backend is not None and backend.poll() is None:
            try:
                os.killpg(backend.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try:
                backend.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(backend.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    backend.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    failures.append("backend did not exit after SIGKILL")
        if self._thread is not None and self._thread.ident is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                failures.append("broker thread did not stop")
        if self._failure is not None and not isinstance(self._failure, BrokerDenied):
            failures.append(f"broker runtime failed: {self._failure}")
        if failures:
            raise BrokerError("; ".join(failures))

    def __enter__(self) -> "VaultBroker":
        try:
            self.start()
        except BaseException:
            try:
                self.close()
            except BrokerError:
                pass
            raise
        return self

    def __exit__(self, _kind, _value, _trace) -> None:
        self.close()


def relay(*, port: int, token: str, binding: BrokerBinding) -> int:
    """Bridge this process's stdio to one authenticated loopback broker."""

    _valid_port(port)
    _valid_token(token)
    binding = _valid_binding(binding)
    if any(name in os.environ for name in ROOT_ALIASES):
        raise BrokerError("vault relay refuses a worker environment containing a vault path")
    try:
        connection = socket.create_connection((LOOPBACK_HOST, port), timeout=5)
    except OSError as exc:
        raise BrokerError(f"chrono-vault broker is unreachable: {exc}") from exc
    try:
        connection.settimeout(AUTH_TIMEOUT_SECONDS)
        connection.sendall(_canonical_json_line(_auth_payload(token, binding)))
        response_line = _read_line(connection)
        try:
            response = json.loads(response_line)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            response = None
        if (
            not isinstance(response, dict)
            or response.get("schema") != AUTH_RESULT_SCHEMA
            or not isinstance(response.get("ok"), bool)
        ):
            raise BrokerDenied("broker_protocol_error", "broker returned an invalid auth result")
        if response["ok"] is not True:
            code = response.get("code")
            if not isinstance(code, str) or IDENTITY_RE.fullmatch(code) is None:
                code = "broker_auth_denied"
            raise BrokerDenied(code, f"chrono-vault broker denied relay: {code}")
        connection.settimeout(None)
    except BaseException:
        connection.close()
        raise

    def stdin_to_socket() -> None:
        try:
            for chunk in iter(lambda: os.read(sys.stdin.fileno(), 65536), b""):
                connection.sendall(chunk)
        except OSError:
            pass
        finally:
            try:
                connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    inbound = threading.Thread(target=stdin_to_socket, name="vault-relay-input", daemon=True)
    inbound.start()
    try:
        for chunk in iter(lambda: connection.recv(65536), b""):
            _write_all_fd(sys.stdout.fileno(), chunk)
    finally:
        connection.close()
        inbound.join(timeout=2)
    return 0


def _error_payload(exc: BaseException) -> str:
    code = exc.code if isinstance(exc, BrokerDenied) else "broker_unreachable"
    return json.dumps(
        {
            "schema": "chrono-vault-relay-error/v1",
            "code": code,
            "message": " ".join(str(exc).split())[:512],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    relay_parser = subparsers.add_parser("relay", help="relay stdio to the attempt broker")
    relay_parser.add_argument("--port", type=int, required=True)
    relay_parser.add_argument("--task-id", required=True)
    relay_parser.add_argument("--attempt-id", required=True)
    relay_parser.add_argument("--generation", type=int, required=True)
    relay_parser.add_argument("--server-name", default="chrono-vault")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "relay":
            token = os.environ.pop(TOKEN_ENV, "")
            return relay(
                port=args.port,
                token=token,
                binding=BrokerBinding(
                    task_id=args.task_id,
                    attempt_id=args.attempt_id,
                    generation=args.generation,
                    server_name=args.server_name,
                ),
            )
    except BrokerError as exc:
        print(_error_payload(exc), file=sys.stderr, flush=True)
        return 78
    return 64


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BrokerError",
    "BrokerDenied",
    "BrokerBinding",
    "BrokerStatus",
    "CONTEXT_ENV",
    "LOOPBACK_HOST",
    "ROOT_ALIASES",
    "ROOT_ENV",
    "TOKEN_ENV",
    "VaultBroker",
    "relay",
]
