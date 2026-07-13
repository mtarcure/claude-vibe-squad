"""chrono-vault — shared infrastructure MCP for KG state + Obsidian navigation.

Merges old chrono-kg (record_attempt, record_finding, recall, etc.) with old
chrono-obsidian (vault_list, vault_get, vault_search, etc.) into one plugin.

SQLite indexes use WAL mode + 5000ms busy timeout for parallel-dispatch safety.
Atomic writes per TOOLS.md: tmp + fsync + os.replace.

Tools added in subsequent tasks:
- Task 2: KG state ops (record_attempt, record_finding, recall, list_attempts)
- Task 3: Obsidian REST navigation (vault_list, vault_get, vault_search, obsidian_health_check)
- Task 4: capture_* helpers wrapping vendored capture support
"""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chrono-vault")


def _vault_root() -> Path:
    return Path(os.environ.get("CHRONO_VAULT_ROOT", os.path.expanduser("~/Obsidian-Chrono")))


def _state_dir() -> Path:
    return _vault_root() / "chrono" / "_state"


def _connect(db_name: str) -> sqlite3.Connection:
    """Open SQLite with WAL + busy timeout. Idempotent (safe on every call)."""
    _state_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_state_dir() / db_name, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Tools added in subsequent tasks.


CANONICAL_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})


def _init_kg_schema() -> None:
    """Idempotent schema init for KG tables."""
    with _connect("kg.db") as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                target TEXT NOT NULL,
                attack_class TEXT NOT NULL,
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS findings (
                finding_id TEXT PRIMARY KEY,
                attempt_id TEXT NOT NULL,
                title TEXT NOT NULL,
                severity TEXT NOT NULL,
                description TEXT NOT NULL,
                evidence TEXT NOT NULL,
                ts REAL NOT NULL,
                FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id)
            );
            CREATE INDEX IF NOT EXISTS idx_attempts_target ON attempts(target);
            CREATE INDEX IF NOT EXISTS idx_findings_attempt ON findings(attempt_id);
        """)


@mcp.tool()
def record_attempt(role: str, target: str, attack_class: str) -> str:
    """Record a specialist attempt. Returns attempt_id."""
    _init_kg_schema()
    aid = f"a-{uuid.uuid4().hex[:12]}"
    with _connect("kg.db") as conn:
        conn.execute(
            "INSERT INTO attempts(attempt_id, role, target, attack_class, ts) VALUES (?,?,?,?,?)",
            (aid, role, target, attack_class, time.time()),
        )
    return aid


@mcp.tool()
def record_finding(
    attempt_id: str,
    title: str,
    severity: str,
    description: str,
    evidence: str,
) -> str:
    """Record a finding. Requires existing attempt_id. severity MUST be canonical lowercase enum."""
    if severity not in CANONICAL_SEVERITIES:
        raise ValueError(
            f"severity must be one of {sorted(CANONICAL_SEVERITIES)}, got {severity!r}"
        )
    _init_kg_schema()
    with _connect("kg.db") as conn:
        cur = conn.execute("SELECT 1 FROM attempts WHERE attempt_id=?", (attempt_id,))
        if cur.fetchone() is None:
            raise LookupError(f"no such attempt_id: {attempt_id}")
        fid = f"f-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO findings(finding_id, attempt_id, title, severity, description, evidence, ts) "
            "VALUES (?,?,?,?,?,?,?)",
            (fid, attempt_id, title, severity, description, evidence, time.time()),
        )
    return fid


@mcp.tool()
def list_attempts(
    target: str | None = None,
    role: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List attempts, optionally filtered by target or role. Most recent first."""
    _init_kg_schema()
    sql = "SELECT * FROM attempts WHERE 1=1"
    params: list[Any] = []
    if target:
        sql += " AND target = ?"
        params.append(target)
    if role:
        sql += " AND role = ?"
        params.append(role)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    with _connect("kg.db") as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]


@mcp.tool()
def recall(query: str, topic: str | None = None, limit: int = 5) -> dict[str, Any]:
    """Recall — minimal stub for Phase 2. Phase 4 expands with FTS + vector + decay weighting."""
    _init_kg_schema()
    sql = (
        "SELECT title, description FROM findings "
        "WHERE description LIKE ? OR title LIKE ? "
        "ORDER BY ts DESC LIMIT ?"
    )
    pat = f"%{query}%"
    with _connect("kg.db") as conn:
        rows = list(conn.execute(sql, (pat, pat, limit)))
    return {
        "query": query,
        "topic": topic,
        "chunks": [{"title": r[0], "description": r[1]} for r in rows],
    }


OBSIDIAN_REST_BASE = "http://127.0.0.1:27123"


def _obsidian_headers() -> dict[str, str]:
    key = os.environ.get("OBSIDIAN_REST_API_KEY", "")
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _degraded(reason: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": reason, **extra}


@mcp.tool()
def vault_list(glob_pattern: str = "") -> dict[str, Any]:
    """List vault files via Obsidian Local REST API. Optional glob filter."""
    if not _obsidian_headers():
        return _degraded("missing OBSIDIAN_REST_API_KEY")
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{OBSIDIAN_REST_BASE}/vault/", headers=_obsidian_headers())
            r.raise_for_status()
        files = r.json().get("files", [])
        if glob_pattern:
            import fnmatch
            files = [f for f in files if fnmatch.fnmatch(f, glob_pattern)]
        return {"ok": True, "files": files}
    except httpx.HTTPStatusError as exc:
        # Rule 17.1: never str(exc); only status_code + reason_phrase
        return _degraded(
            f"http_{exc.response.status_code}",
            reason_phrase=exc.response.reason_phrase,
        )
    except (httpx.RequestError, OSError) as exc:
        return _degraded(f"network_error: {type(exc).__name__}")


@mcp.tool()
def vault_get(path: str) -> dict[str, Any]:
    """Get a single vault file's content."""
    if not _obsidian_headers():
        return _degraded("missing OBSIDIAN_REST_API_KEY")
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(
                f"{OBSIDIAN_REST_BASE}/vault/{path}",
                headers=_obsidian_headers(),
            )
            r.raise_for_status()
        return {"ok": True, "path": path, "content": r.text}
    except httpx.HTTPStatusError as exc:
        return _degraded(
            f"http_{exc.response.status_code}",
            reason_phrase=exc.response.reason_phrase,
        )
    except (httpx.RequestError, OSError) as exc:
        return _degraded(f"network_error: {type(exc).__name__}")


@mcp.tool()
def vault_search(query: str, mode: str = "text") -> dict[str, Any]:
    """Search vault. mode: text | regex. (dataview mode is Phase 4)"""
    if not _obsidian_headers():
        return _degraded("missing OBSIDIAN_REST_API_KEY")
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                f"{OBSIDIAN_REST_BASE}/search/simple/",
                params={"query": query},
                headers=_obsidian_headers(),
            )
            r.raise_for_status()
        return {"ok": True, "results": r.json()}
    except httpx.HTTPStatusError as exc:
        return _degraded(
            f"http_{exc.response.status_code}",
            reason_phrase=exc.response.reason_phrase,
        )
    except (httpx.RequestError, OSError) as exc:
        return _degraded(f"network_error: {type(exc).__name__}")


@mcp.tool()
def obsidian_health_check() -> dict[str, Any]:
    """Check Obsidian Local REST API connectivity."""
    if not _obsidian_headers():
        return {"ok": False, "error": "missing OBSIDIAN_REST_API_KEY"}
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(
                f"{OBSIDIAN_REST_BASE}/",
                headers=_obsidian_headers(),
            )
        return {"ok": r.status_code == 200, "status_code": r.status_code}
    except (httpx.RequestError, OSError) as exc:
        return {"ok": False, "error": f"network_error: {type(exc).__name__}"}


import importlib.util as _importlib_util


def _load_capture_support():
    support_path = Path(__file__).resolve().parents[1] / "_support" / "capture.py"
    spec = _importlib_util.spec_from_file_location("vibe_squad_capture", support_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load capture support from {support_path}")
    module = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_capture = _load_capture_support()


@mcp.tool()
def capture_session(model: str, cwd: str, first_message: str = "") -> dict[str, Any]:
    """Append session-start header to vault sessions/<today>.md. Wraps vendored capture support."""
    _capture.handle_session_start({
        "model": model,
        "cwd": cwd,
        "first_message": first_message,
    })
    return {"ok": True}


@mcp.tool()
def capture_dispatch(role: str, model: str, prompt: str, output: str) -> dict[str, Any]:
    """Append dispatch entry to vault dispatches/<today>.md. Wraps vendored capture support."""
    _capture.handle_dispatch({
        "role": role,
        "model": model,
        "prompt": prompt,
        "output": output,
    })
    return {"ok": True}


@mcp.tool()
def capture_review(provider: str, target: str, prompt: str, output: str) -> dict[str, Any]:
    """Write cross-provider review to vault reviews/. Wraps vendored capture support."""
    _capture.handle_review(provider, {
        "target": target,
        "prompt": prompt,
        "output": output,
    })
    return {"ok": True}


@mcp.tool()
def capture_research(query: str, tool: str, output: str) -> dict[str, Any]:
    """Write research artifact to vault research/. Wraps vendored capture support."""
    _capture.handle_research({
        "query": query,
        "tool": tool,
        "output": output,
    })
    return {"ok": True}


# ---------------------------------------------------------------------------
# Phase 4 Task 3 — MCP namespace aliases for archive role agent compat.
# 24 archive role agents reference mcp__chrono_kg__*, mcp__chrono_obsidian__*,
# mcp__chrono_catalog__* — names dropped in v1.3 §5 and folded into chrono-vault.
# These additional FastMCP servers expose the same canonical functions under
# the legacy namespaces so archive plugins continue to work without edits.
#
# Wrappers use FastMCP's @tool(name=...) so the registered tool name matches
# the canonical (un-prefixed) name while the Python function uses a prefixed
# name to avoid collision with the canonical implementations defined above.
# ---------------------------------------------------------------------------

kg_alias_mcp = FastMCP("chrono-kg")


@kg_alias_mcp.tool(name="record_attempt")
def _kg_alias_record_attempt(role: str, target: str, attack_class: str) -> str:
    """Alias for chrono-vault.record_attempt — preserves archive plugin compat."""
    return record_attempt(role=role, target=target, attack_class=attack_class)


@kg_alias_mcp.tool(name="record_finding")
def _kg_alias_record_finding(
    attempt_id: str,
    title: str,
    severity: str,
    description: str,
    evidence: str,
) -> str:
    return record_finding(
        attempt_id=attempt_id,
        title=title,
        severity=severity,
        description=description,
        evidence=evidence,
    )


@kg_alias_mcp.tool(name="list_attempts")
def _kg_alias_list_attempts(
    target: str | None = None,
    role: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return list_attempts(target=target, role=role, limit=limit)


@kg_alias_mcp.tool(name="recall")
def _kg_alias_recall(query: str, topic: str | None = None, limit: int = 5) -> dict[str, Any]:
    return recall(query=query, topic=topic, limit=limit)


obsidian_alias_mcp = FastMCP("chrono-obsidian")


@obsidian_alias_mcp.tool(name="vault_list")
def _obsidian_alias_vault_list(glob_pattern: str = "") -> dict[str, Any]:
    return vault_list(glob_pattern=glob_pattern)


@obsidian_alias_mcp.tool(name="vault_get")
def _obsidian_alias_vault_get(path: str) -> dict[str, Any]:
    return vault_get(path=path)


@obsidian_alias_mcp.tool(name="vault_search")
def _obsidian_alias_vault_search(query: str, mode: str = "text") -> dict[str, Any]:
    return vault_search(query=query, mode=mode)


catalog_alias_mcp = FastMCP("chrono-catalog")


@catalog_alias_mcp.tool(name="list_skills")
def _catalog_alias_list_skills(role: str = "") -> dict[str, Any]:
    """chrono-catalog was dropped in v1.3; return graceful empty for archive callers."""
    return {
        "ok": True,
        "skills": [],
        "note": (
            "chrono-catalog deprecated in chrono v1.3 — skills surfaced via plugin "
            "manifests directly. Archive callers receive empty list to avoid breaking dispatch."
        ),
    }


def _run_mcp_server(server: FastMCP) -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        server.settings.port = int(os.environ.get("MCP_PORT", "3001"))
        server.run(transport="sse")
    else:
        server.run()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--namespace":
        ns = sys.argv[2]
        if ns == "kg":
            _run_mcp_server(kg_alias_mcp)
        elif ns == "obsidian":
            _run_mcp_server(obsidian_alias_mcp)
        elif ns == "catalog":
            _run_mcp_server(catalog_alias_mcp)
        else:
            _run_mcp_server(mcp)
    else:
        _run_mcp_server(mcp)
