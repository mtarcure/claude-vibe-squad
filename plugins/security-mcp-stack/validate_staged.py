#!/usr/bin/env python3
"""Fail-closed static validation for the restart-gated security MCP cutover."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CLAUDE_STAGED = REPO / "model-lanes/claude/.mcp.security-arsenal.staged.json"
CODEX_STAGED = REPO / "model-lanes/gpt-codex/.codex/security-arsenal.staged.toml"
CLAUDE_LIVE = REPO / "model-lanes/claude/.mcp.json"
CODEX_LIVE = REPO / "model-lanes/gpt-codex/.codex/config.toml"
HELD_SOLODIT = REPO / "plugins/security-mcp-stack/held-solodit.json"
HELD_MODEL_ARMOR = REPO / "plugins/security-mcp-stack/held-modelarmor.json"
SNYK_TARGETS = REPO / "plugins/security-mcp-stack/snyk-preactivation-targets.json"
SNYK_GATE = REPO / "plugins/security-mcp-stack/preactivate-security-stack.sh"
CONTEXT_DB = (
    REPO
    / "_state/tooling-arsenal-2026-07-18/mcp-context-protector/servers.json"
)
SOLODIT_ENTRYPOINT = (
    REPO
    / "_state/tooling-arsenal-2026-07-18/runtime/solodit-mcp-prod/dist/index.js"
)
WRAPPER = str(
    REPO
    / "_state/tooling-arsenal-2026-07-18/sources/mcp-context-protector/mcp-context-protector.sh"
)
EXPECTED = ["guarded-semgrep", "guarded-slither", "guarded-solodit"]
SECRET_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9]|AIza[0-9A-Za-z_-]|gh[opsu]_[A-Za-z0-9]|"
    r"ya29\.[A-Za-z0-9_-]|-----BEGIN PRIVATE KEY-----)"
)
MODEL_ARMOR_ASK = (
    "Provide either the absolute path to a durable least-privilege Model Armor "
    "service-account JSON key via GOOGLE_APPLICATION_CREDENTIALS, or run "
    "`gcloud auth application-default login` for the gateway identity."
)


def json_servers(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))["mcpServers"]


def toml_servers(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]


def normalize_empty_env(servers: dict[str, object]) -> dict[str, object]:
    """Treat empty environment entries as absent for semantic comparisons."""
    normalized = json.loads(json.dumps(servers))
    for raw in normalized.values():
        if not isinstance(raw, dict) or not isinstance(raw.get("env"), dict):
            continue
        raw["env"] = {key: value for key, value in raw["env"].items() if value not in ("", None)}
        if not raw["env"]:
            del raw["env"]
    return normalized


def guarded_subset(
    label: str, servers: dict[str, object], *, allow_unrelated: bool
) -> tuple[dict[str, object], list[str]]:
    """Return the ordered guarded trio without treating unrelated MCPs as drift."""
    issues: list[str] = []
    guarded_names = [name for name in servers if name in EXPECTED]
    if guarded_names != EXPECTED:
        issues.append(f"{label}:guard-order-or-server-set")
    if not allow_unrelated and list(servers) != EXPECTED:
        issues.append(f"{label}:unexpected-extra-server")
    return ({name: servers[name] for name in guarded_names}, issues)


def validate_servers(
    label: str, servers: dict[str, object], *, allow_unrelated: bool = False
) -> list[str]:
    issues: list[str] = []
    guarded, subset_issues = guarded_subset(
        label, servers, allow_unrelated=allow_unrelated
    )
    issues.extend(subset_issues)
    for name, raw in guarded.items():
        if not isinstance(raw, dict):
            issues.append(f"{label}:{name}:not-a-table")
            continue
        command = raw.get("command")
        args = raw.get("args")
        if command != WRAPPER:
            issues.append(f"{label}:{name}:not-context-protected")
        if not Path(str(command)).is_file():
            issues.append(f"{label}:{name}:wrapper-missing")
        if not isinstance(args, list) or "--command-args" not in args:
            issues.append(f"{label}:{name}:child-command-missing")
            continue
        if "--server-config-file" not in args:
            issues.append(f"{label}:{name}:context-db-argument-missing")
        else:
            db_index = args.index("--server-config-file") + 1
            if db_index >= len(args) or args[db_index] != str(CONTEXT_DB):
                issues.append(f"{label}:{name}:wrong-context-db")
        if "--visualize-ansi-codes" not in args:
            issues.append(f"{label}:{name}:ansi-visualization-missing")
        if "--quarantine-path" in args:
            issues.append(f"{label}:{name}:inactive-quarantine-argument")
        if "--guardrail-provider" in args:
            issues.append(f"{label}:{name}:inline-llamafirewall-not-approved")
        child_index = args.index("--command-args") + 1
        if child_index >= len(args):
            issues.append(f"{label}:{name}:child-command-value-missing")
            continue
        child = Path(str(args[child_index]))
        if not child.is_absolute() or not child.is_file():
            issues.append(f"{label}:{name}:child-not-absolute-or-missing")
        if name == "guarded-semgrep" and args[child_index:] != [
            "/opt/homebrew/bin/semgrep", "mcp"
        ]:
            issues.append(f"{label}:{name}:unexpected-child-command")
        if name == "guarded-slither" and (
            len(args[child_index:]) != 2 or args[-1] != "--disable-metrics"
        ):
            issues.append(f"{label}:{name}:metrics-not-disabled")
        if name == "guarded-solodit":
            if args[child_index:] != ["/opt/homebrew/bin/node", str(SOLODIT_ENTRYPOINT)]:
                issues.append(f"{label}:{name}:unexpected-production-entrypoint")
            if "env" in raw or "SOLODIT_API_KEY" in json.dumps(raw):
                issues.append(f"{label}:{name}:credential-must-be-inherited")
        if SECRET_PATTERN.search(json.dumps(raw)):
            issues.append(f"{label}:{name}:literal-secret")
    return issues


def main() -> int:
    claude_staged = json_servers(CLAUDE_STAGED)
    codex_staged = toml_servers(CODEX_STAGED)
    claude_live = json_servers(CLAUDE_LIVE)
    codex_live = toml_servers(CODEX_LIVE)
    snyk_targets = json_servers(SNYK_TARGETS)
    held = json.loads(HELD_SOLODIT.read_text(encoding="utf-8"))
    model_armor = json.loads(HELD_MODEL_ARMOR.read_text(encoding="utf-8"))
    context_db = json.loads(CONTEXT_DB.read_text(encoding="utf-8"))
    issues: list[str] = []
    for label, servers, allow_unrelated in (
        ("claude-staged", claude_staged, False),
        ("gpt-codex-staged", codex_staged, False),
        ("claude-live", claude_live, True),
        ("gpt-codex-live", codex_live, True),
        ("snyk-targets", snyk_targets, False),
    ):
        issues.extend(
            validate_servers(label, servers, allow_unrelated=allow_unrelated)
        )
    claude_live_guarded, _ = guarded_subset(
        "claude-live", claude_live, allow_unrelated=True
    )
    codex_live_guarded, _ = guarded_subset(
        "gpt-codex-live", codex_live, allow_unrelated=True
    )
    normalized_claude_live = normalize_empty_env(claude_live_guarded)
    if (
        normalized_claude_live != normalize_empty_env(claude_staged)
        or normalized_claude_live != normalize_empty_env(codex_live_guarded)
    ):
        issues.append("lane-configs:not-semantically-equal")
    if (
        normalized_claude_live != normalize_empty_env(codex_staged)
        or normalized_claude_live != normalize_empty_env(snyk_targets)
    ):
        issues.append("review-or-snyk-mirror:not-semantically-equal")
    empty_env_warnings = []
    for label, servers in (
        ("claude-staged", claude_staged),
        ("gpt-codex-staged", codex_staged),
        ("claude-live", claude_live),
        ("gpt-codex-live", codex_live),
    ):
        semgrep = servers.get("guarded-semgrep")
        if isinstance(semgrep, dict) and semgrep.get("env", {}).get("SEMGREP_APP_TOKEN") == "":
            empty_env_warnings.append(
                f"{label}:guarded-semgrep:empty-SEMGREP_APP_TOKEN-overrides-inherited-auth"
            )
    context_servers = context_db.get("servers") if isinstance(context_db, dict) else None
    context_state = "invalid"
    if context_servers == []:
        context_state = "empty-unapproved-fail-closed"
    elif isinstance(context_servers, list):
        expected_identifiers = {
            "/opt/homebrew/bin/semgrep mcp",
            str(REPO / "_state/tooling-arsenal-2026-07-18/tools/slither-mcp/bin/slither-mcp")
            + " --disable-metrics",
            "/opt/homebrew/bin/node " + str(SOLODIT_ENTRYPOINT),
        }
        actual_identifiers = {
            str(server.get("identifier"))
            for server in context_servers
            if isinstance(server, dict)
        }
        approved = all(
            isinstance(server, dict)
            and server.get("type") == "stdio"
            and server.get("approval_status") == "approved"
            and isinstance(server.get("config"), dict)
            for server in context_servers
        )
        if len(context_servers) == 3 and actual_identifiers == expected_identifiers and approved:
            context_state = "three-reviewed-schemas-approved"
        else:
            issues.append("context-db:unexpected-or-unapproved-server-set")
    else:
        issues.append("context-db:malformed-servers-list")
    if held.get("activation") != "activated-ready":
        issues.append("solodit:not-activated-ready")
    if held.get("built_entrypoint") != str(SOLODIT_ENTRYPOINT):
        issues.append("solodit:wrong-production-entrypoint")
    if held.get("credential_env") != "SOLODIT_API_KEY":
        issues.append("solodit:wrong-inherited-credential")
    if SECRET_PATTERN.search(json.dumps(held)):
        issues.append("solodit:literal-secret")
    if model_armor.get("activation") != "blocked-on-operator-credential":
        issues.append("model-armor:not-credential-blocked")
    if model_armor.get("operator_ask") != MODEL_ARMOR_ASK:
        issues.append("model-armor:operator-ask-drift")
    if SECRET_PATTERN.search(json.dumps(model_armor)):
        issues.append("model-armor:literal-secret")
    gate_text = SNYK_GATE.read_text(encoding="utf-8")
    for token in (
        "SNYK_TOKEN", "SOLODIT_API_KEY", "--ci", "--no-skills",
        "--dangerously-run-mcp-servers", "plugins/security-mcp-stack/snyk-preactivation-targets.json",
    ):
        if token not in gate_text:
            issues.append(f"snyk-gate:missing:{token}")
    if not SNYK_GATE.stat().st_mode & 0o111:
        issues.append("snyk-gate:not-executable")
    if "snyk" in " ".join(claude_live).lower():
        issues.append("lane-configs:snyk-must-not-be-inline")
    result = {
        "status": "pass" if not issues else "fail",
        "guard": "mcp-context-protector",
        "staged_servers": EXPECTED,
        "live_configs": [str(CLAUDE_LIVE.relative_to(REPO)), str(CODEX_LIVE.relative_to(REPO))],
        "context_config_state": context_state,
        "solodit": "activated-ready",
        "snyk": "required-fail-closed-preactivation",
        "model_armor": "blocked-on-operator-credential",
        "warnings": empty_env_warnings,
        "issues": issues,
    }
    print(json.dumps(result, sort_keys=True))
    return int(bool(issues))


if __name__ == "__main__":
    sys.exit(main())
