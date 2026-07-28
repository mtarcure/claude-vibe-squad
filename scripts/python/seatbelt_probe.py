#!/usr/bin/env python3
"""Real, loopback-only probe harness for the V2 Seatbelt profile compiler."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import errno
import json
from pathlib import Path
import socket
import subprocess
import threading
from typing import Sequence

from seatbelt_profile import ProfileSpec, compile_profile


@dataclass(frozen=True)
class ProbeEffect:
    succeeded: bool
    returncode: int
    errno: int | None
    stdout: str
    stderr: str
    target_exists: bool | None = None


@dataclass(frozen=True)
class ProbeSuiteResult:
    fixture_root: str
    deny_profile_sha256: str
    broker_profile_sha256: str
    declared_write: ProbeEffect
    undeclared_write: ProbeEffect
    network_deny: ProbeEffect
    exact_broker_port: ProbeEffect
    wrong_broker_port: ProbeEffect

    @property
    def passed(self) -> bool:
        return bool(
            self.declared_write.succeeded
            and self.declared_write.target_exists
            and not self.undeclared_write.succeeded
            and self.undeclared_write.errno == errno.EPERM
            and self.undeclared_write.target_exists is False
            and not self.network_deny.succeeded
            and self.network_deny.errno == errno.EPERM
            and self.exact_broker_port.succeeded
            and not self.wrong_broker_port.succeeded
            and self.wrong_broker_port.errno == errno.EPERM
        )


class _LoopbackListener:
    def __init__(self, *, timeout: float = 3.0) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self._socket.settimeout(timeout)
        self.port = self._socket.getsockname()[1]
        self.accepted = False
        self._thread = threading.Thread(target=self._serve, daemon=False)

    def _serve(self) -> None:
        try:
            connection, _address = self._socket.accept()
        except TimeoutError:
            return
        else:
            self.accepted = True
            with connection:
                connection.recv(1)
        finally:
            self._socket.close()

    def start(self) -> None:
        self._thread.start()

    def finish(self) -> None:
        self._thread.join(timeout=4)
        if self._thread.is_alive():
            raise RuntimeError(
                f"loopback listener on port {self.port} did not terminate"
            )


def _run_sandbox(
    profile: str,
    command: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/sandbox-exec", "-p", profile, *command],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
        close_fds=True,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )


def _effect(
    completed: subprocess.CompletedProcess[str],
    *,
    target: Path | None = None,
) -> ProbeEffect:
    observed_errno: int | None = None
    for line in completed.stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("errno"), int):
            observed_errno = payload["errno"]
    combined = f"{completed.stdout}\n{completed.stderr}".lower()
    if (
        completed.returncode != 0
        and observed_errno is None
        and "operation not permitted" in combined
    ):
        observed_errno = errno.EPERM
    return ProbeEffect(
        succeeded=completed.returncode == 0,
        returncode=completed.returncode,
        errno=observed_errno,
        stdout=completed.stdout,
        stderr=completed.stderr,
        target_exists=target.exists() if target is not None else None,
    )


_NETWORK_PROBE_SOURCE = r"""
#include <arpa/inet.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    struct sockaddr_in address = {0};
    int descriptor;
    if (argc != 2) return 64;
    descriptor = socket(AF_INET, SOCK_STREAM, 0);
    if (descriptor < 0) return 65;
    address.sin_family = AF_INET;
    address.sin_port = htons((unsigned short)strtoul(argv[1], NULL, 10));
    if (inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) != 1) return 66;
    if (connect(descriptor, (struct sockaddr *)&address, sizeof(address)) != 0) {
        printf("{\"errno\":%d}\n", errno);
        close(descriptor);
        return 73;
    }
    (void)write(descriptor, "x", 1);
    close(descriptor);
    puts("{\"connected\":true}");
    return 0;
}
"""


def _build_network_probe(target: Path) -> None:
    completed = subprocess.run(
        ["/usr/bin/clang", "-x", "c", "-o", str(target), "-"],
        input=_NETWORK_PROBE_SOURCE,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        close_fds=True,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    if completed.returncode != 0 or not target.is_file():
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"could not build retained network probe: {detail}")


def _connect(profile: str, executable: Path, port: int) -> ProbeEffect:
    return _effect(
        _run_sandbox(
            profile,
            [str(executable), str(port)],
        )
    )


def run_probe_suite(fixture_root: Path) -> ProbeSuiteResult:
    """Run all Task-1.1 effects, retaining fixtures for audit/no-delete."""

    root = Path(fixture_root)
    allowed = root / "allowed"
    denied = root / "denied"
    allowed.mkdir(parents=True, exist_ok=False)
    denied.mkdir(parents=True, exist_ok=False)
    declared_target = allowed / "declared.txt"
    denied_target = denied / "undeclared.txt"
    network_probe = allowed / "network-probe"
    _build_network_probe(network_probe)

    network_deny_listener = _LoopbackListener()
    network_deny_listener.start()
    deny_profile = compile_profile(
        ProfileSpec(
            write_paths=(allowed,),
            executable_paths=(
                Path("/bin/sh"),
                Path("/bin/bash"),
                network_probe,
            ),
            allow_fork=True,
        )
    )

    declared_completed = _run_sandbox(
        deny_profile.text,
        ["/bin/sh", "-c", 'printf permitted > "$1"', "probe", str(declared_target)],
    )
    undeclared_completed = _run_sandbox(
        deny_profile.text,
        ["/bin/sh", "-c", 'printf denied > "$1"', "probe", str(denied_target)],
    )
    network_deny = _connect(
        deny_profile.text, network_probe, network_deny_listener.port
    )
    network_deny_listener.finish()

    broker_listener = _LoopbackListener()
    wrong_listener = _LoopbackListener()
    broker_listener.start()
    wrong_listener.start()
    broker_profile = compile_profile(
        ProfileSpec(
            write_paths=(allowed,),
            executable_paths=(network_probe,),
            broker_port=broker_listener.port,
        )
    )
    exact_broker = _connect(
        broker_profile.text, network_probe, broker_listener.port
    )
    wrong_broker = _connect(
        broker_profile.text, network_probe, wrong_listener.port
    )
    broker_listener.finish()
    wrong_listener.finish()

    return ProbeSuiteResult(
        fixture_root=str(root),
        deny_profile_sha256=deny_profile.sha256,
        broker_profile_sha256=broker_profile.sha256,
        declared_write=_effect(declared_completed, target=declared_target),
        undeclared_write=_effect(undeclared_completed, target=denied_target),
        network_deny=network_deny,
        exact_broker_port=exact_broker,
        wrong_broker_port=wrong_broker,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, required=True)
    arguments = parser.parse_args()
    result = run_probe_suite(arguments.fixture_root)
    payload = asdict(result)
    payload["passed"] = result.passed
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
