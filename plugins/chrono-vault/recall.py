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
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from clearance import can_read, lane_clearance
from index import FTS_COLUMNS, INDEX_SCHEMA_VERSION
from query import TOKEN_PATTERN, build_fts_query
from vaultroot import resolve_vault_root


DEFAULT_STATUSES = ("candidate", "verified")
ALL_STATUSES = frozenset(
    {"candidate", "verified", "superseded", "invalidated", "archived"}
)
NOTE_TYPES = frozenset({"attempt", "finding", "learning"})
FILTER_FIELDS = frozenset(
    {
        "written_before",
        "target",
        "attack_class",
        "component",
        "type",
        "keywords",
        "status",
        "max_sensitivity",
    }
)
# Least sensitive first: a ceiling is a prefix of this ladder.
SENSITIVITY_ORDER = ("internal", "restricted")
WEIGHT_FIELDS = FTS_COLUMNS
MAX_QUERY_CHARS = 512
MAX_LIMIT = 50
MAX_QUOTED_CONTENT_CHARS = 600
MAX_EXPANSION_TERMS = 16
# Vocabulary the squad writes one way and searches another. Every member of a
# group is interchangeable; multi-word members are matched as FTS5 phrases.
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("auth", "authentication", "authn"),
    ("authz", "authorization"),
    ("ssrf", "server side request forgery"),
    ("xss", "cross site scripting"),
    ("csrf", "cross site request forgery"),
    ("idor", "insecure direct object reference"),
    ("rce", "remote code execution"),
    ("sqli", "sql injection"),
    ("dos", "denial of service"),
    ("privesc", "privilege escalation"),
    ("reentrancy", "reentrant", "recursive call"),
    ("creds", "credentials"),
    ("secrets", "credentials"),
    ("recon", "reconnaissance"),
    ("repro", "reproduction"),
    ("config", "configuration"),
    ("perms", "permissions"),
    ("env", "environment"),
    ("db", "database"),
    ("deps", "dependencies"),
    ("mcp", "model context protocol"),
    ("rag", "retrieval augmented generation"),
    ("fts", "full text search"),
    ("kg", "knowledge graph"),
    ("regression", "regressed"),
    ("timeout", "timed out"),
)
COLUMN_SELECTOR_PATTERN = re.compile(
    r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*:"
)


class RecallError(RuntimeError):
    """Recall input or index state is invalid."""


def _term_tokens(term: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in TOKEN_PATTERN.findall(term))


# Each group member pre-tokenized, so matching is whole-token in both
# directions: an acronym query reaches the spelled-out note and vice versa.
SYNONYM_GROUP_TOKENS: tuple[tuple[tuple[str, ...], ...], ...] = tuple(
    tuple(_term_tokens(term) for term in group) for group in SYNONYM_GROUPS
)


def _quote_term(term: str) -> str:
    """Return one FTS5 literal; alias terms are constants but quote defensively."""
    return '"{}"'.format(term.replace('"', '""'))


def _contains_term(query_tokens: list[str], term_tokens: tuple[str, ...]) -> bool:
    """Match a term only as a contiguous run of whole query tokens."""
    span = len(term_tokens)
    if not span or span > len(query_tokens):
        return False
    return any(
        tuple(query_tokens[start : start + span]) == term_tokens
        for start in range(len(query_tokens) - span + 1)
    )


def _expansion_terms(user_query: str) -> list[str]:
    query_tokens = [token.casefold() for token in TOKEN_PATTERN.findall(user_query)]
    added: list[str] = []
    seen: set[str] = set()
    for group, group_tokens in zip(SYNONYM_GROUPS, SYNONYM_GROUP_TOKENS, strict=True):
        present = [_contains_term(query_tokens, tokens) for tokens in group_tokens]
        if not any(present):
            continue
        for term, is_present in zip(group, present, strict=True):
            folded = term.casefold()
            if is_present or folded in seen:
                continue
            seen.add(folded)
            added.append(term)
            if len(added) >= MAX_EXPANSION_TERMS:
                return added
    return added


def build_expanded_fts_query(user_query: str) -> str:
    """Compile a query, then OR on deterministic alias terms.

    Expansion only ever adds quoted literals: original terms are never replaced
    or rewritten, and only whole-token hits against the alias map expand. Exact
    identifiers (commit ids, CVE ids, note ids, symbol names) therefore compile
    unchanged, preserving the precision BM25 is chosen for.
    """
    compiled = build_fts_query(user_query)
    added = _expansion_terms(user_query)
    if not added:
        return compiled
    return " OR ".join([compiled, *(_quote_term(term) for term in added)])


def _narrow_sensitivities(
    process_allowed: tuple[str, ...],
    max_sensitivity: str | None,
) -> tuple[str, ...]:
    """Intersect this process's clearance with an optional caller ceiling.

    The ceiling may only remove tiers. Clearance is server-owned, so a caller
    parameter must never be able to widen what this process can read.
    """
    if max_sensitivity is None:
        return process_allowed
    ceiling = SENSITIVITY_ORDER[: SENSITIVITY_ORDER.index(max_sensitivity) + 1]
    return tuple(value for value in process_allowed if value in ceiling)


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


def _validate_filters(
    filters: dict | None,
) -> tuple[dict[str, str], tuple[str, ...], str | None]:
    if filters is None:
        return {}, DEFAULT_STATUSES, None
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

    if "written_before" in filters:
        raw = filters["written_before"]
        if isinstance(raw, (int, float)):
            cutoff_ns = int(raw * 1_000_000_000) if raw < 10_000_000_000 else int(raw)
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            except ValueError as exc:
                raise RecallError(
                    "filter written_before must be an ISO-8601 timestamp or epoch seconds"
                ) from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            cutoff_ns = int(parsed.timestamp() * 1_000_000_000)
        else:
            raise RecallError(
                "filter written_before must be an ISO-8601 timestamp or epoch seconds"
            )
        structured["written_before_ns"] = cutoff_ns

    raw_statuses = filters.get("status", DEFAULT_STATUSES)
    if isinstance(raw_statuses, str):
        statuses = (raw_statuses,)
    elif isinstance(raw_statuses, (list, tuple)):
        statuses = tuple(raw_statuses)
    else:
        raise RecallError("filter status must be a string or list of strings")
    if any(not isinstance(value, str) or value not in ALL_STATUSES for value in statuses):
        raise RecallError(f"filter status must use {sorted(ALL_STATUSES)}")

    max_sensitivity = None
    if "max_sensitivity" in filters:
        max_sensitivity = filters["max_sensitivity"]
        # Rejected rather than ignored: silently dropping a typo would return
        # more than the caller asked for, which is the failure this prevents.
        if max_sensitivity not in SENSITIVITY_ORDER:
            raise RecallError(
                f"filter max_sensitivity must be one of {sorted(SENSITIVITY_ORDER)}"
            )
    return structured, tuple(dict.fromkeys(statuses)), max_sensitivity


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
    """Return ranked, quoted note snippets from the active FTS5 tier.

    The optional `max_sensitivity` filter narrows results to that tier and
    below (for example, recalling on behalf of an internal-tier destination).
    It intersects with this process's clearance and can never widen it.
    """
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
    fts_query = build_expanded_fts_query(query)
    validated_limit = _validate_limit(limit)
    structured, statuses, max_sensitivity = _validate_filters(filters)
    if not statuses:
        return _empty(recall_id)
    clearance = lane_clearance()
    process_allowed = (
        ("internal", "restricted")
        if clearance == "restricted"
        else ("internal",)
    )
    allowed_sensitivities = _narrow_sensitivities(process_allowed, max_sensitivity)
    if not allowed_sensitivities:
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
            f"m.sensitivity IN ({','.join('?' for _ in allowed_sensitivities)})",
        ]
        parameters: list[Any] = [
            fts_query,
            *statuses,
            *allowed_sensitivities,
        ]

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
        if "written_before_ns" in structured:
            clauses.append("m.mtime_ns < ?")
            parameters.append(structured["written_before_ns"])
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
            if not can_read(row["sensitivity"], clearance):
                continue
            if row["sensitivity"] not in allowed_sensitivities:
                continue
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
