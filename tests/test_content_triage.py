#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "content"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "content-triage-fixture.json"
        log = Path(td) / "content-triage-fixture.md"
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "python" / "content_triage.py"),
            "--date",
            "fixture",
            "--new-items",
            str(FIXTURES / "new-items.json"),
            "--feed-config",
            str(FIXTURES / "feed-config.yaml"),
            "--interests",
            str(FIXTURES / "operator-interests.yaml"),
            "--output",
            str(out),
            "--log",
            str(log),
            "--no-llm",
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            return result.returncode
        data = json.loads(out.read_text())

    items = data["items"]
    input_items = json.loads((FIXTURES / "new-items.json").read_text())
    require(data["schema_version"] == 1, "schema version changed")
    require(len(items) == len(input_items), "fixture item count changed")
    require(
        len({i["item_id"] for i in items}) == len(items),
        "content triage emitted duplicate item IDs",
    )
    require(
        all(i["tier"] in {"depth", "skim", "drop"} for i in items),
        "content triage emitted an unknown tier",
    )

    metere = next(i for i in items if "2605.00424" in i["feed_metadata"]["url"])
    require(metere["source_lane"] == "research", "research source lane changed")
    require(metere["tier"] == "depth", "high-value research item lost depth tier")
    require(metere["relevance_score"] >= 0.85, "research relevance score regressed")

    vendor_depth = [
        i for i in items
        if i["source_lane"] == "vendor-pr" and i["tier"] == "depth"
    ]
    require(len(vendor_depth) <= 2, "vendor depth quota exceeded")

    practitioner_depth = [
        i for i in items
        if i["source_lane"] == "practitioner" and i["tier"] == "depth"
    ]
    require(3 <= len(practitioner_depth) <= 5, "practitioner depth quota changed")

    pricing = next(i for i in items if i["feed_metadata"]["title"] == "New pricing plans for teams")
    require(pricing["tier"] in {"skim", "drop"}, "generic pricing item was over-promoted")

    print("content triage fixture regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
