from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import prior_art_check


def _item(raw: str | None, path: str | None) -> dict[str, Any]:
    if raw and path:
        raise ValueError("use only one of --item-json or --item-file")
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    elif raw:
        payload = json.loads(raw)
    else:
        payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("item JSON must be an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a finding or composite chain against prior art."
    )
    parser.add_argument("target", help="Target program or project name")
    item_group = parser.add_mutually_exclusive_group()
    item_group.add_argument("--item-json", help="Finding/chain as a JSON object")
    item_group.add_argument("--item-file", help="Path to a finding/chain JSON file")
    args = parser.parse_args(argv)
    try:
        result = prior_art_check(
            args.target,
            _item(args.item_json, args.item_file),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"ok": True, "result": result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
