#!/usr/bin/env python3
"""JSON bridge to the real chrono-vault FTS5/BM25 recall implementation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True))


def main() -> int:
    if not os.environ.get("CHRONO_VAULT_ROOT"):
        _emit({"status": "recall_unavailable", "reason": "vault_root_unset"})
        return 0
    if not os.environ.get("CHRONO_VAULT_CLEARANCE"):
        _emit({"status": "recall_unavailable", "reason": "vault_clearance_unset"})
        return 0

    request = json.load(sys.stdin)
    plugin_dir = Path(__file__).resolve().parents[2] / "plugins" / "chrono-vault"
    sys.path.insert(0, str(plugin_dir))

    try:
        from recall import recall

        result = recall(
            request["query"],
            filters=request.get("filters"),
            limit=request.get("limit", 8),
        )
    except Exception as error:  # The Node caller must receive an explicit state.
        _emit(
            {
                "status": "recall_unavailable",
                "reason": "recall_error",
                "error_type": type(error).__name__,
            }
        )
        return 0

    _emit({"status": "ok", "recall": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
