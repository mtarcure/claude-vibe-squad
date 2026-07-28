#!/usr/bin/env python3
"""Redacted, read-only static audit of chrono-vault provider wiring."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def server_from_json(path: Path) -> dict[str, Any] | None:
    data = load_json(path)
    servers = data.get("mcpServers", {})
    server = servers.get("chrono-vault") if isinstance(servers, dict) else None
    return server if isinstance(server, dict) else None


def server_from_codex(path: Path) -> dict[str, Any] | None:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcp_servers", {})
    server = servers.get("chrono-vault") if isinstance(servers, dict) else None
    return server if isinstance(server, dict) else None


def static_result(provider: str, config: Path, server: dict[str, Any] | None) -> dict[str, Any]:
    issues: list[str] = []
    if server is None:
        issues.append("chrono-vault-server-missing")
        return {
            "provider": provider,
            "config": str(config),
            "configured": False,
            "recall_declared": False,
            "record_declared": False,
            "root_source": "missing",
            "status": "fail",
            "issues": issues,
        }

    command = server.get("command")
    args = server.get("args", [])
    env = server.get("env", {})
    if not isinstance(command, str) or not Path(command).is_absolute():
        issues.append("command-not-absolute")
    elif not Path(command).is_file():
        issues.append("command-not-found")
    script_args = [Path(item) for item in args if isinstance(item, str) and item.endswith(".py")]
    if not script_args:
        issues.append("server-script-arg-missing")
    else:
        for script in script_args:
            if not script.is_absolute():
                issues.append("server-script-not-absolute")
            elif not script.is_file():
                issues.append("server-script-not-found")

    configured_root = env.get("CHRONO_VAULT_ROOT") if isinstance(env, dict) else None
    inherited_root = os.environ.get("CHRONO_VAULT_ROOT")
    root_source = "config" if configured_root else "inherited" if inherited_root else "missing"
    root = configured_root or inherited_root
    if not root:
        issues.append("chrono-vault-root-missing")
    elif "${" in root or not Path(root).is_absolute():
        issues.append("chrono-vault-root-unresolved")
    else:
        sentinel = Path(root) / ".chrono-vault"
        if not sentinel.is_file():
            issues.append("chrono-vault-sentinel-missing")

    server_script = script_args[0] if script_args and script_args[0].is_file() else None
    source = server_script.read_text(encoding="utf-8") if server_script else ""
    recall_declared = "def recall(" in source
    record_declared = "def record(" in source
    if not recall_declared:
        issues.append("recall-tool-not-declared")
    if not record_declared:
        issues.append("record-tool-not-declared")

    return {
        "provider": provider,
        "config": str(config),
        "configured": True,
        "recall_declared": recall_declared,
        "record_declared": record_declared,
        "root_source": root_source,
        "status": "pass" if not issues else "fail",
        "issues": sorted(set(issues)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit chrono-vault config without printing commands, roots, or credentials."
    )
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()
    repo = args.repo.resolve()
    home = args.home.resolve()

    specs: list[tuple[str, Path, dict[str, Any] | None]] = []
    claude = home / ".claude" / "settings.json"
    codex = home / ".codex" / "config.toml"
    gemini_project = repo / "model-lanes" / "gemini" / ".gemini" / "settings.json"
    gemini_home = home / ".gemini" / "settings.json"
    kimi = home / ".kimi" / "mcp.json"

    for provider, path, loader in (
        ("claude", claude, server_from_json),
        ("gpt-codex", codex, server_from_codex),
        ("kimi", kimi, server_from_json),
    ):
        try:
            server = loader(path)
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            server = None
        specs.append((provider, path, server))

    gemini_path = gemini_project if gemini_project.is_file() else gemini_home
    try:
        gemini_server = server_from_json(gemini_path)
    except (OSError, ValueError):
        gemini_server = None
    # Project settings may omit chrono-vault and inherit the home MCP registry.
    # Fall back only when the project file has no same-name server, never merge
    # or print provider credential material.
    if gemini_server is None and gemini_path != gemini_home:
        gemini_path = gemini_home
        try:
            gemini_server = server_from_json(gemini_path)
        except (OSError, ValueError):
            gemini_server = None
    specs.insert(2, ("gemini", gemini_path, gemini_server))

    failed = False
    for provider, config, server in specs:
        result = static_result(provider, config, server)
        # Intentionally emit no command, argument, env value, or credential content.
        print(json.dumps(result, sort_keys=True))
        failed |= result["status"] != "pass"
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
