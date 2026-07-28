"""Canonical repo-root resolver for Python entry points.

The shell counterpart is ``shared/repo-root.sh``; both derive the repository
root from their own location so a clone works from any directory under any
username, and both honour the same ``VAULT_ROOT`` override.
"""

import os
from pathlib import Path

__all__ = ["resolve_vault_root"]


def resolve_vault_root() -> Path:
    """Return the repo root from the VAULT_ROOT env var or this file's location.

    An override is returned verbatim, never canonicalised: callers test whether
    a path is inside the vault by string prefix, and resolving would rewrite
    /var to /private/var on macOS and make every such comparison miss. An
    override that does not exist is a configuration error and raises, rather
    than silently falling back to a root the caller did not ask for.
    """
    override = os.environ.get("VAULT_ROOT")
    if override:
        root = Path(override)
        if not root.is_dir():
            raise FileNotFoundError(f"VAULT_ROOT is not a directory: {override}")
        return root
    # scripts/python/repo_root.py -> the repo root is two parents up.
    return Path(__file__).resolve().parents[2]
