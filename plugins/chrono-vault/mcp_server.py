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

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from clearance import ClearanceError, can_read, lane_clearance
import index as vault_index
from lifecycle import LifecycleError
from lifecycle import get_note as lifecycle_get_note
from lifecycle import record_usage as lifecycle_record_usage
from lifecycle import set_status as lifecycle_set_status
from notes import NOTE_TYPES, record as record_note
from recall import RecallError, _read_index, recall as recall_notes
from vaultroot import VaultRootError, read_sentinel, resolve_vault_root

mcp = FastMCP("chrono-vault")


def _get_note_for_lane(note_id: str) -> dict[str, Any]:
    note = lifecycle_get_note(note_id)
    if not can_read(note.get("sensitivity"), lane_clearance()):
        raise ClearanceError("note is unavailable at the current clearance")
    return note


def _vault_root() -> Path:
    return resolve_vault_root()


def _state_dir() -> Path:
    return _vault_root() / "chrono" / "_state"


def _connect(db_name: str) -> sqlite3.Connection:
    """Open SQLite with WAL + busy timeout. Idempotent (safe on every call)."""
    conn = sqlite3.connect(_state_dir() / db_name, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Tools added in subsequent tasks.


CANONICAL_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})


def _compat_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _compat_evidence_ref(value: str) -> str:
    evidence = _compat_text(value, "evidence")
    immutable_prefixes = (
        "artifact:",
        "note:",
        "sha256:",
        "note-content-sha256:",
        "legacy-evidence-sha256:",
    )
    if "\n" not in evidence and "\r" not in evidence and evidence.startswith(
        immutable_prefixes
    ):
        return evidence
    digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    return f"legacy-evidence-sha256:{digest}"


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
    """Compatibility wrapper that records a canonical attempt note."""
    normalized_role = _compat_text(role, "role")
    normalized_target = _compat_text(target, "target")
    normalized_attack_class = _compat_text(attack_class, "attack_class")
    if any("\n" in value or "\r" in value for value in (normalized_role, normalized_target)):
        raise ValueError("role and target must each be one line")
    result = record_note(
        "attempt",
        {
            "title": f"{normalized_role} attempt against {normalized_target}",
            "body": (
                f"Role: {normalized_role}\n"
                f"Target: {normalized_target}\n"
                f"Attack class: {normalized_attack_class}\n"
            ),
            "target": normalized_target,
            "attack_class": normalized_attack_class,
            "keywords": [f"role-{normalized_role}"],
        },
    )
    return result["id"]


@mcp.tool()
def record(note_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Record one canonical markdown memory note."""
    return record_note(note_type, fields)


@mcp.tool()
def record_finding(
    attempt_id: str | None = None,
    title: str = "",
    severity: str = "",
    description: str = "",
    evidence: str = "",
    target: str | None = None,
    attack_class: str | None = None,
) -> str:
    """Compatibility wrapper that records a canonical finding without FK friction."""
    if severity not in CANONICAL_SEVERITIES:
        raise ValueError(
            f"severity must be one of {sorted(CANONICAL_SEVERITIES)}, got {severity!r}"
        )
    normalized_title = _compat_text(title, "title")
    normalized_description = _compat_text(description, "description")
    normalized_evidence = _compat_evidence_ref(evidence)

    attempt: dict[str, Any] | None = None
    if attempt_id:
        try:
            candidate = _get_note_for_lane(attempt_id)
        except (ClearanceError, LifecycleError):
            candidate = None
        if candidate is not None and candidate.get("type") == "attempt":
            attempt = candidate

    resolved_target = target if target is not None else (
        attempt["target"] if attempt is not None else None
    )
    resolved_attack_class = attack_class if attack_class is not None else (
        attempt["attack_class"] if attempt is not None else None
    )
    if resolved_target is None or resolved_attack_class is None:
        raise ValueError(
            "target and attack_class are required without a canonical attempt"
        )
    normalized_target = _compat_text(resolved_target, "target")
    normalized_attack_class = _compat_text(resolved_attack_class, "attack_class")
    evidence_refs = [normalized_evidence]
    if attempt is not None:
        evidence_refs.append(f"note:{attempt['id']}")
    result = record_note(
        "finding",
        {
            "title": normalized_title,
            "body": normalized_description,
            "target": normalized_target,
            "attack_class": normalized_attack_class,
            "sensitivity": (
                attempt["sensitivity"] if attempt is not None else "internal"
            ),
            "keywords": [f"severity-{severity}"],
            "evidence_refs": evidence_refs,
        },
    )
    return result["id"]


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
def recall(
    query: str,
    filters: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Recall ranked, quoted memory from the canonical FTS5 index."""
    return recall_notes(query=query, filters=filters, limit=limit)


@mcp.tool()
def get_note(id: str) -> dict[str, Any]:
    """Get one complete canonical memory note by stable ID."""
    return _get_note_for_lane(id)


@mcp.tool()
def set_status(
    id: str,
    new_status: str,
    reason: str,
    expected_revision: int,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Compare-and-swap note status and maintain supersede links."""
    _get_note_for_lane(id)
    if supersedes is not None:
        _get_note_for_lane(supersedes)
    return lifecycle_set_status(
        id=id,
        new_status=new_status,
        reason=reason,
        expected_revision=expected_revision,
        supersedes=supersedes,
    )


@mcp.tool()
def record_usage(
    recall_id: str,
    note_id: str,
    outcome: str,
    source_task: str | None = None,
) -> dict[str, Any]:
    """Record whether a recalled note was used, unhelpful, or incorrect."""
    return lifecycle_record_usage(
        recall_id=recall_id,
        note_id=note_id,
        outcome=outcome,
        source_task=source_task,
    )


def _fts5_available() -> bool:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(content)")
        return True
    except sqlite3.Error:
        return False
    finally:
        if connection is not None:
            connection.close()


def _note_inventory(
    root: Path,
) -> tuple[dict[str, int], dict[str, tuple[int, int, str]], bool]:
    counts = {note_type: 0 for note_type in sorted(NOTE_TYPES)}
    signatures: dict[str, tuple[int, int, str]] = {}
    seen_ids: set[str] = set()
    unsafe = False
    notes_root = root / "notes"
    if not notes_root.exists():
        return counts, signatures, unsafe
    if notes_root.is_symlink() or not notes_root.is_dir():
        return counts, signatures, True

    for note_type in sorted(NOTE_TYPES):
        type_dir = notes_root / note_type
        if not type_dir.exists():
            continue
        if type_dir.is_symlink() or not type_dir.is_dir():
            unsafe = True
            continue
        try:
            entries = list(type_dir.iterdir())
        except OSError:
            unsafe = True
            continue
        for path in entries:
            if path.suffix != ".md":
                continue
            if path.is_symlink() or not path.is_file():
                unsafe = True
                continue
            try:
                parsed = vault_index._parse_note(path)
            except (vault_index.MalformedNote, OSError):
                unsafe = True
                continue
            if parsed["id"] in seen_ids:
                unsafe = True
            seen_ids.add(parsed["id"])
            counts[note_type] += 1
            signatures[str(path)] = (
                int(parsed["size"]),
                int(parsed["mtime_ns"]),
                parsed["content_hash"],
            )
    return counts, signatures, unsafe


def _index_health(
    root: Path,
    note_signatures: dict[str, tuple[int, int, str]],
    unsafe_notes: bool,
) -> tuple[int, bool]:
    try:
        with _read_index(root) as connection:
            if connection is None:
                return 0, True
            generation_row = connection.execute(
                "SELECT value FROM state WHERE key='generation'"
            ).fetchone()
            if generation_row is None:
                return 0, True
            generation = int(generation_row[0])
            indexed = {
                row[0]: (int(row[1]), int(row[2]), row[3])
                for row in connection.execute(
                    "SELECT path, size, mtime_ns, content_hash FROM meta"
                )
            }
            quarantined = int(
                connection.execute("SELECT count(*) FROM quarantine").fetchone()[0]
            )
            dirty = (
                unsafe_notes
                or not vault_index._schema_is_current(connection)
                or indexed != note_signatures
                or quarantined > 0
            )
            return generation, dirty
    except (RecallError, OSError, sqlite3.Error, TypeError, ValueError):
        return 0, True


def _legacy_stores(root: Path | None) -> list[str]:
    repo_root = Path(__file__).resolve().parents[2]
    literal_phantom = Path("chrono") / "${CHRONO_VAULT_ROOT}"
    candidates: list[tuple[str, Path]] = [
        (
            "public:chrono/${CHRONO_VAULT_ROOT}/kg.db",
            repo_root / literal_phantom / "kg.db",
        ),
        (
            "public:chrono/${CHRONO_VAULT_ROOT}/_state/kg.db",
            repo_root / literal_phantom / "_state" / "kg.db",
        ),
        (
            "public:plugins/chrono-vault/_state/kg.db",
            Path(__file__).resolve().parent / "_state" / "kg.db",
        ),
    ]
    if root is not None:
        candidates.extend(
            (
                ("vault:kg.db", root / "kg.db"),
                ("vault:_state/kg.db", root / "_state" / "kg.db"),
                ("vault:chrono/_state/kg.db", root / "chrono" / "_state" / "kg.db"),
                (
                    "vault:chrono/${CHRONO_VAULT_ROOT}/kg.db",
                    root / literal_phantom / "kg.db",
                ),
                (
                    "vault:chrono/${CHRONO_VAULT_ROOT}/_state/kg.db",
                    root / literal_phantom / "_state" / "kg.db",
                ),
            )
        )
    return sorted(
        {
            label
            for label, path in candidates
            if os.path.lexists(path) and (path.is_symlink() or path.is_file())
        }
    )


@mcp.tool()
def health() -> dict[str, Any]:
    """Report canonical vault, index freshness, and legacy-store diagnostics."""
    fts5 = _fts5_available()
    try:
        root = resolve_vault_root()
        sentinel = read_sentinel(root)
    except VaultRootError:
        return {
            "vault_id": None,
            "root_valid": False,
            "schema_version": None,
            "fts5": fts5,
            "note_counts": {note_type: 0 for note_type in sorted(NOTE_TYPES)},
            "index_generation": 0,
            "index_dirty": True,
            "legacy_stores": _legacy_stores(None),
        }

    note_counts, note_signatures, unsafe_notes = _note_inventory(root)
    generation, index_dirty = _index_health(root, note_signatures, unsafe_notes)
    return {
        "vault_id": sentinel["vault_id"],
        "root_valid": True,
        "schema_version": sentinel["schema_version"],
        "fts5": fts5,
        "note_counts": note_counts,
        "index_generation": generation,
        "index_dirty": index_dirty,
        "legacy_stores": _legacy_stores(root),
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


_CAPTURE_DISABLED_ERROR = "capture_disabled_pending_canonical_migration"


def _capture_disabled() -> dict[str, Any]:
    """Fail closed until capture tools use the canonical rooted note writer."""
    return {
        "ok": False,
        "disabled": True,
        "error": _CAPTURE_DISABLED_ERROR,
    }


@mcp.tool()
def capture_session(model: str, cwd: str, first_message: str = "") -> dict[str, Any]:
    """Disabled pending migration to the canonical rooted note writer."""
    return _capture_disabled()


@mcp.tool()
def capture_dispatch(role: str, model: str, prompt: str, output: str) -> dict[str, Any]:
    """Disabled pending migration to the canonical rooted note writer."""
    return _capture_disabled()


@mcp.tool()
def capture_review(provider: str, target: str, prompt: str, output: str) -> dict[str, Any]:
    """Disabled pending migration to the canonical rooted note writer."""
    return _capture_disabled()


@mcp.tool()
def capture_research(query: str, tool: str, output: str) -> dict[str, Any]:
    """Disabled pending migration to the canonical rooted note writer."""
    return _capture_disabled()


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
    attempt_id: str | None = None,
    title: str = "",
    severity: str = "",
    description: str = "",
    evidence: str = "",
    target: str | None = None,
    attack_class: str | None = None,
) -> str:
    return record_finding(
        attempt_id=attempt_id,
        title=title,
        severity=severity,
        description=description,
        evidence=evidence,
        target=target,
        attack_class=attack_class,
    )


@kg_alias_mcp.tool(name="list_attempts")
def _kg_alias_list_attempts(
    target: str | None = None,
    role: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return list_attempts(target=target, role=role, limit=limit)


@kg_alias_mcp.tool(name="recall")
def _kg_alias_recall(
    query: str,
    filters: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    return recall(query=query, filters=filters, limit=limit)


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
