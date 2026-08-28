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

import audit
from clearance import ClearanceError, can_read, lane_clearance, recall_constraints
import index as vault_index
from index import FTS_COLUMNS, INDEX_SCHEMA_VERSION
from query import TOKEN_PATTERN, build_fts_query
from vaultroot import VaultRootError, resolve_vault_root


ACTIVE_STATUSES = ("candidate", "verified")
FOLDED_STATUSES = ("superseded", "invalidated", "archived")
DEFAULT_STATUSES = ACTIVE_STATUSES
ALL_STATUSES = frozenset((*ACTIVE_STATUSES, *FOLDED_STATUSES))
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
        "source_task",
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


def _empty(
    recall_id: str,
    *,
    audit_result: str,
    query_error: str | None = None,
    tiers_searched: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "recall_id": recall_id,
        "tiers_searched": tiers_searched or ["active"],
        "results": [],
        "_audit_result": audit_result,
    }
    if query_error is not None:
        result["query_error"] = query_error
    return result


def _status_tiers(statuses: tuple[str, ...]) -> list[str]:
    """Name the lifecycle surfaces searched, without creating another tier.

    Candidate and verified notes form the default active surface. The existing
    terminal/replacement statuses are the recoverable folded surface: callers
    can search it explicitly with the same ``status`` filter they already use.
    """
    tiers: list[str] = []
    if any(status in ACTIVE_STATUSES for status in statuses):
        tiers.append("active")
    if any(status in FOLDED_STATUSES for status in statuses):
        tiers.append("folded")
    return tiers


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

    # Bookkeeping only: never a WHERE-clause column (see `column_filters`
    # below), just carried through to `_record_returns` so the notes a task
    # received are recorded against it. Under a bound engagement `_recall`
    # OVERRIDES whatever arrives here with the authenticated `task_id` and
    # refuses a mismatch, so this branch governs only the unbound
    # controller/maintenance case. Absent is valid there --
    # `_record_returns` writes NULL rather than requiring it -- but a
    # present-and-empty value is a caller bug, rejected like any other
    # structured filter.
    if "source_task" in filters:
        source_task = filters["source_task"]
        if not isinstance(source_task, str) or not source_task.strip():
            raise RecallError("filter source_task must be a non-empty string")
        structured["source_task"] = source_task

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
    # The per-column weight vector lives in the index config, authored from
    # `index.BM25_WEIGHTS`. Its magnitudes have no measured derivation -- see
    # the provenance note on `index.BM25_WEIGHTS` -- so treat them as a legacy
    # baseline, not tuned constants. What the vector IS load-bearing for is the
    # ordering "a query term in a label field (title/aliases/attack_class)
    # outranks the same term in prose (body)"; that ordinal intent is pinned,
    # with a baked-in flatten-the-vector negative control, by
    # tests/test_recall_weight_ordinality.py. Do not adjust the magnitudes
    # without the labeled relevance measurement that note describes.
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


# Ranking bonuses. bm25() returns NEGATIVE relevance ordered ASC, so a
# bonus is SUBTRACTED: a more-negative adjusted rank sorts earlier.
#
# Provenance: both values entered in commit ec87bb48 (2026-08-17). The commit
# establishes the qualitative reasons -- make promotion/type visible at equal
# lexical relevance -- but contains no measurement supporting either magnitude.
# Its "~9x" finding-frequency observation explains why type was considered, not
# why 0.25 is the right coefficient. Preserve the values as the legacy baseline;
# do not present them as tuned or validated constants.
_VERIFIED_BONUS = 0.5
_FINDING_BONUS = 0.25

# One neutral pseudo-observation for each scored outcome is Laplace smoothing,
# not a fitted parameter. It gives early feedback a bounded effect and makes
# repeated independent outcomes add diminishing evidence. The signal's maximum
# magnitude reuses (rather than exceeds) the two existing ranking nudges.
_USAGE_PRIOR_OBSERVATIONS = 2.0


def _rank_bonus_sql() -> str:
    """SQL expression subtracted from raw_rank to bias ordering."""
    return (
        f"- (CASE WHEN m.status = 'verified' THEN {_VERIFIED_BONUS} ELSE 0 END)"
        f" - (CASE WHEN m.note_type = 'finding' THEN {_FINDING_BONUS} ELSE 0 END)"
    )


def _usage_signal_sql() -> str:
    """Bounded support/demotion from recorded use and correctness outcomes.

    ``not_useful`` is intentionally reported but not scored: it describes fit
    for one recall context, not whether the reusable note is true. ``incorrect``
    is correctness evidence and ``used`` is positive applicability evidence.
    """
    used = "COALESCE(u.used_count, 0)"
    incorrect = "COALESCE(u.incorrect_count, 0)"
    signal_cap = _VERIFIED_BONUS + _FINDING_BONUS
    return (
        f"({signal_cap} * (({used}) - ({incorrect})) / "
        f"(({used}) + ({incorrect}) + {_USAGE_PRIOR_OBSERVATIONS}))"
    )


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


def _unreconciled_note_ids(audit_dir: Path | None = None) -> frozenset[str]:
    """Note ids left in an unreconciled contradiction, read from the audit trail.

    A write that contradicts an active note on the same subject and does not
    declare the relationship is recorded — never refused — as one ``contradiction``
    audit event with result ``flagged``, naming the contradicted notes in
    ``unreconciled_note_ids`` (see ``notes._emit_contradiction_event``). That event
    is the ONLY record that a stored note is disputed: the fact lives nowhere on
    the note or the index, which is why a reader receiving the note today cannot
    tell it is contested. This reads it back so ``recall`` can mark the note.

    The flagged events under ``<audit_dir>/contradiction/`` are the single source;
    ``chrono_state.resume`` counts the same set for the capsule. Best-effort by
    construction — an unresolved trail, or an unreadable or malformed event, yields
    no marks rather than breaking the recall it annotates, mirroring the never-gate
    rule the write path already follows. Cost is one directory scan per non-empty
    recall (O(events)); an index would be faster but is the machinery this fix
    deliberately does not build.
    """
    if audit_dir is None:
        audit_dir = audit.resolve_audit_dir()
    if audit_dir is None:
        return frozenset()
    try:
        events = list((audit_dir / "contradiction").glob("evt-*.json"))
    except OSError:
        return frozenset()
    disputed: set[str] = set()
    for event_path in events:
        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(event, dict) or event.get("result") != audit.CONTRA_FLAGGED:
            continue
        ids = event.get("unreconciled_note_ids")
        if isinstance(ids, list):
            disputed.update(note_id for note_id in ids if isinstance(note_id, str))
    return frozenset(disputed)


def _record_returns(
    root: Path,
    recall_id: str,
    note_ids: list[str],
    source_task: str | None,
) -> None:
    """Persist one `recall_returned` row per note this call handed back.

    Recording what recall HANDED the worker is what makes citation mechanical
    (protocol.md:445). Task 8's promotion handler reads this table directly;
    it never parses prose for `mem-...` IDs, because an unenforced markdown
    contract is exactly the failure this replaces -- `usage` sat empty for 23
    days under the same class of bug (see `lifecycle.record_usage`).

    `source_task` is likewise not a declaration. `_recall` derives it from the
    bound engagement, so the same reasoning applies one level down: a field
    the caller had to remember to send is a field that arrives NULL, and a
    NULL here is a promotion that never fires.

    Uses a dedicated write connection under the exclusive `.kg.lock`, the same
    pattern `lifecycle.record_usage` uses -- never the connection `_read_index`
    hands `_recall`, which is opened `mode=ro` with `PRAGMA query_only=ON` and
    cannot accept writes. Callers must invoke this only after releasing that
    read lock: both locks live on the same `.kg.lock` file, and this process
    taking the exclusive lock while it still holds the shared one would
    deadlock against itself.

    MEASURED, 2026-08-17, because ruling T7a accepted this as asserted-safe
    rather than measured-safe and carried the probe forward. Every non-empty
    recall now takes this exclusive lock, so recalls mutually exclude, and
    recall volume goes from 4 of 2,669 dispatches to nearly all of them.
    On a 2,000-note temp vault: this function holds the lock for 1.4ms p50 /
    2.1ms max, about 1% of a 231ms recall. Under 16 concurrent recalls on a
    300-note vault, p50 latency rises 12.8ms -> 300ms while throughput stays
    flat (~20ms/call wall), i.e. the calls serialize on the critical section
    rather than collapsing. The worst case is a concurrent `rebuild_index()`
    holding the same lock, which takes 264ms for 2,000 notes. Sub-second at
    the projected corpus; revisit if the vault grows by an order of
    magnitude, and note that `index._locked` is a blocking flock with no
    timeout, so the bound is the rebuild's duration and nothing else.
    """
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with vault_index._locked(root) as index_dir:
        connection = vault_index._connect(index_dir / "kg.db", wal=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "INSERT INTO recall_returned(recall_id, note_id, source_task, ts) "
                "VALUES (?, ?, ?, ?)",
                [(recall_id, note_id, source_task, timestamp) for note_id in note_ids],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def recall(query: str, filters: dict = None, limit: int = 8) -> dict[str, Any]:
    """Return ranked, quoted note snippets from the lifecycle-filtered FTS5 index.

    The optional `max_sensitivity` filter narrows results to that tier and
    below (for example, recalling on behalf of an internal-tier destination).
    It intersects with this process's clearance and can never widen it.

    Each returned note carries `disputed` (bool): True when the note is left in
    an unreconciled contradiction that a later write flagged but never reconciled
    (`_unreconciled_note_ids`), or when usage history contains an ``incorrect``
    outcome. The reader is thereby told a demoted note is contested instead of
    receiving it as if settled; scoring never removes the note from its lifecycle
    surface.

    Every call emits exactly one audit event (best-effort, never gating). The
    event's `result` distinguishes a recall that matched nothing from one that
    ran against an empty or broken store, and the absence of an event marks a
    recall that never ran. Behaviour on the return/raise path is unchanged: the
    internal `_audit_result` marker is stripped before the caller sees the dict,
    and every exception is re-raised exactly as before.
    """
    recall_id = str(uuid.uuid4())
    request_hash = audit.request_digest(
        "recall", {"query": query, "filters": filters, "limit": limit}
    )
    result_code = audit.ERROR
    returned_note_ids: list[str] = []
    try:
        response = _recall(query, recall_id, filters, limit)
        result_code = response.pop("_audit_result")
        returned_note_ids = [row["id"] for row in response["results"]]
        return response
    except ClearanceError:
        result_code = audit.DENIED
        raise
    except (RecallError, VaultRootError):
        result_code = audit.UNAVAILABLE
        raise
    finally:
        audit.emit(
            "recall",
            result=result_code,
            request_hash=request_hash,
            returned_note_ids=returned_note_ids,
            recall_id=recall_id,
        )


def _recall(
    query: str,
    recall_id: str,
    filters: dict = None,
    limit: int = 8,
) -> dict[str, Any]:
    constraints = recall_constraints()
    if not isinstance(query, str):
        raise RecallError("query must be a string")
    if not query.strip() or "\x00" in query or len(query) > MAX_QUERY_CHARS:
        return _empty(
            recall_id, audit_result=audit.QUERY_ERROR, query_error="invalid_fts_query"
        )
    if (
        _has_unknown_column_selector(query)
        or query.strip() == "*"
        or query.count('"') % 2
    ):
        return _empty(
            recall_id, audit_result=audit.QUERY_ERROR, query_error="invalid_fts_query"
        )
    fts_query = build_expanded_fts_query(query)
    validated_limit = _validate_limit(limit)
    structured, statuses, max_sensitivity = _validate_filters(filters)
    tiers_searched = _status_tiers(statuses)
    if constraints is not None:
        # DERIVED, never taken on the caller's word, for the same reason
        # `lifecycle.record_usage` derives it: the launch prompt
        # `dispatch_context_builder` gives every worker says "Pass no
        # filters", and the MCP `recall` tool does not even expose this
        # field, so a caller-DECLARED key is NULL on every production
        # recall. Any query joining on it therefore matches nothing --
        # which is how promotion came to be structurally dead, with 0
        # `recall_returned` rows and 0 `verified_at_ns` stamps on the live
        # vault. (Promotion itself has since moved to `usage.source_task`,
        # which the vault derives the same way; this column is now the
        # provenance record of what recall returned, not the promotion key.
        # It is derived here regardless, because a NULL-by-construction
        # column is a broken record either way.) An unbound
        # controller/maintenance process has no engagement to derive from,
        # and keeps the declared value (usually absent, hence NULL).
        declared = structured.get("source_task")
        if declared not in {None, constraints["task_id"]}:
            raise RecallError("filter source_task does not match the engagement")
        structured["source_task"] = constraints["task_id"]
        allowed_statuses = constraints["statuses"]
        statuses = tuple(value for value in statuses if value in allowed_statuses)
        allowed_types = constraints["note_types"]
        if structured.get("type") not in {None, *allowed_types}:
            return _empty(
                recall_id,
                audit_result=audit.FILTERED,
                tiers_searched=tiers_searched,
            )
        focus = constraints["target"]
        if focus is not None:
            if structured.get("target") not in {None, focus}:
                return _empty(
                    recall_id,
                    audit_result=audit.FILTERED,
                    tiers_searched=tiers_searched,
                )
            structured["target"] = focus
        cutoff = constraints["written_before_ns"]
        if cutoff is not None:
            structured["written_before_ns"] = min(
                cutoff,
                int(structured.get("written_before_ns", cutoff)),
            )
    if not statuses:
        return _empty(
            recall_id,
            audit_result=audit.FILTERED,
            tiers_searched=tiers_searched,
        )
    clearance = lane_clearance()
    process_allowed = (
        ("internal", "restricted")
        if clearance == "restricted"
        else ("internal",)
    )
    allowed_sensitivities = _narrow_sensitivities(process_allowed, max_sensitivity)
    if not allowed_sensitivities:
        return _empty(
            recall_id,
            audit_result=audit.FILTERED,
            tiers_searched=tiers_searched,
        )

    root = resolve_vault_root()
    with _read_index(root) as connection:
        if connection is None:
            return _empty(
                recall_id,
                audit_result=audit.EMPTY_STORE,
                tiers_searched=tiers_searched,
            )

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
        if constraints is not None and set(constraints["note_types"]) != NOTE_TYPES:
            allowed_types = constraints["note_types"]
            clauses.append(
                f"m.note_type IN ({','.join('?' for _ in allowed_types)})"
            )
            parameters.extend(allowed_types)

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
            clauses.append("m.created_at_ns < ?")
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
                m.mtime_ns, m.note_type, notes_fts.title, notes_fts.body,
                bm25(notes_fts, {weight_sql}) AS lexical_rank,
                COALESCE(u.used_count, 0) AS used_count,
                COALESCE(u.not_useful_count, 0) AS not_useful_count,
                COALESCE(u.incorrect_count, 0) AS incorrect_count,
                {_usage_signal_sql()} AS usage_signal,
                bm25(notes_fts, {weight_sql}) {_rank_bonus_sql()}
                    - {_usage_signal_sql()} AS raw_rank
            FROM notes_fts
            JOIN meta AS m ON m.docid = notes_fts.rowid
            LEFT JOIN (
                SELECT
                    note_id,
                    SUM(CASE WHEN outcome = 'used' THEN 1 ELSE 0 END)
                        AS used_count,
                    SUM(CASE WHEN outcome = 'not_useful' THEN 1 ELSE 0 END)
                        AS not_useful_count,
                    SUM(CASE WHEN outcome = 'incorrect' THEN 1 ELSE 0 END)
                        AS incorrect_count
                FROM usage
                GROUP BY note_id
            ) AS u ON u.note_id = m.id
            WHERE {' AND '.join(clauses)}
            ORDER BY raw_rank ASC, m.mtime_ns DESC, m.id ASC
            LIMIT ?
        """
        try:
            rows = list(connection.execute(sql, parameters))
        except sqlite3.OperationalError as exc:
            if _is_fts_syntax_error(exc):
                return _empty(
                    recall_id,
                    audit_result=audit.QUERY_ERROR,
                    query_error="invalid_fts_query",
                )
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
            lexical_rank = float(row["lexical_rank"])
            adjusted_rank = float(row["raw_rank"])
            score = -adjusted_rank
            verified_bonus = _VERIFIED_BONUS if row["status"] == "verified" else 0.0
            finding_bonus = _FINDING_BONUS if row["note_type"] == "finding" else 0.0
            usage = {
                "used": int(row["used_count"]),
                "not_useful": int(row["not_useful_count"]),
                "incorrect": int(row["incorrect_count"]),
                "signal": float(row["usage_signal"]),
            }
            results.append(
                {
                    "id": row["id"],
                    "score": score,
                    "score_components": {
                        "bm25": -lexical_rank,
                        "raw_bm25": lexical_rank,
                        "verified_bonus": verified_bonus,
                        "finding_bonus": finding_bonus,
                        "usage": usage,
                        "adjusted_score": score,
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

    # P13.66 — surface the write-time contradiction the audit trail already
    # recorded. A note left in an unreconciled contradiction is disputed, and the
    # reader must be told so on the note itself. One scan, only when there is
    # something to mark; `disputed` is present on every returned note (False on a
    # clean one) so a consumer can rely on the key.
    disputed_ids = _unreconciled_note_ids() if results else frozenset()
    for row in results:
        row["disputed"] = (
            row["id"] in disputed_ids
            or row["score_components"]["usage"]["incorrect"] > 0
        )

    # Skipped when nothing was returned: an empty recall must never create
    # index storage (test_missing_index_returns_empty_without_creating_storage
    # depends on that), and there is nothing to cite anyway.
    if results:
        try:
            _record_returns(
                root,
                recall_id,
                [row["id"] for row in results],
                structured.get("source_task"),
            )
        except (sqlite3.Error, vault_index.IndexError) as exc:
            raise RecallError("failed to record recall_returned rows") from exc

    return {
        "recall_id": recall_id,
        "tiers_searched": tiers_searched,
        "results": results,
        "_audit_result": audit.MATCHED if results else audit.NO_MATCH,
    }
