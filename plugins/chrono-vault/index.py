"""Disposable, rebuildable FTS5 index for canonical Chrono notes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from vaultroot import resolve_vault_root


NOTE_TYPES = frozenset({"attempt", "finding", "learning"})
STATUSES = frozenset(
    {"candidate", "verified", "superseded", "invalidated", "archived"}
)
SENSITIVITIES = frozenset({"internal", "restricted"})
FRONTMATTER_FIELDS = (
    "schema_version",
    "id",
    "title",
    "type",
    "status",
    "target",
    "program",
    "component",
    "attack_class",
    "sensitivity",
    "source_task",
    "source_artifact_hash",
    "created_at",
    "updated_at",
    "valid_from",
    "valid_to",
    "supersedes",
    "superseded_by",
    "aliases",
    "keywords",
    "evidence_refs",
    "revision",
)
INDEX_SCHEMA_VERSION = 2
FTS_COLUMNS = (
    "title",
    "body",
    "aliases",
    "target",
    "component",
    "attack_class",
    "keywords",
    "evidence_summary",
)
BM25_WEIGHTS = (8.0, 1.0, 6.0, 3.0, 2.0, 6.0, 3.0, 1.0)


class IndexError(RuntimeError):
    """The disposable index could not be updated safely."""


class MalformedNote(IndexError):
    """A source note cannot be represented in the canonical index."""


class IndexSchemaMismatch(IndexError):
    """The disposable index must be rebuilt for the current FTS schema."""


def _index_dir(root: Path, *, create: bool) -> Path:
    index_dir = root / "index"
    if create:
        try:
            index_dir.mkdir(mode=0o700)
        except FileExistsError:
            pass
    if index_dir.is_symlink():
        raise IndexError("index directory cannot be a symlink")
    if not index_dir.is_dir():
        raise IndexError("index directory is missing or inaccessible")
    if Path(os.path.realpath(index_dir)).parent != root:
        raise IndexError("index directory escapes the private vault")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise IndexError("secure index directory access is unavailable")
    try:
        directory_fd = os.open(index_dir, directory_flags | nofollow)
        try:
            os.fchmod(directory_fd, 0o700)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise IndexError("index directory is unsafe or inaccessible") from exc
    return index_dir


@contextmanager
def _locked(root: Path) -> Iterator[Path]:
    index_dir = _index_dir(root, create=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise IndexError("secure lock-file creation is unavailable")
    lock_fd = os.open(index_dir / ".kg.lock", flags | nofollow, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise IndexError("index lock must be a regular file")
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield index_dir
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            docid INTEGER PRIMARY KEY,
            id TEXT UNIQUE NOT NULL,
            path TEXT UNIQUE NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            note_type TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quarantine (
            path TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            error_code TEXT NOT NULL,
            error TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            title, body, aliases, target, component, attack_class,
            keywords, evidence_summary, tokenize='unicode61'
        )
        """
    )
    columns = tuple(
        row[1] for row in connection.execute("PRAGMA table_info(notes_fts)")
    )
    if columns != FTS_COLUMNS:
        raise IndexSchemaMismatch("index FTS schema is stale; rebuild required")
    connection.execute(
        "INSERT OR REPLACE INTO config(key, value) VALUES('bm25_weights', ?)",
        (json.dumps(BM25_WEIGHTS, separators=(",", ":")),),
    )
    connection.execute(
        "INSERT OR REPLACE INTO config(key, value) "
        "VALUES('index_schema_version', ?)",
        (str(INDEX_SCHEMA_VERSION),),
    )
    connection.execute(
        "INSERT OR IGNORE INTO state(key, value) VALUES('generation', '0')"
    )
    connection.execute(f"PRAGMA user_version={INDEX_SCHEMA_VERSION}")


def _schema_is_current(connection: sqlite3.Connection) -> bool:
    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        config_row = connection.execute(
            "SELECT value FROM config WHERE key='index_schema_version'"
        ).fetchone()
        config_version = int(config_row[0]) if config_row is not None else None
        columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(notes_fts)")
        )
    except (sqlite3.Error, TypeError, ValueError):
        return False
    return (
        user_version == INDEX_SCHEMA_VERSION
        and config_version == INDEX_SCHEMA_VERSION
        and columns == FTS_COLUMNS
    )


def _existing_schema_is_current(path: Path) -> bool | None:
    if not _prepare_database(path, create=False):
        return None
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        try:
            return _schema_is_current(connection)
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def _ensure_index_schema(root: Path) -> bool:
    """Atomically rebuild a present stale index; return whether rebuilt."""
    current = _existing_schema_is_current(root / "index" / "kg.db")
    if current is not False:
        return False
    rebuild_index()
    return True


def _prepare_database(path: Path, *, create: bool) -> bool:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise IndexError("secure database access is unavailable")
    flags = os.O_RDWR | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileNotFoundError:
        if not create:
            return False
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                descriptor = os.open(path, flags, 0o600)
            except OSError as exc:
                raise IndexError("index database is unsafe or inaccessible") from exc
        except OSError as exc:
            raise IndexError("index database is unsafe or inaccessible") from exc
    except OSError as exc:
        raise IndexError("index database is unsafe or inaccessible") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise IndexError("index database must be a regular file")
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    return True


def _connect(path: Path, *, wal: bool) -> sqlite3.Connection:
    _prepare_database(path, create=True)
    connection = sqlite3.connect(path, timeout=5.0)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(f"PRAGMA journal_mode={'WAL' if wal else 'DELETE'}")
        has_fts = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='notes_fts'"
        ).fetchone()
        if has_fts and not _schema_is_current(connection):
            raise IndexSchemaMismatch("index schema is stale; rebuild required")
        _initialize(connection)
        connection.commit()
        return connection
    except Exception:
        connection.close()
        raise


def _checkpoint(connection: sqlite3.Connection, label: str) -> None:
    result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if result is None or result[0] != 0 or result[1] != result[2]:
        raise IndexError(f"{label} WAL checkpoint did not complete: {result}")


def _remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        try:
            Path(f"{path}{suffix}").unlink()
        except FileNotFoundError:
            pass


def _generation(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM state WHERE key='generation'"
    ).fetchone()
    return int(row[0]) if row else 0


def _set_generation(connection: sqlite3.Connection, generation: int) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO state(key, value) VALUES('generation', ?)",
        (str(generation),),
    )


def _require_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise MalformedNote(f"{field} must be a non-empty string")
    return value


def _require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MalformedNote(f"{field} must be a list of strings")
    return value


def _parse_note(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise MalformedNote("note must be a regular non-symlink file")
    try:
        stat_before = path.stat()
        raw = path.read_bytes()
        stat_result = path.stat()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise MalformedNote("note is not readable UTF-8") from exc
    if (
        stat_before.st_size != stat_result.st_size
        or stat_before.st_mtime_ns != stat_result.st_mtime_ns
    ):
        raise MalformedNote("note changed while it was being read")

    if not text.startswith("---\n"):
        raise MalformedNote("note is missing opening frontmatter")
    closing = text.find("\n---\n", 4)
    if closing < 0:
        raise MalformedNote("note is missing closing frontmatter")

    frontmatter: dict[str, Any] = {}
    for line in text[4:closing].splitlines():
        key, separator, encoded = line.partition(": ")
        if not separator or key in frontmatter:
            raise MalformedNote("frontmatter contains an invalid or duplicate key")
        try:
            frontmatter[key] = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise MalformedNote(f"frontmatter value is invalid JSON: {key}") from exc

    expected = set(FRONTMATTER_FIELDS)
    if set(frontmatter) != expected:
        missing = sorted(expected - set(frontmatter))
        unknown = sorted(set(frontmatter) - expected)
        raise MalformedNote(f"frontmatter fields differ: missing={missing}, unknown={unknown}")

    body = text[closing + 5:]
    _require_string(body, "body")
    note_id = _require_string(frontmatter["id"], "id")
    if not re.fullmatch(r"mem-[0-9a-f]{12}", note_id):
        raise MalformedNote("id is not canonical")
    if path.stem != note_id:
        raise MalformedNote("id does not match filename")

    schema_version = frontmatter["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise MalformedNote("schema_version is invalid")
    revision = frontmatter["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise MalformedNote("revision is invalid")

    note_type = frontmatter["type"]
    if (
        not isinstance(note_type, str)
        or note_type not in NOTE_TYPES
        or path.parent.name != note_type
    ):
        raise MalformedNote("type does not match note directory")
    status = frontmatter["status"]
    if not isinstance(status, str) or status not in STATUSES:
        raise MalformedNote("status is invalid")
    sensitivity = frontmatter["sensitivity"]
    if not isinstance(sensitivity, str) or sensitivity not in SENSITIVITIES:
        raise MalformedNote("sensitivity is invalid")

    title = _require_string(frontmatter["title"], "title")
    if "\n" in title or "\r" in title:
        raise MalformedNote("title must be one line")
    target = _require_string(frontmatter["target"], "target")
    attack_class = _require_string(frontmatter["attack_class"], "attack_class")
    for field in ("created_at", "updated_at"):
        _require_string(frontmatter[field], field)
    for field in (
        "program",
        "component",
        "source_task",
        "source_artifact_hash",
        "valid_from",
        "superseded_by",
    ):
        if frontmatter[field] is not None:
            _require_string(frontmatter[field], field)
    if frontmatter["valid_to"] is not None:
        raise MalformedNote("valid_to must be null")
    aliases = _require_string_list(frontmatter["aliases"], "aliases")
    keywords = _require_string_list(frontmatter["keywords"], "keywords")
    _require_string_list(frontmatter["evidence_refs"], "evidence_refs")
    _require_string_list(frontmatter["supersedes"], "supersedes")
    component = frontmatter["component"]

    return {
        **frontmatter,
        "body": body,
        "path": str(path),
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "content_hash": hashlib.sha256(raw).hexdigest(),
        "aliases_text": "\n".join(aliases),
        "keywords_text": "\n".join(keywords),
        "evidence_summary": "",
        "component_text": component or "",
    }


def _delete_doc(connection: sqlite3.Connection, docid: int) -> None:
    connection.execute("DELETE FROM notes_fts WHERE rowid=?", (docid,))
    connection.execute("DELETE FROM meta WHERE docid=?", (docid,))


def _upsert_connection(connection: sqlite3.Connection, note: dict[str, Any]) -> None:
    by_id = connection.execute(
        "SELECT docid, path FROM meta WHERE id=?", (note["id"],)
    ).fetchone()
    by_path = connection.execute(
        "SELECT docid, id FROM meta WHERE path=?", (note["path"],)
    ).fetchone()
    if by_path and by_path[1] != note["id"]:
        raise IndexError("note path is already associated with a different id")

    if by_id:
        docid = int(by_id[0])
        connection.execute("DELETE FROM notes_fts WHERE rowid=?", (docid,))
        connection.execute(
            """
            UPDATE meta SET path=?, size=?, mtime_ns=?, content_hash=?, status=?,
                sensitivity=?, note_type=? WHERE docid=?
            """,
            (
                note["path"], note["size"], note["mtime_ns"], note["content_hash"],
                note["status"], note["sensitivity"], note["type"], docid,
            ),
        )
    else:
        cursor = connection.execute(
            """
            INSERT INTO meta(id, path, size, mtime_ns, content_hash, status,
                sensitivity, note_type) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                note["id"], note["path"], note["size"], note["mtime_ns"],
                note["content_hash"], note["status"], note["sensitivity"],
                note["type"],
            ),
        )
        docid = int(cursor.lastrowid)

    connection.execute(
        """
        INSERT INTO notes_fts(
            rowid, title, body, aliases, target, component, attack_class,
            keywords, evidence_summary
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            docid, note["title"], note["body"], note["aliases_text"],
            note["target"], note["component_text"], note["attack_class"],
            note["keywords_text"], note["evidence_summary"],
        ),
    )
    connection.execute("DELETE FROM quarantine WHERE path=?", (note["path"],))


def upsert(note: dict) -> None:
    """Insert or replace one complete source note under an exclusive lock."""
    path_value = note.get("path") if isinstance(note, dict) else None
    if not isinstance(path_value, str):
        raise IndexError("upsert requires note.path")
    root = resolve_vault_root()
    source_path = Path(path_value)
    if source_path.is_symlink():
        raise IndexError("note path cannot be a symlink")
    canonical_path = Path(os.path.realpath(source_path))
    try:
        canonical_path.relative_to(root / "notes")
    except ValueError as exc:
        raise IndexError("note path is outside the private notes directory") from exc
    parsed = _parse_note(canonical_path)

    if _ensure_index_schema(root):
        return

    with _locked(root) as index_dir:
        connection = _connect(index_dir / "kg.db", wal=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            _upsert_connection(connection, parsed)
            _set_generation(connection, _generation(connection) + 1)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _note_paths(root: Path) -> list[Path]:
    notes_root = root / "notes"
    if not notes_root.exists():
        return []
    if notes_root.is_symlink() or not notes_root.is_dir():
        raise IndexError("notes root is unsafe")
    paths: list[Path] = []
    for note_type in sorted(NOTE_TYPES):
        type_dir = notes_root / note_type
        if not type_dir.exists():
            continue
        if type_dir.is_symlink() or not type_dir.is_dir():
            raise IndexError(f"note type directory is unsafe: {note_type}")
        paths.extend(path for path in type_dir.iterdir() if path.suffix == ".md")
    return sorted(paths, key=lambda path: str(path))


def _quarantine(path: Path, error: Exception) -> dict[str, str]:
    try:
        content_hash = "" if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        content_hash = ""
    return {
        "path": str(path),
        "content_hash": content_hash,
        "error_code": type(error).__name__,
        "error": str(error),
    }


def _store_quarantine(connection: sqlite3.Connection, item: dict[str, str]) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO quarantine(path, content_hash, error_code, error)
        VALUES(?,?,?,?)
        """,
        (item["path"], item["content_hash"], item["error_code"], item["error"]),
    )


def sync_index() -> dict[str, Any]:
    """Synchronize changed source notes and quarantine malformed documents."""
    root = resolve_vault_root()
    _ensure_index_schema(root)
    with _locked(root) as index_dir:
        connection = _connect(index_dir / "kg.db", wal=True)
        indexed = 0
        unchanged = 0
        removed = 0
        quarantined: list[dict[str, str]] = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = {
                row[0]: (int(row[1]), int(row[2]), int(row[3]), row[4])
                for row in connection.execute(
                    "SELECT path, docid, size, mtime_ns, content_hash FROM meta"
                )
            }
            scanned: set[str] = set()
            for path in _note_paths(root):
                path_string = str(path)
                scanned.add(path_string)
                try:
                    parsed = _parse_note(path)
                except (MalformedNote, OSError) as exc:
                    prior = existing.get(path_string)
                    if prior:
                        _delete_doc(connection, prior[0])
                        removed += 1
                    item = _quarantine(path, exc)
                    _store_quarantine(connection, item)
                    quarantined.append(item)
                    continue

                prior = existing.get(path_string)
                signature = (parsed["size"], parsed["mtime_ns"], parsed["content_hash"])
                if prior and prior[1:] == signature:
                    unchanged += 1
                    connection.execute("DELETE FROM quarantine WHERE path=?", (path_string,))
                    continue
                _upsert_connection(connection, parsed)
                indexed += 1

            for path_string in existing:
                if path_string not in scanned:
                    current = connection.execute(
                        "SELECT docid FROM meta WHERE path=?", (path_string,)
                    ).fetchone()
                    if current:
                        _delete_doc(connection, int(current[0]))
                        removed += 1
                    connection.execute("DELETE FROM quarantine WHERE path=?", (path_string,))

            placeholders = ",".join("?" for _ in scanned)
            if scanned:
                connection.execute(
                    f"DELETE FROM quarantine WHERE path NOT IN ({placeholders})",
                    tuple(scanned),
                )
            else:
                connection.execute("DELETE FROM quarantine")

            if indexed or removed or quarantined:
                _set_generation(connection, _generation(connection) + 1)
            generation = _generation(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    return {
        "indexed": indexed,
        "unchanged": unchanged,
        "removed": removed,
        "quarantined": quarantined,
        "generation": generation,
    }


def _read_generation(path: Path) -> int:
    if not _prepare_database(path, create=False):
        return 0
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        try:
            return _generation(connection)
        finally:
            connection.close()
    except sqlite3.Error:
        return 0


def rebuild_index() -> dict[str, Any]:
    """Build a complete temp index, integrity-check it, and atomically publish."""
    root = resolve_vault_root()
    with _locked(root) as index_dir:
        db_path = index_dir / "kg.db"
        previous_generation = _read_generation(db_path)
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=".kg.db.", suffix=".tmp", dir=index_dir
        )
        os.close(temp_fd)
        os.chmod(temp_name, 0o600)
        temp_path = Path(temp_name)
        quarantined: list[dict[str, str]] = []
        indexed = 0
        connection: sqlite3.Connection | None = None
        try:
            connection = _connect(temp_path, wal=True)
            connection.execute("BEGIN IMMEDIATE")
            parsed_notes: list[dict[str, Any]] = []
            for path in _note_paths(root):
                try:
                    parsed_notes.append(_parse_note(path))
                except (MalformedNote, OSError) as exc:
                    item = _quarantine(path, exc)
                    _store_quarantine(connection, item)
                    quarantined.append(item)

            duplicate_ids = {
                note_id
                for note_id in {note["id"] for note in parsed_notes}
                if sum(note["id"] == note_id for note in parsed_notes) > 1
            }
            for note in parsed_notes:
                if note["id"] in duplicate_ids:
                    item = _quarantine(
                        Path(note["path"]), MalformedNote("duplicate note id")
                    )
                    _store_quarantine(connection, item)
                    quarantined.append(item)
                    continue
                _upsert_connection(connection, note)
                indexed += 1

            generation = previous_generation + 1
            _set_generation(connection, generation)
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise IndexError(f"rebuilt index failed integrity check: {integrity}")
            _checkpoint(connection, "rebuilt index")
            connection.close()
            connection = None
            _remove_sidecars(temp_path)

            with temp_path.open("rb") as handle:
                os.fsync(handle.fileno())

            if _prepare_database(db_path, create=False):
                old_connection = sqlite3.connect(db_path, timeout=5.0)
                try:
                    old_connection.execute("PRAGMA busy_timeout=5000")
                    _checkpoint(old_connection, "existing index")
                finally:
                    old_connection.close()
                _remove_sidecars(db_path)

            os.replace(temp_path, db_path)
            _prepare_database(db_path, create=False)
            verification = sqlite3.connect(db_path, timeout=5.0)
            try:
                journal_mode = verification.execute("PRAGMA journal_mode").fetchone()[0]
                if journal_mode.lower() != "wal":
                    raise IndexError("rebuilt index did not retain WAL mode")
                if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise IndexError("published index failed integrity check")
            finally:
                verification.close()
            with db_path.open("rb") as handle:
                os.fsync(handle.fileno())
            directory_fd = os.open(index_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if connection is not None:
                connection.close()
            _remove_sidecars(temp_path)
            if temp_path.exists():
                temp_path.unlink()

    return {
        "indexed": indexed,
        "quarantined": quarantined,
        "generation": generation,
    }


def index_generation() -> int:
    """Return the current disposable index generation, or zero if absent."""
    root = resolve_vault_root()
    return _read_generation(root / "index" / "kg.db")
