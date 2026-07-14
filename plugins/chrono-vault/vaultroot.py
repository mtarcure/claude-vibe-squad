"""Fail-closed resolution for the private Chrono vault root."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class VaultRootError(RuntimeError):
    """The configured private vault root is missing or unsafe."""


def _realpath(path: os.PathLike[str] | str) -> Path:
    try:
        return Path(os.path.realpath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as exc:
        raise VaultRootError("vault root contains an invalid path") from exc


REPO_ROOT = _realpath(Path(__file__).parents[2])


def _git_common_dir(repo_root: Path) -> Path | None:
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        return _realpath(dot_git)
    if not dot_git.is_file():
        return None

    try:
        marker = dot_git.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise VaultRootError("cannot inspect repository worktree metadata") from exc
    prefix = "gitdir: "
    if not marker.startswith(prefix):
        raise VaultRootError("repository .git marker is invalid")

    git_dir = Path(marker[len(prefix):])
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    git_dir = _realpath(git_dir)

    common_marker = git_dir / "commondir"
    if common_marker.is_file():
        try:
            common = Path(common_marker.read_text(encoding="utf-8").strip())
        except OSError as exc:
            raise VaultRootError("cannot inspect shared worktree metadata") from exc
        if not common.is_absolute():
            common = git_dir / common
        return _realpath(common)
    return git_dir


def _discover_public_roots() -> list[Path]:
    roots = [REPO_ROOT]
    common_dir = _git_common_dir(REPO_ROOT)
    if common_dir is None:
        return roots

    if common_dir.name == ".git":
        roots.append(_realpath(common_dir.parent))

    worktrees_dir = common_dir / "worktrees"
    if worktrees_dir.is_dir():
        try:
            worktree_metadata = list(worktrees_dir.iterdir())
        except OSError as exc:
            raise VaultRootError("cannot enumerate repository worktrees") from exc
        for metadata_dir in worktree_metadata:
            gitdir_marker = metadata_dir / "gitdir"
            try:
                marker = gitdir_marker.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise VaultRootError("cannot inspect repository worktree") from exc
            if not marker:
                raise VaultRootError("repository worktree marker is empty")
            worktree_git_dir = Path(marker)
            if not worktree_git_dir.is_absolute():
                worktree_git_dir = metadata_dir / worktree_git_dir
            roots.append(_realpath(worktree_git_dir).parent)

    return list(dict.fromkeys(roots))


PUBLIC_ROOTS = _discover_public_roots()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((path, parent)) == os.fspath(parent)
    except ValueError:
        return False


def read_sentinel(root: Path) -> dict[str, Any]:
    """Read and validate ``<root>/.chrono-vault`` JSON metadata."""
    sentinel_path = _realpath(root) / ".chrono-vault"
    try:
        payload = json.loads(sentinel_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VaultRootError("vault root requires a readable .chrono-vault sentinel") from exc

    if not isinstance(payload, dict):
        raise VaultRootError(".chrono-vault sentinel must be a JSON object")

    vault_id = payload.get("vault_id")
    schema_version = payload.get("schema_version")
    if not isinstance(vault_id, str) or not vault_id.strip():
        raise VaultRootError(".chrono-vault sentinel requires a non-empty vault_id")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise VaultRootError(".chrono-vault sentinel requires a positive schema_version")

    return {"vault_id": vault_id, "schema_version": schema_version}


def resolve_vault_root() -> Path:
    """Return the canonical private vault root or fail without writing."""
    raw_root = os.environ.get("CHRONO_VAULT_ROOT")
    if not raw_root:
        raise VaultRootError("CHRONO_VAULT_ROOT must be set")
    if "${" in raw_root:
        raise VaultRootError("CHRONO_VAULT_ROOT contains an unresolved expression")
    if not os.path.isabs(raw_root):
        raise VaultRootError("CHRONO_VAULT_ROOT must be absolute")

    root = _realpath(raw_root)
    if not root.is_dir():
        raise VaultRootError("CHRONO_VAULT_ROOT must name an existing directory")

    for public_root in PUBLIC_ROOTS:
        canonical_public_root = _realpath(public_root)
        if _is_within(root, canonical_public_root):
            raise VaultRootError("CHRONO_VAULT_ROOT cannot be inside a public worktree")

    read_sentinel(root)
    return root
