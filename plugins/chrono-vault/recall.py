"""BM25 recall over the disposable Chrono FTS5 index."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from index import FTS_COLUMNS, INDEX_SCHEMA_VERSION
from query import build_fts_query
from vaultroot import resolve_vault_root


DEFAULT_STATUSES = ("candidate", "verified")
ALL_STATUSES = frozenset(
    {"candidate", "verified", "superseded", "invalidated", "archived"}
)
NOTE_TYPES = frozenset({"attempt", "finding", "learning"})
FILTER_FIELDS = frozenset(
    {"target", "attack_class", "component", "type", "keywords", "status"}
)
WEIGHT_FIELDS = FTS_COLUMNS
MAX_QUERY_CHARS = 512
MAX_LIMIT = 50
MAX_QUOTED_CONTENT_CHARS = 600
COLUMN_SELECTOR_PATTERN = re.compile(
    r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*:"
)


class RecallError(RuntimeError):
    """Recall input or index state is invalid."""


def _empty(recall_id: str, *, query_error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "recall_id": recall_id,
        "tiers_searched": ["active"],
        "results": [],
    }
    if query_error is not None:
        result["query_error"] = query_error
    return result


def _validate_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise RecallError("limit must be an integer")
    if limit < 1 or limit > MAX_LIMIT:
        raise RecallError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def _validate_filters(filters: dict | None) -> tuple[dict[str, str], tuple[str, ...]]:
    if filters is None:
        return {}, DEFAULT_STATUSES
    if not isinstance(filters, dict):
        raise RecallError("filters must be a dict")
    unknown = set(filters) - FILTER_FIELDS
    if unknown:
        raise RecallError(f"unknown filters: {sorted(map(str, unknown))}")

    structured: dict[str, str] = {}
    for field in ("target", "attack_class", "component", "type", "keywords"):
        if field not in filters:
            continue
        value = filters[field]
        if not isinstance(value, str) or not value.strip():
            raise RecallError(f"filter {field} must be a non-empty string")
        if field == "type" and value not in NOTE_TYPES:
            raise RecallError(f"filter type must be one of {sorted(NOTE_TYPES)}")
        structured[field] = value

    raw_statuses = filters.get("status", DEFAULT_STATUSES)
    if isinstance(raw_statuses, str):
        statuses = (raw_statuses,)
    elif isinstance(raw_statuses, (list, tuple)):
        statuses = tuple(raw_statuses)
    else:
        raise RecallError("filter status must be a string or list of strings")
    if any(not isinstance(value, str) or value not in ALL_STATUSES for value in statuses):
        raise RecallError(f"filter status must use {sorted(ALL_STATUSES)}")
    return structured, tuple(dict.fromkeys(statuses))


def _load_weights(connection: sqlite3.Connection) -> tuple[float, ...]:
    row = connection.execute(
        "SELECT value FROM config WHERE key='bm25_weights'"
    ).fetchone()
    if row is None:
        raise RecallError("index is missing BM25 weights")
    try:
        raw_weights = json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RecallError("index BM25 weights are malformed") from exc
    if not isinstance(raw_weights, list) or len(raw_weights) != len(WEIGHT_FIELDS):
        raise RecallError("index BM25 weights have the wrong shape")

    weights: list[float] = []
    for value in raw_weights:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RecallError("index BM25 weights must be numeric")
        weight = float(value)
        if not math.isfinite(weight) or weight < 0:
            raise RecallError("index BM25 weights must be finite and non-negative")
        weights.append(weight)
    return tuple(weights)


@contextmanager
def _read_index(root: Path) -> Iterator[sqlite3.Connection | None]:
    index_dir = root / "index"
    if not index_dir.exists():
        yield None
        return
    if index_dir.is_symlink() or Path(os.path.realpath(index_dir)).parent != root:
        raise RecallError("index directory is unsafe")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise RecallError("secure index reads are unavailable")

    directory_fd = -1
    lock_fd = -1
    database_fd = -1
    connection: sqlite3.Connection | None = None
    try:
        directory_fd = os.open(index_dir, os.O_RDONLY | nofollow | directory)
        try:
            lock_fd = os.open(
                ".kg.lock",
                os.O_RDONLY | nofollow,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            yield None
            return
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise RecallError("index lock is not a regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_SH)

        try:
            database_fd = os.open(
                "kg.db",
                os.O_RDONLY | nofollow,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            yield None
            return
        if not stat.S_ISREG(os.fstat(database_fd).st_mode):
            raise RecallError("index database is not a regular file")

        connection = sqlite3.connect(
            f"{(index_dir / 'kg.db').as_uri()}?mode=ro",
            uri=True,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA query_only=ON")
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(notes_fts)")
        )
        if user_version != INDEX_SCHEMA_VERSION or columns != FTS_COLUMNS:
            raise RecallError("index schema is stale; run rebuild_index")
        yield connection
    except OSError as exc:
        raise RecallError("index is unsafe or inaccessible") from exc
    finally:
        if connection is not None:
            connection.close()
        if database_fd >= 0:
            os.close(database_fd)
        if lock_fd >= 0:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _quoted_snippet(body: str) -> str:
    normalized = "".join(
        character
        if character in "\n\t" or ord(character) >= 32
        else "�"
        for character in body
    )
    quoted = "\n".join(f"> {line}" for line in normalized.splitlines())
    if not quoted:
        quoted = "> "
    if len(quoted) > MAX_QUOTED_CONTENT_CHARS:
        quoted = quoted[: MAX_QUOTED_CONTENT_CHARS - 1] + "…"
    return (
        "[BEGIN QUOTED UNTRUSTED NOTE]\n"
        f"{quoted}\n"
        "[END QUOTED UNTRUSTED NOTE]"
    )


def _note_link(root: Path, absolute_path: str) -> str:
    path = Path(absolute_path)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RecallError("index contains a note path outside the private vault") from exc
    if len(relative.parts) < 3 or relative.parts[0] != "notes":
        raise RecallError("index contains an invalid note path")
    return relative.as_posix()


def _has_unknown_column_selector(query: str) -> bool:
    unquoted: list[str] = []
    in_quote = False
    index = 0
    while index < len(query):
        character = query[index]
        if character == '"':
            if in_quote and index + 1 < len(query) and query[index + 1] == '"':
                unquoted.extend((" ", " "))
                index += 2
                continue
            in_quote = not in_quote
            unquoted.append(" ")
        else:
            unquoted.append(" " if in_quote else character)
        index += 1
    return any(
        match.group(1).lower() not in WEIGHT_FIELDS
        for match in COLUMN_SELECTOR_PATTERN.finditer("".join(unquoted))
    )


def _is_fts_syntax_error(error: sqlite3.OperationalError) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "fts5: syntax error",
            "unterminated string",
            "malformed match",
            "unknown special query",
        )
    )


def recall(query: str, filters: dict = None, limit: int = 8) -> dict[str, Any]:
    """Return ranked, quoted note snippets from the active FTS5 tier."""
    recall_id = str(uuid.uuid4())
    if not isinstance(query, str):
        raise RecallError("query must be a string")
    if not query.strip() or "\x00" in query or len(query) > MAX_QUERY_CHARS:
        return _empty(recall_id, query_error="invalid_fts_query")
    if (
        _has_unknown_column_selector(query)
        or query.strip() == "*"
        or query.count('"') % 2
    ):
        return _empty(recall_id, query_error="invalid_fts_query")
    fts_query = build_fts_query(query)
    validated_limit = _validate_limit(limit)
    structured, statuses = _validate_filters(filters)
    if not statuses:
        return _empty(recall_id)

    root = resolve_vault_root()
    with _read_index(root) as connection:
        if connection is None:
            return _empty(recall_id)

        weights = _load_weights(connection)
        weight_sql = ",".join(format(value, ".17g") for value in weights)
        clauses = [
            "notes_fts MATCH ?",
            f"m.status IN ({','.join('?' for _ in statuses)})",
        ]
        parameters: list[Any] = [fts_query, *statuses]

        column_filters = {
            "target": "notes_fts.target = ?",
            "attack_class": "notes_fts.attack_class = ?",
            "component": "notes_fts.component = ?",
            "type": "m.note_type = ?",
        }
        for field, clause in column_filters.items():
            if field in structured:
                clauses.append(clause)
                parameters.append(structured[field])
        if "keywords" in structured:
            clauses.append(
                "instr(char(10) || notes_fts.keywords || char(10), "
                "char(10) || ? || char(10)) > 0"
            )
            parameters.append(structured["keywords"])
        parameters.append(validated_limit)

        sql = f"""
            SELECT
                m.id, m.path, m.status, m.sensitivity, m.content_hash,
                m.mtime_ns, notes_fts.title, notes_fts.body,
                bm25(notes_fts, {weight_sql}) AS raw_rank
            FROM notes_fts
            JOIN meta AS m ON m.docid = notes_fts.rowid
            WHERE {' AND '.join(clauses)}
            ORDER BY raw_rank ASC, m.mtime_ns DESC, m.id ASC
            LIMIT ?
        """
        try:
            rows = list(connection.execute(sql, parameters))
        except sqlite3.OperationalError as exc:
            if _is_fts_syntax_error(exc):
                return _empty(recall_id, query_error="invalid_fts_query")
            raise RecallError("index query failed") from exc

        generation_row = connection.execute(
            "SELECT value FROM state WHERE key='generation'"
        ).fetchone()
        if generation_row is None:
            raise RecallError("index generation is missing")
        generation = int(generation_row[0])
        weight_components = dict(zip(WEIGHT_FIELDS, weights, strict=True))
        results: list[dict[str, Any]] = []
        for row in rows:
            note_link = _note_link(root, row["path"])
            raw_rank = float(row["raw_rank"])
            score = -raw_rank
            results.append(
                {
                    "id": row["id"],
                    "score": score,
                    "score_components": {
                        "bm25": score,
                        "raw_bm25": raw_rank,
                        "weights": weight_components,
                        "recency_tiebreak_ns": int(row["mtime_ns"]),
                    },
                    "snippet": _quoted_snippet(row["body"]),
                    "note_link": note_link,
                    "status": row["status"],
                    "sensitivity": row["sensitivity"],
                    "provenance": {
                        "source": "chrono-vault",
                        "note_id": row["id"],
                        "note_link": note_link,
                        "content_hash": row["content_hash"],
                        "index_generation": generation,
                    },
                }
            )

    return {
        "recall_id": recall_id,
        "tiers_searched": ["active"],
        "results": results,
    }
