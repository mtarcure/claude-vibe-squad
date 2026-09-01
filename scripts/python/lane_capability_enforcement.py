#!/usr/bin/env python3
"""Deterministic role capability projection and native lane enforcement.

This module contains no model calls and grants no capabilities. It filters a
lane's already-configured MCP servers where the native CLI can enforce that
boundary. The agy-backed ``gemini`` and native ``grok`` lanes are explicit
exceptions: their discovered MCPs are global configuration, so each plan
records the whole enabled inventory and emits no fictitious restriction flag.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Callable, Mapping


SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
CLAUDE_LIVE_SERVER_RE = re.compile(
    r"^(?:plugin:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+|[A-Za-z0-9_-]+)$"
)
CLAUDE_FIRST_PARTY_SERVERS = {
    "claude.ai Gmail": ("claude-ai-gmail", "claude_ai_Gmail"),
    "claude.ai Google Calendar": (
        "claude-ai-google-calendar",
        "claude_ai_Google_Calendar",
    ),
    "claude.ai Google Drive": (
        "claude-ai-google-drive",
        "claude_ai_Google_Drive",
    ),
}
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
ROLE_CONFIG_MARKER = "__ROLE_MCP_CONFIG__"
CHRONO_VAULT_SERVER = "chrono-vault"
AGY_GLOBAL_CHRONO_MCPS = frozenset(
    {
        "chrono-media-studio",
        "chrono-obsidian",
        "chrono-research-arsenal",
        "chrono-vault",
    }
)
BROKER_TOKEN_ENV = "CHRONO_VAULT_BROKER_TOKEN"
BROKER_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
RESEARCH_ARSENAL_SERVER = "chrono-research-arsenal"
# The one home for the research-arsenal credential NAMES. `board-supervisor.sh`
# imports this tuple instead of restating it: the same three names choose which
# secrets are loaded, which are reported missing, which Codex forwards through
# `env_vars`, and which are bound into Kimi's per-server `env`. Two lists would
# drift, and the drift would look like a silent auth failure at call time.
RESEARCH_API_KEY_NAMES = (
    "XAI_API_KEY",
    "PERPLEXITY_API_KEY",
    "FIRECRAWL_API_KEY",
)
LANES = frozenset({"codex", "claude", "gemini", "grok", "kimi"})
KIMI_LOCAL_SERVER_SCRIPTS = {
    name: Path("plugins") / name / "mcp_server.py"
    for name in ("chrono-vault", "chrono-dedup", "chrono-research-arsenal")
}
KIMI_SEQUENTIAL_COMMAND = Path(
    "/opt/homebrew/bin/mcp-server-sequential-thinking"
)
CAPABILITY_SOURCE_RELATIVE = Path(
    "model-lanes/specialist-lane-capabilities.v1.json"
)

# ── F6: only a PATH-resolvable tool may gate a headless spawn ────────────────
# `host-PATH` is the one evidence kind in `specialist_capability_source.py` that
# ASSERTS "a binary spelled like this capability's id answers on the shell
# PATH". Every other kind describes a capability reached some other way -- a
# macOS `.app` bundle (`host-app-bundle`, launched via `open -a`), the repo venv
# interpreter (`repo-venv-interpreter`), an MCP operation, a harness capability
# behind a runtime-map approval, or something only an operator can install
# (`operator-install-required`).
#
# The launch gate used to run `shutil.which()` over EVERY declared tool and hard
# -deny on any miss, which made `which()` the arbiter of capabilities it can
# never see. That silently made whole specialists undispatchable:
# `knowledge-librarian` declares `zotero` (a GUI `.app`), so every headless
# spawn died with exit 74 "role requires unavailable local tools: zotero" --
# friction F6, and the same trap waits for hammerspoon/mitmproxy/Xcode roles.
#
# A `which()` miss is only EVIDENCE OF ABSENCE for a tool that claimed to be on
# PATH. For anything else the miss proves nothing, so it is recorded as a
# `capability_gap` (the adapters already instruct workers to declare a gap and
# use the task-approved fallback) instead of denying the launch. This stays
# fail-CLOSED: an unclassified tool, or a `host-PATH`-declared required tool
# that is genuinely absent, still denies.
PATH_RESOLVABLE_EVIDENCE = frozenset({"host-PATH"})

# ── Structural validity is NOT runtime health ────────────────────────────────
# These were one class until 2026-08-10, and folding them together made a
# transient outage anywhere in a role's authorized set a permanent denial of
# that role. Measured 2026-08-09: the `research` role could not be dispatched
# because the `github` MCP answered `HTTP 400: Authorization header is badly
# formatted`, on a markdown/caching packet that never touched github.
#
#   STRUCTURAL  -- a REQUIRED authorized server that is not configured at all,
#                  or any configured authorized server whose record is unsafe.
#                  This is a defect in the PLAN and no amount of waiting fixes
#                  it. Still fails closed.
#   DEGRADATION -- an explicitly non-required server that is not configured.
#                  The role can launch without it, and the absence is surfaced
#                  through the same receipt fields as runtime ill health.
#   RUNTIME     -- a properly-configured, authorized server that did not answer
#                  the health probe (connection failure, auth failure, provider
#                  outage). This is a fact about the WORLD at one instant. It
#                  degrades: the launch proceeds, and the unhealthy server is
#                  named in the receipt and in the worker's injected context so
#                  the worker does not discover it by calling a dead tool.
#
# `available` now means exactly one thing on every lane -- see `mcp_health()`.
# The lanes differ only in whether they COLLECT health at all, and that is
# stated here rather than left implicit in where the probe happens to be
# called: Claude's live inventory reports connection health. Agy's table
# reports only persistent enabled/disabled configuration state, not a probe;
# Codex and Kimi likewise enumerate configuration only. Their records carry no
# health status, which means `unknown`, not healthy or unhealthy.
MCP_HEALTH_INSPECTED_LANES = frozenset({"claude"})
MCP_HEALTHY_STATUS_RE = re.compile(r"^[✔✓]?\s*Connected\b")
MCP_STATUS_MAX_LENGTH = 512


class CapabilityDenied(RuntimeError):
    """Role capability projection cannot be enforced without widening it."""


def _reject_non_finite_json(_value: str) -> None:
    raise ValueError("non-finite JSON value")


@dataclass(frozen=True)
class LaneCapabilityPlan:
    lane: str
    authorized_mcps: tuple[str, ...]
    configured_mcps: tuple[str, ...]
    disabled_mcps: tuple[str, ...]
    brokered_mcps: tuple[str, ...]
    authorized_tools: tuple[str, ...]
    available_tools: tuple[str, ...]
    missing_tools: tuple[str, ...]
    capability_enforcement: str
    cli_args: tuple[str, ...]
    role_config_json: str | None
    # Declared tools that are unresolvable on this headless spawn but must not
    # gate it (F6). The worker is expected to declare a `capability_gap` and use
    # the task-approved fallback rather than pretend the tool worked.
    capability_gaps: tuple[str, ...] = ()
    # Authorized servers that are either explicitly non-required and absent or
    # configured but did not answer the health probe. Degraded, not denied: the
    # launch proceeds and these are surfaced.
    unhealthy_mcps: tuple[str, ...] = ()
    # (server name, degradation status) for every entry in `unhealthy_mcps`.
    # Probe statuses stay verbatim; an absent non-required server uses `absent`.
    unhealthy_mcp_status: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class KimiLocalHostArtifacts:
    """Executable host paths used by Kimi's controller-owned templates."""

    interpreter: Path
    sequential_thinking: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CapabilityDenied(f"role capability source is unavailable: {exc}") from exc
    return digest.hexdigest()


def _declared_arrays(path: Path) -> dict[str, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CapabilityDenied(f"role capability source is unavailable: {exc}") from exc
    result = {"mcps": [], "tools": [], "skills": []}
    aliases = {
        "mcps": ("mcps", "capability_mcps"),
        "tools": ("tools", "capability_tools"),
        "skills": ("skills", "capability_skills"),
    }
    for canonical, keys in aliases.items():
        for key in keys:
            matches = re.findall(
                rf"(?m)^[ \t]*{re.escape(key)}[ \t]*[:=][ \t]*(\[[^\r\n]*\])[ \t]*$",
                text,
            )
            for match in matches:
                try:
                    values = json.loads(match)
                except json.JSONDecodeError as exc:
                    raise CapabilityDenied(
                        f"role capability source has an invalid {key} declaration"
                    ) from exc
                if not isinstance(values, list) or any(
                    not isinstance(value, str) for value in values
                ):
                    raise CapabilityDenied(
                        f"role capability source has an invalid {key} declaration"
                    )
                result[canonical].extend(values)
    return result


def adapter_path_for(*, repo_root: Path, lane: str, specialist: str) -> Path:
    """Resolve one native lane adapter without falling back across lanes."""

    if lane not in LANES:
        raise CapabilityDenied(f"unsupported capability lane: {lane!r}")
    if not SERVER_NAME_RE.fullmatch(specialist):
        raise CapabilityDenied("specialist name is unsafe")
    candidates: tuple[Path, ...]
    if lane == "codex":
        root = repo_root / "model-lanes" / "gpt-codex" / ".codex" / "agents"
        candidates = (
            root / f"{specialist.replace('-', '_')}.toml",
            root / f"{specialist}.toml",
        )
    elif lane == "claude":
        candidates = (
            repo_root / "model-lanes" / "claude" / ".claude" / "agents"
            / f"{specialist}.md",
        )
    elif lane == "gemini":
        candidates = (
            repo_root / "model-lanes" / "gemini" / ".gemini" / "agents"
            / f"{specialist}.md",
        )
    elif lane == "grok":
        candidates = (
            repo_root / "model-lanes" / "grok" / ".grok" / "agents"
            / f"{specialist}.yaml",
        )
    else:
        root = repo_root / "model-lanes" / "kimi"
        candidates = (
            root / ".kimi" / "agents" / f"{specialist}.yaml",
            root / "subagents" / f"{specialist}.yaml",
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CapabilityDenied(
        f"native {lane} specialist adapter is missing for {specialist!r}"
    )


def load_projection(
    *,
    lane: str,
    specialist: str,
    adapter_path: Path,
    overlay_path: Path,
) -> dict[str, object]:
    """Load, deduplicate, validate, and hash adapter capability declarations."""

    if lane not in LANES:
        raise CapabilityDenied(f"unsupported capability lane: {lane!r}")
    sources: list[Path] = []
    for raw_path in (Path(adapter_path), Path(overlay_path)):
        resolved = raw_path.resolve(strict=False)
        if resolved not in sources:
            sources.append(resolved)
    projection: dict[str, object] = {
        "schema": "role-capability-projection/v1",
        "lane": lane,
        "specialist": specialist,
        "mcps": [],
        "brokered_mcps": [],
        "tools": [],
        "skills": [],
        "sources": [],
    }
    for source in sources:
        declarations = _declared_arrays(source)
        projection["sources"].append(
            {"path": str(source), "sha256": _sha256_file(source)}
        )
        projection["tools"].extend(declarations["tools"])
        projection["skills"].extend(declarations["skills"])
        for server_name in declarations["mcps"]:
            if server_name.startswith("lead:"):
                projection["brokered_mcps"].append(server_name[5:])
            else:
                projection["mcps"].append(server_name)
    for key in ("mcps", "brokered_mcps"):
        values = sorted(set(projection[key]))
        if any(not SERVER_NAME_RE.fullmatch(value) for value in values):
            raise CapabilityDenied(f"role declares an unsafe {key} name")
        projection[key] = values
    tools = sorted(set(projection["tools"]))
    if any(not TOOL_NAME_RE.fullmatch(value) for value in tools):
        raise CapabilityDenied("role declares an unsafe local tool name")
    projection["tools"] = tools
    skills = sorted(set(projection["skills"]))
    if any(not SERVER_NAME_RE.fullmatch(value) for value in skills):
        raise CapabilityDenied("role declares an unsafe skill name")
    projection["skills"] = skills
    return projection


def load_json_mcp_servers(path: Path) -> dict[str, dict[str, object]]:
    """Load the conventional ``{"mcpServers": {...}}`` lane config shape."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityDenied(f"lane MCP config is unreadable or invalid: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("mcpServers"), dict)
        or any(
            not isinstance(name, str) or not isinstance(config, dict)
            for name, config in payload["mcpServers"].items()
        )
    ):
        raise CapabilityDenied("lane MCP config has the wrong schema")
    result = dict(payload["mcpServers"])
    if any(not SERVER_NAME_RE.fullmatch(name) for name in result):
        raise CapabilityDenied("configured MCP server has an unsafe name")
    return result


# SGR ("select graphic rendition") colour sequences only -- not the whole ANSI
# escape space. A cursor-movement or clear-screen sequence in an inventory row
# would be genuinely anomalous and should still fail closed.
_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def parse_live_mcp_listing(
    *, lane: str, output: str
) -> dict[str, dict[str, object]]:
    """Parse one native CLI's live MCP inventory into adapter-facing names."""

    if lane not in {"claude", "gemini", "grok"}:
        raise CapabilityDenied(f"{lane} does not have a text MCP inventory parser")
    if not isinstance(output, str) or "\x00" in output:
        raise CapabilityDenied("live MCP inventory output is invalid")

    # Strip SGR colour codes before matching Claude rows. This is deliberately
    # narrow: a genuinely malformed row still fails closed.
    output = _SGR_RE.sub("", output)

    lines = output.splitlines()
    try:
        header_index = next(
            index
            for index, line in enumerate(lines)
            if (
                line.strip() == "Checking MCP server health…"
                if lane == "claude"
                else (
                    line.split() == ["NAME", "TYPE", "STATUS", "COMMAND/URL"]
                    if lane == "gemini"
                    else re.fullmatch(r"\s*MCP Servers\s+\([0-9]+\)\s*", line)
                    is not None
                )
            )
        )
    except StopIteration as exc:
        raise CapabilityDenied(
            f"{lane} live MCP inventory header is missing"
        ) from exc

    result: dict[str, dict[str, object]] = {}
    for raw_line in lines[header_index + 1 :]:
        line = raw_line.strip()
        if not line:
            continue
        if lane == "claude":
            live_name, name_separator, remainder = line.partition(": ")
            _command, status_separator, status = remainder.rpartition(" - ")
            if not name_separator or not status_separator or not status.strip():
                raise CapabilityDenied(
                    "Claude live MCP inventory contains an unparseable row"
                )
            status = status.strip()
            first_party = CLAUDE_FIRST_PARTY_SERVERS.get(live_name)
            if first_party is not None:
                canonical_name, tool_namespace = first_party
            elif CLAUDE_LIVE_SERVER_RE.fullmatch(live_name):
                canonical_name = live_name.rsplit(":", 1)[-1]
                tool_namespace = live_name.replace(":", "_")
            else:
                raise CapabilityDenied(
                    "Claude live MCP inventory contains an unsafe server name"
                )
        elif lane == "gemini":
            columns = line.split(None, 3)
            if (
                len(columns) != 4
                or SERVER_NAME_RE.fullmatch(columns[0]) is None
                or columns[1] not in {"stdio", "http"}
                or columns[2] not in {"enabled", "disabled"}
                or not columns[3].strip()
            ):
                raise CapabilityDenied(
                    "agy live MCP inventory contains an unparseable row"
                )
            canonical_name = columns[0]
            # A disabled persistent entry is not available to the worker and is
            # therefore absent from the configured/enabled surface.
            if columns[2] == "disabled":
                continue
            live_name = canonical_name
            status = None
        else:
            match = re.fullmatch(
                r"\s*[├└](?:─+)?\s+([A-Za-z0-9_-]+)\s+\((stdio|http)\)(?:\s+.*)?",
                raw_line,
            )
            if match is None:
                if result and raw_line and not raw_line[0].isspace():
                    break
                continue
            canonical_name = match.group(1)
            live_name = canonical_name
            status = None

        if not SERVER_NAME_RE.fullmatch(canonical_name):
            raise CapabilityDenied(
                f"{lane} live MCP inventory contains an unsafe adapter name"
            )
        previous = result.get(canonical_name)
        if previous is not None and previous.get("live_name") != live_name:
            raise CapabilityDenied(
                f"{lane} live MCP inventory has an ambiguous server name: "
                f"{canonical_name}"
            )
        if lane == "claude":
            for record in result.values():
                if (
                    record.get("tool_namespace") == tool_namespace
                    and record.get("live_name") != live_name
                ):
                    raise CapabilityDenied(
                        "Claude live MCP inventory has an ambiguous tool namespace: "
                        f"{tool_namespace}"
                    )
        result[canonical_name] = {
            "live_name": live_name,
            **(
                {"status": status, "tool_namespace": tool_namespace}
                if lane == "claude"
                else {}
            ),
        }
    if not result:
        raise CapabilityDenied(f"{lane} live MCP inventory is empty or unparseable")
    if lane == "grok":
        declared_count = int(
            re.search(r"\(([0-9]+)\)", lines[header_index]).group(1)  # type: ignore[union-attr]
        )
        if len(result) != declared_count:
            raise CapabilityDenied(
                "grok live MCP inventory count does not match its inspect header"
            )
    return result


def parse_claude_enabled_plugins(output: str) -> tuple[str, ...]:
    """Return safe enabled plugin names from ``claude plugin list --json``."""

    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CapabilityDenied("Claude plugin inventory returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise CapabilityDenied("Claude plugin inventory has the wrong schema")
    names: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise CapabilityDenied("Claude plugin inventory has the wrong schema")
        if item.get("enabled") is not True:
            continue
        plugin_id = item.get("id")
        if not isinstance(plugin_id, str) or "@" not in plugin_id:
            raise CapabilityDenied("Claude plugin inventory has an invalid id")
        name = plugin_id.split("@", 1)[0]
        if not SERVER_NAME_RE.fullmatch(name):
            raise CapabilityDenied("Claude plugin inventory has an unsafe name")
        names.add(name)
    return tuple(sorted(names))


def parse_claude_project_plugin_dirs(output: str) -> dict[str, str]:
    """Return safe enabled project-plugin install paths by plugin name."""

    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CapabilityDenied("Claude plugin inventory returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise CapabilityDenied("Claude plugin inventory has the wrong schema")
    result: dict[str, str] = {}
    for item in payload:
        if (
            not isinstance(item, dict)
            or item.get("enabled") is not True
            or item.get("scope") != "project"
        ):
            continue
        plugin_id = item.get("id")
        install_path = item.get("installPath")
        if (
            not isinstance(plugin_id, str)
            or "@" not in plugin_id
            or not isinstance(install_path, str)
            or not install_path.startswith("/")
            or "\x00" in install_path
        ):
            raise CapabilityDenied(
                "Claude project plugin inventory has an invalid record"
            )
        name = plugin_id.split("@", 1)[0]
        if not SERVER_NAME_RE.fullmatch(name):
            raise CapabilityDenied("Claude project plugin has an unsafe name")
        previous = result.get(name)
        if previous is not None and previous != install_path:
            raise CapabilityDenied(
                f"Claude project plugin inventory is ambiguous: {name}"
            )
        result[name] = install_path
    return result


def _claude_tool_pattern(server: Mapping[str, object]) -> str:
    """Map one validated live Claude server name to its native MCP wildcard."""

    live_name = server.get("live_name")
    tool_namespace = server.get("tool_namespace")
    if not isinstance(live_name, str):
        raise CapabilityDenied("Claude live MCP server name is unsafe")
    first_party = CLAUDE_FIRST_PARTY_SERVERS.get(live_name)
    expected_namespace = (
        first_party[1]
        if first_party is not None
        else live_name.replace(":", "_")
        if CLAUDE_LIVE_SERVER_RE.fullmatch(live_name)
        else None
    )
    if (
        expected_namespace is None
        or not isinstance(tool_namespace, str)
        or tool_namespace != expected_namespace
        or not SERVER_NAME_RE.fullmatch(tool_namespace)
    ):
        raise CapabilityDenied("Claude live MCP tool namespace is unsafe")
    return f"mcp__{tool_namespace}__*"


def _canonical_role_config(
    *,
    authorized: tuple[str, ...],
    configured_servers: Mapping[str, Mapping[str, object]],
) -> str:
    selected = {name: configured_servers[name] for name in authorized}
    try:
        return json.dumps(
            {"mcpServers": selected},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CapabilityDenied(
            f"selected MCP config is not canonical JSON: {exc}"
        ) from exc


def chrono_vault_relay_server(
    *,
    repo_root: Path,
    broker_port: int,
    broker_token: str,
    task_id: str,
    attempt_id: str,
    generation: int,
    python_executable: Path = Path("/usr/bin/python3"),
) -> dict[str, object]:
    """Return the one path-free MCP server record installed in a worker.

    The only filesystem path in this record points back into the worker's own
    worktree.  The private vault address and authenticated aperture context
    stay exclusively in the supervisor-owned backend environment.
    """

    if (
        isinstance(broker_port, bool)
        or not isinstance(broker_port, int)
        or not 1 <= broker_port <= 65535
    ):
        raise CapabilityDenied("chrono-vault broker port is invalid")
    if not isinstance(broker_token, str) or BROKER_TOKEN_RE.fullmatch(broker_token) is None:
        raise CapabilityDenied("chrono-vault broker token is invalid")
    if (
        not isinstance(task_id, str)
        or not isinstance(attempt_id, str)
        or SERVER_NAME_RE.fullmatch(task_id) is None
        or SERVER_NAME_RE.fullmatch(attempt_id) is None
        or len(task_id) > 192
        or len(attempt_id) > 192
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise CapabilityDenied("chrono-vault broker binding is invalid")
    try:
        root = Path(repo_root).resolve(strict=True)
        executable = Path(python_executable).resolve(strict=True)
        relay = (root / "plugins" / "chrono-vault" / "broker.py").resolve(strict=True)
    except (OSError, RuntimeError):
        raise CapabilityDenied("chrono-vault relay runtime is unavailable") from None
    if (
        not root.is_dir()
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
        or not relay.is_file()
        or not relay.is_relative_to(root)
    ):
        raise CapabilityDenied("chrono-vault relay runtime is unavailable")
    return {
        "command": str(executable),
        "args": [
            str(relay),
            "relay",
            "--port",
            str(broker_port),
            "--task-id",
            task_id,
            "--attempt-id",
            attempt_id,
            "--generation",
            str(generation),
            "--server-name",
            CHRONO_VAULT_SERVER,
        ],
        "env": {BROKER_TOKEN_ENV: broker_token},
    }


def broker_chrono_vault_plan(
    plan: LaneCapabilityPlan,
    *,
    repo_root: Path,
    broker_port: int,
    broker_token: str,
    task_id: str,
    attempt_id: str,
    generation: int,
    python_executable: Path = Path("/usr/bin/python3"),
) -> LaneCapabilityPlan:
    """Replace direct chrono-vault launch data with one relay-only record."""

    if CHRONO_VAULT_SERVER not in plan.authorized_mcps:
        return plan
    relay = chrono_vault_relay_server(
        repo_root=repo_root,
        broker_port=broker_port,
        broker_token=broker_token,
        task_id=task_id,
        attempt_id=attempt_id,
        generation=generation,
        python_executable=python_executable,
    )
    if plan.lane == "codex":
        return replace(
            plan,
            cli_args=(
                *plan.cli_args,
                *codex_chrono_vault_relay_args(
                    relay=relay,
                    broker_token=broker_token,
                ),
            ),
        )

    # Gemini has no reviewed per-spawn MCP-config argument in the current
    # launcher.  Returning role_config_json here used to look complete, but the
    # materializer then rejected it because no ROLE_CONFIG_MARKER was present.
    # Keep this typed and closed until the supervisor has a proven config-home
    # injection mechanism.
    if plan.lane in {"gemini", "grok"}:
        raise CapabilityDenied(
            f"{plan.lane} chrono-vault relay config injection is not implemented"
        )

    selected: dict[str, object] = {}
    if plan.role_config_json is not None:
        try:
            payload = json.loads(plan.role_config_json)
            configured = payload.get("mcpServers") if isinstance(payload, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            configured = None
        if not isinstance(configured, dict):
            raise CapabilityDenied("role MCP config cannot be broker-rewritten")
        selected.update(configured)
    selected[CHRONO_VAULT_SERVER] = relay
    role_config_json = _canonical_role_config(
        authorized=tuple(sorted(selected)),
        configured_servers=selected,
    )
    cli_args = plan.cli_args
    if plan.lane == "claude" and ROLE_CONFIG_MARKER not in cli_args:
        cli_args = ("--mcp-config", ROLE_CONFIG_MARKER, *cli_args)
    return replace(plan, role_config_json=role_config_json, cli_args=cli_args)


def codex_chrono_vault_relay_args(
    *,
    relay: Mapping[str, object],
    broker_token: str,
) -> tuple[str, str]:
    """Build the final Codex table replacement for one validated relay."""

    if (
        not isinstance(relay, Mapping)
        or not isinstance(relay.get("command"), str)
        or not isinstance(relay.get("args"), list)
        or any(not isinstance(value, str) for value in relay["args"])
        or not isinstance(broker_token, str)
        or BROKER_TOKEN_RE.fullmatch(broker_token) is None
        or relay.get("env") != {BROKER_TOKEN_ENV: broker_token}
    ):
        raise CapabilityDenied("Codex chrono-vault relay record is invalid")
    # JSON strings are valid TOML basic strings for these prevalidated ASCII
    # values.  A full table replacement appears after the earlier enabled=true
    # switch and therefore wins without exposing host provider configuration.
    command = json.dumps(relay["command"], ensure_ascii=True)
    arguments = ",".join(
        json.dumps(value, ensure_ascii=True) for value in relay["args"]
    )
    token = json.dumps(broker_token, ensure_ascii=True)
    override = (
        "mcp_servers.chrono-vault="
        "{enabled=true,command="
        + command
        + ",args=["
        + arguments
        + f"],env={{CHRONO_VAULT_BROKER_TOKEN={token}}}}}"
    )
    return ("-c", override)


def _kimi_local_server_templates(
    *,
    repo_root: Path | None,
    authorized: tuple[str, ...],
    vault_environment: Mapping[str, str] | None = None,
    research_environment: Mapping[str, str] | None = None,
    host_artifacts: KimiLocalHostArtifacts | None = None,
) -> dict[str, dict[str, object]]:
    """Build selected Kimi MCP config from controller-owned local paths only."""

    supported = set(KIMI_LOCAL_SERVER_SCRIPTS) | {"sequential-thinking"}
    if set(authorized) - supported:
        raise CapabilityDenied("Kimi lead MCP uses an unsupported local template")
    if repo_root is None:
        raise CapabilityDenied("Kimi local template repo root is unavailable")
    try:
        root = Path(repo_root).resolve(strict=True)
    except (OSError, RuntimeError):
        raise CapabilityDenied("Kimi local template repo root is unavailable") from None
    if not root.is_dir():
        raise CapabilityDenied("Kimi local template repo root is unavailable")

    bound_vault_environment: dict[str, str] | None = None
    if "chrono-vault" in authorized:
        required = {"CHRONO_VAULT_ROOT", "CHRONO_VAULT_CONTEXT"}
        if not isinstance(vault_environment, Mapping) or set(vault_environment) != required:
            raise CapabilityDenied("Kimi chrono-vault environment is not exactly bound")
        vault_root = vault_environment["CHRONO_VAULT_ROOT"]
        vault_context = vault_environment["CHRONO_VAULT_CONTEXT"]
        try:
            decoded_context = json.loads(
                vault_context,
                parse_constant=_reject_non_finite_json,
            )
        except (TypeError, ValueError):
            raise CapabilityDenied("Kimi chrono-vault context is invalid") from None
        if (
            not isinstance(vault_root, str)
            or not Path(vault_root).is_absolute()
            or not vault_root
            or "\x00" in vault_root
            or len(vault_root.encode("utf-8")) > 4096
            or not isinstance(vault_context, str)
            or "\x00" in vault_context
            or len(vault_context.encode("utf-8")) > 16384
            or not isinstance(decoded_context, dict)
            or decoded_context.get("schema") != "chrono-vault-context/v1"
            or json.dumps(
                decoded_context,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            != vault_context
        ):
            raise CapabilityDenied("Kimi chrono-vault environment is invalid")
        bound_vault_environment = {
            name: vault_environment[name] for name in sorted(required)
        }

    # Kimi's installed MCP client hands a stdio child only HOME/LOGNAME/PATH/
    # SHELL/TERM/USER plus whatever the server record's own `env` says. The
    # research arsenal reads its three provider keys from ITS OWN environment,
    # so widening the Kimi CLI's parent environment (what
    # `project_worker_credentials` does) never reached the process making the
    # HTTP call -- measured as three live `"<KEY> missing"` errors on
    # `large-context-analyst@kimi`. Binding the already-loaded snapshot here is
    # the only seam that delivers them, and it mirrors what the Codex path
    # already does with `mcp_servers.<name>.env_vars`.
    #
    # BEST-EFFORT, like the loader: a key the secret store did not supply is
    # simply absent, and the tool degrades to its own "key missing" error while
    # the launch receipt names it under `credential_missing`. An empty mapping
    # therefore writes no `env` at all rather than an empty one.
    bound_research_environment: dict[str, str] = {}
    if research_environment is not None:
        if not isinstance(research_environment, Mapping) or set(
            research_environment
        ) - set(RESEARCH_API_KEY_NAMES):
            raise CapabilityDenied("Kimi research environment is not exactly bound")
        for name in RESEARCH_API_KEY_NAMES:
            if name not in research_environment:
                continue
            value = research_environment[name]
            if (
                not isinstance(value, str)
                or not value
                or "\x00" in value
                or "\n" in value
                or len(value.encode("utf-8")) > 16384
            ):
                raise CapabilityDenied("Kimi research environment is invalid")
            bound_research_environment[name] = value
        if bound_research_environment and RESEARCH_ARSENAL_SERVER not in authorized:
            raise CapabilityDenied(
                "Kimi research credentials bound for an unauthorized server"
            )

    artifacts = host_artifacts or KimiLocalHostArtifacts(
        interpreter=root / ".venv" / "bin" / "python",
        sequential_thinking=KIMI_SEQUENTIAL_COMMAND,
    )
    interpreter = Path(artifacts.interpreter)
    sequential_command = Path(artifacts.sequential_thinking)
    selected: dict[str, dict[str, object]] = {}
    script_names = set(authorized) & set(KIMI_LOCAL_SERVER_SCRIPTS)
    if script_names and (
        not interpreter.is_absolute()
        or not interpreter.is_file()
        or not os.access(interpreter, os.X_OK)
    ):
        raise CapabilityDenied("Kimi local template interpreter is unavailable")
    for name in authorized:
        if name == "sequential-thinking":
            if (
                not sequential_command.is_absolute()
                or not sequential_command.is_file()
                or not os.access(sequential_command, os.X_OK)
            ):
                raise CapabilityDenied(
                    "Kimi sequential-thinking executable is unavailable"
                )
            selected[name] = {"command": str(sequential_command)}
            continue
        script = root / KIMI_LOCAL_SERVER_SCRIPTS[name]
        try:
            resolved_script = script.resolve(strict=True)
        except (OSError, RuntimeError):
            raise CapabilityDenied(
                "Kimi local template server script is unavailable"
            ) from None
        if (
            script.is_symlink()
            or not resolved_script.is_file()
            or not resolved_script.is_relative_to(root)
        ):
            raise CapabilityDenied("Kimi local template server script is unavailable")
        selected[name] = {
            "command": str(interpreter),
            "args": [str(script)],
        }
        if name == "chrono-vault":
            selected[name]["env"] = bound_vault_environment
        elif name == RESEARCH_ARSENAL_SERVER and bound_research_environment:
            selected[name]["env"] = bound_research_environment
    return selected


def _kimi_none_aperture_environment(
    vault_environment: Mapping[str, str] | None,
) -> bool:
    """Recognize the controller projection that intentionally omits vault paths."""

    if not isinstance(vault_environment, Mapping) or set(vault_environment) != {
        "CHRONO_VAULT_CONTEXT"
    }:
        return False
    vault_context = vault_environment["CHRONO_VAULT_CONTEXT"]
    try:
        decoded_context = json.loads(
            vault_context,
            parse_constant=_reject_non_finite_json,
        )
    except (TypeError, ValueError):
        return False
    return (
        isinstance(vault_context, str)
        and "\x00" not in vault_context
        and len(vault_context.encode("utf-8")) <= 16384
        and isinstance(decoded_context, dict)
        and decoded_context.get("schema") == "chrono-vault-context/v1"
        and decoded_context.get("aperture") == "none"
        and json.dumps(
            decoded_context,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        == vault_context
    )


def load_tool_classes(
    *,
    repo_root: Path,
    lane: str,
    specialist: str,
    source_path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Read declared tool classes plus namespaced MCP requirement classes.

    The generated lane adapters flatten the capability source down to bare name
    arrays (``tools: ["pdftotext","zotero"]``), which is why the launch gate had
    no way to tell a PATH binary from a GUI app bundle. This reads the typed
    record back out of the versioned source for the exact (specialist, lane)
    pair. MCP records use an ``mcp:`` key prefix so a same-named tool and server
    cannot collide. Returns ``{}`` when the source is unreadable or the pair is
    absent, keeping unclassified capabilities fail-closed in ``plan_lane``.
    """

    path = (
        Path(source_path)
        if source_path is not None
        else Path(repo_root) / CAPABILITY_SOURCE_RELATIVE
    )
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return {}
    source_lane = "gpt-codex" if lane == "codex" else lane
    classes: dict[str, dict[str, str]] = {}
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or entry.get("specialist") != specialist
            or entry.get("lane") != source_lane
        ):
            continue
        for kind in ("tools", "mcps"):
            for capability in entry.get(kind) or ():
                if not isinstance(capability, dict):
                    continue
                identifier = capability.get("id")
                if not isinstance(identifier, str) or not identifier:
                    continue
                if kind == "mcps":
                    identifier = "mcp:" + identifier.removeprefix("lead:")
                requirement = capability.get("requirement")
                classes[identifier] = {
                    "requirement": (
                        requirement if isinstance(requirement, str) else ""
                    ),
                    "availability": str(capability.get("availability") or ""),
                    "evidence": str(capability.get("evidence") or ""),
                }
    return classes


def _tool_gates_launch(tool_class: Mapping[str, str] | None) -> bool:
    """True only when a `which()` miss is real evidence this role cannot run.

    Fail-closed on an unknown tool (no class == the old behaviour), open only
    for an explicitly `preferred` tool or one whose declared evidence is not a
    PATH lookup at all. See ``PATH_RESOLVABLE_EVIDENCE``.
    """

    if tool_class is None:
        return True
    if str(tool_class.get("requirement") or "required") != "required":
        return False
    return str(tool_class.get("evidence") or "") in PATH_RESOLVABLE_EVIDENCE


def _mcp_gates_launch(mcp_class: Mapping[str, object] | None) -> bool:
    """True unless an MCP is explicitly classified as preferred."""

    if not isinstance(mcp_class, Mapping):
        return True
    requirement = mcp_class.get("requirement")
    return requirement != "preferred"


def partition_absent_mcps(
    *,
    authorized: tuple[str, ...] | list[str],
    configured: tuple[str, ...] | list[str],
    mcp_classes: Mapping[str, Mapping[str, object]] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split absent MCPs into launch-blocking and degraded declarations.

    The native Codex path and ``plan_lane`` must make the same decision from
    the typed capability source. Unknown or malformed metadata stays
    fail-closed; only an explicit ``preferred`` declaration can degrade.
    """

    classes = mcp_classes or {}
    absent = tuple(sorted(set(authorized) - set(configured)))
    blocking = tuple(
        name for name in absent if _mcp_gates_launch(classes.get(name))
    )
    degraded = tuple(name for name in absent if name not in blocking)
    return blocking, degraded


def mcp_health(*, lane: str, details: Mapping[str, object]) -> str:
    """Classify ONE configured server record as healthy/unknown/unhealthy.

    One predicate, every lane. `unknown` is not a euphemism for healthy: it
    means this lane collected no health evidence for this record (see
    ``MCP_HEALTH_INSPECTED_LANES``), so there is nothing to degrade on. Only a
    lane that actually probed can report `unhealthy`.
    """

    status = details.get("status")
    if status is None:
        return "unknown"
    if not isinstance(status, str):
        raise CapabilityDenied("configured MCP server has an unsafe status")
    if MCP_HEALTHY_STATUS_RE.match(status):
        return "healthy"
    if (
        lane == "claude"
        and status.startswith("⏸ Pending approval")
        and isinstance(details.get("project_config"), dict)
    ):
        # The role config re-supplies this server to the child directly, so a
        # pending in-project approval is a configuration state, not ill health.
        return "healthy"
    return "unhealthy"


def _validate_server_record(
    *, name: str, details: Mapping[str, object]
) -> None:
    """Fail closed on an authorized server whose RECORD is unsafe.

    This is the structural leg. It stays a hard denial: an unparseable or
    unsafe record means the plan cannot be enforced, which is categorically
    different from a well-formed server that happens to be down right now.
    """

    if not isinstance(details, Mapping):
        raise CapabilityDenied(f"configured MCP server {name} has an unsafe record")
    status = details.get("status")
    if status is not None and (
        not isinstance(status, str)
        or "\x00" in status
        or "\n" in status
        or len(status) > MCP_STATUS_MAX_LENGTH
    ):
        raise CapabilityDenied(f"configured MCP server {name} has an unsafe status")
    live_name = details.get("live_name")
    if live_name is not None and (
        not isinstance(live_name, str)
        or (
            live_name not in CLAUDE_FIRST_PARTY_SERVERS
            and not CLAUDE_LIVE_SERVER_RE.fullmatch(live_name)
        )
    ):
        raise CapabilityDenied(f"configured MCP server {name} has an unsafe live name")


def plan_lane(
    *,
    lane: str,
    projection: Mapping[str, object],
    configured_servers: Mapping[str, Mapping[str, object]],
    tool_lookup: Callable[[str], str | None] | None = None,
    tool_classes: Mapping[str, Mapping[str, str]] | None = None,
    mcp_classes: Mapping[str, Mapping[str, object]] | None = None,
    repo_root: Path | None = None,
    kimi_vault_environment: Mapping[str, str] | None = None,
    kimi_research_environment: Mapping[str, str] | None = None,
    kimi_host_artifacts: KimiLocalHostArtifacts | None = None,
    broker_chrono_vault: bool = False,
) -> LaneCapabilityPlan:
    """Build one fail-closed, deterministic native-CLI enforcement plan."""

    if lane not in LANES:
        raise CapabilityDenied(f"unsupported capability lane: {lane!r}")
    if not isinstance(broker_chrono_vault, bool):
        raise CapabilityDenied("broker_chrono_vault must be a boolean")
    raw_authorized = projection.get("mcps", ())
    raw_brokered = projection.get("brokered_mcps", ())
    if not isinstance(raw_authorized, (list, tuple)) or not isinstance(
        raw_brokered, (list, tuple)
    ):
        raise CapabilityDenied("role MCP declarations have the wrong shape")
    if any(not isinstance(name, str) for name in (*raw_authorized, *raw_brokered)):
        raise CapabilityDenied("role MCP declaration contains an unsafe name")
    brokered = tuple(raw_brokered)
    if lane == "kimi":
        if raw_authorized:
            raise CapabilityDenied(
                "Kimi direct role MCP declarations are forbidden; use lead: declarations"
            )
        if any(name.startswith("lead:") for name in brokered):
            raise CapabilityDenied("Kimi brokered MCP names must be stripped")
        if brokered != tuple(sorted(set(brokered))):
            raise CapabilityDenied("Kimi brokered MCP names must be sorted unique")
        if (
            not broker_chrono_vault
            and "chrono-vault" in brokered
            and _kimi_none_aperture_environment(kimi_vault_environment)
        ):
            brokered = tuple(name for name in brokered if name != "chrono-vault")
        authorized = brokered
        template_authorized = tuple(
            name
            for name in authorized
            if not (broker_chrono_vault and name == CHRONO_VAULT_SERVER)
        )
        configured_servers = dict(_kimi_local_server_templates(
            repo_root=repo_root,
            authorized=template_authorized,
            vault_environment=kimi_vault_environment,
            research_environment=kimi_research_environment,
            host_artifacts=kimi_host_artifacts,
        ))
        if broker_chrono_vault and CHRONO_VAULT_SERVER in authorized:
            # A deliberately inert placeholder makes a forgotten supervisor
            # rewrite fail closed. broker_chrono_vault_plan replaces it only
            # after the retained listener and token exist.
            configured_servers[CHRONO_VAULT_SERVER] = {
                "command": "/usr/bin/false"
            }
    else:
        authorized = tuple(sorted(set(raw_authorized)))
        brokered = tuple(sorted(set(brokered)))
    tools = tuple(sorted(set(projection.get("tools", ()))))
    configured = tuple(sorted(configured_servers))
    if any(
        not isinstance(name, str) or not SERVER_NAME_RE.fullmatch(name)
        for name in (*authorized, *brokered, *configured)
    ):
        raise CapabilityDenied("MCP server name is unsafe")
    classes = mcp_classes
    if classes is None:
        classes = {
            name.removeprefix("mcp:"): details
            for name, details in (tool_classes or {}).items()
            if name.startswith("mcp:")
        }
    classes = classes or {}
    # STRUCTURAL: an absent REQUIRED server cannot be enforced at all. Missing
    # or malformed requirement metadata defaults to required and fails closed.
    blocking_absent_mcps, degraded_absent_mcps = partition_absent_mcps(
        authorized=authorized,
        configured=configured,
        mcp_classes=classes,
    )
    if blocking_absent_mcps:
        raise CapabilityDenied(
            "role requires unconfigured MCP servers: "
            + ", ".join(f"{name} (absent)" for name in blocking_absent_mcps)
        )
    # DEGRADATION: a declared non-required server may be absent. Remove it from
    # the enforceable set and surface the absence through the existing health
    # fields so the launch receipt and injected worker notice both record it.
    authorized = tuple(
        name for name in authorized if name not in degraded_absent_mcps
    )
    # Agy exposes every enabled persistent MCP to every worker. Require the four
    # operator-selected Chrono servers, then report the entire enabled inventory
    # as authorized rather than pretending an unsupported flag disabled extras.
    if lane == "gemini":
        missing_global_mcps = tuple(
            sorted(AGY_GLOBAL_CHRONO_MCPS - set(configured))
        )
        if missing_global_mcps:
            raise CapabilityDenied(
                "agy global MCP exposure is missing required Chrono servers: "
                + ", ".join(missing_global_mcps)
            )
        authorized = configured
    elif lane == "grok":
        # Grok discovers persistent host MCP configuration and exposes it as a
        # global surface. Record that complete surface instead of claiming a
        # per-invocation selector the CLI does not provide.
        authorized = configured
    # STRUCTURAL: an unsafe record is a defect in the plan, not an outage.
    for name in authorized:
        _validate_server_record(name=name, details=configured_servers[name])
    # RUNTIME: record ill health and let the launch proceed. A worker that never
    # calls this server is unaffected; one that does is told up front.
    configured_unhealthy_status = tuple(
        (name, str(configured_servers[name]["status"]))
        for name in authorized
        if mcp_health(lane=lane, details=configured_servers[name]) == "unhealthy"
    )
    unhealthy_status = tuple(
        sorted(
            configured_unhealthy_status
            + tuple((name, "absent") for name in degraded_absent_mcps)
        )
    )
    unhealthy_mcps = tuple(name for name, _status in unhealthy_status)
    disabled = (
        ()
        if lane in {"gemini", "grok"}
        else tuple(sorted(set(configured) - set(authorized)))
    )

    capability_gaps: tuple[str, ...] = ()
    if lane == "gemini":
        # Gemini adapter tools are native CLI tool names, not host executables.
        available_tools = tools
        missing_tools: tuple[str, ...] = ()
    else:
        lookup = tool_lookup or shutil.which
        if any(not TOOL_NAME_RE.fullmatch(name) for name in tools):
            raise CapabilityDenied("role declares an unsafe local tool name")
        classes = tool_classes or {}
        available_tools = tuple(name for name in tools if lookup(name))
        missing_tools = tuple(sorted(set(tools) - set(available_tools)))
        # F6: split a `which()` miss into "this role genuinely cannot run" and
        # "this capability was never reachable through PATH in the first place".
        blocking = tuple(
            name for name in missing_tools if _tool_gates_launch(classes.get(name))
        )
        capability_gaps = tuple(
            name for name in missing_tools if name not in blocking
        )
        if blocking:
            raise CapabilityDenied(
                "role requires unavailable local tools: " + ", ".join(blocking)
            )

    role_config_json: str | None = None
    if lane == "codex":
        arguments: list[str] = []
        for server_name in configured:
            if server_name in authorized:
                arguments.extend(
                    ("-c", f"mcp_servers.{server_name}.enabled=true")
                )
            else:
                arguments.extend(
                    (
                        "-c",
                        (
                            f"mcp_servers.{server_name}="
                            '{enabled=false,command="/usr/bin/false"}'
                        ),
                    )
                )
        tag = "codex-cli-mcp-table-replacement-overrides/v1"
    elif lane == "claude":
        project_servers = {
            name: configured_servers[name]["project_config"]
            for name in authorized
            if isinstance(configured_servers[name].get("project_config"), dict)
        }
        if project_servers:
            role_config_json = _canonical_role_config(
                authorized=tuple(sorted(project_servers)),
                configured_servers=project_servers,
            )
        denied_tool_patterns = tuple(
            _claude_tool_pattern(configured_servers[name])
            for name in disabled
        )
        arguments = []
        if role_config_json is not None:
            arguments.extend(("--mcp-config", ROLE_CONFIG_MARKER))
        if denied_tool_patterns:
            arguments.extend(
                ("--disallowedTools", ",".join(denied_tool_patterns))
            )
        tag = "claude-cli-disallowed-mcp-tools/v1"
    elif lane == "gemini":
        arguments = []
        tag = "agy-cli-global-mcp-exposure/v1"
    elif lane == "grok":
        arguments = []
        tag = "grok-cli-global-mcp-exposure/v1"
    else:
        role_config_json = _canonical_role_config(
            authorized=authorized,
            configured_servers=configured_servers,
        )
        arguments = ["--mcp-config-file", ROLE_CONFIG_MARKER]
        tag = "kimi-cli-main-lead-config-scoped/v1"
    return LaneCapabilityPlan(
        lane=lane,
        authorized_mcps=authorized,
        configured_mcps=configured,
        disabled_mcps=disabled,
        brokered_mcps=brokered,
        authorized_tools=tools,
        available_tools=available_tools,
        missing_tools=missing_tools,
        capability_enforcement=tag,
        cli_args=tuple(arguments),
        role_config_json=role_config_json,
        capability_gaps=capability_gaps,
        unhealthy_mcps=unhealthy_mcps,
        unhealthy_mcp_status=unhealthy_status,
    )


def materialize_role_config(
    plan: LaneCapabilityPlan,
    *,
    worktree_root: Path,
    task_id: str,
    attempt_id: str,
) -> Path:
    """Atomically materialize a generated config inside one owned worktree."""

    if plan.role_config_json is None:
        raise CapabilityDenied(f"{plan.lane} does not require a role config file")
    if not SERVER_NAME_RE.fullmatch(task_id) or not SERVER_NAME_RE.fullmatch(attempt_id):
        raise CapabilityDenied("task or attempt id is unsafe for role config")
    worktree = Path(worktree_root).resolve(strict=True)
    config_dir = worktree / ".role-capabilities"
    config_dir.mkdir(mode=0o700)
    output = config_dir / f"{plan.lane}-{special_name(task_id)}-{attempt_id}.json"
    if output.exists():
        raise CapabilityDenied("role config output already exists")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", dir=str(config_dir)
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(plan.role_config_json + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary_name, output)
        directory_fd = os.open(config_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        # The packet's no-delete rule applies even to failed runtime temps.
        # Leave the owner-only file in the isolated worktree for inspection.
        raise
    if (
        os.path.commonpath((str(output.resolve(strict=True)), str(worktree)))
        != str(worktree)
    ):
        raise CapabilityDenied("materialized role config escaped its worktree")
    return output


def special_name(value: str) -> str:
    """Bound filenames while preserving the validated task identity."""

    return value[:96]


def cli_args_for_materialized(
    plan: LaneCapabilityPlan, path: Path | None
) -> tuple[str, ...]:
    """Replace the internal config marker with an exact worktree path."""

    if ROLE_CONFIG_MARKER not in plan.cli_args:
        if path is not None:
            raise CapabilityDenied(f"{plan.lane} plan does not accept a config file")
        return plan.cli_args
    if path is None or not Path(path).is_absolute():
        raise CapabilityDenied("role config path must be absolute")
    return tuple(
        str(path) if value == ROLE_CONFIG_MARKER else value
        for value in plan.cli_args
    )


__all__ = [
    "AGY_GLOBAL_CHRONO_MCPS",
    "CapabilityDenied",
    "broker_chrono_vault_plan",
    "codex_chrono_vault_relay_args",
    "chrono_vault_relay_server",
    "KimiLocalHostArtifacts",
    "LaneCapabilityPlan",
    "adapter_path_for",
    "cli_args_for_materialized",
    "load_json_mcp_servers",
    "load_projection",
    "materialize_role_config",
    "mcp_health",
    "parse_claude_enabled_plugins",
    "parse_claude_project_plugin_dirs",
    "parse_live_mcp_listing",
    "partition_absent_mcps",
    "plan_lane",
]
