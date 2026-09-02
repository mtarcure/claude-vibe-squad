#!/usr/bin/env python3
"""Record a completed publish in the export ledger.

`projector._read_last_source_anchor` already honours publish records --
`{"event": "publish", "published_tip": ...}` -- so the continuity check will not
"silently ignore every publish since". Nothing wrote one. The ledger carried 32
projection records and no publish records, so every real push left the recorded
tip behind the live rail and the NEXT projection was refused with
`ledger/public mismatch`. The reader was built for a writer that did not exist.

This is that writer. It verifies before it records: the tip must actually be the
public rail's commit. A ledger entry that merely repeats what the operator typed
is a claim, and the whole point of this ledger is that it is a receipt.

Usage after a successful push:

    python3 tools/export/record_publish.py \\
        --published-tip "$(git rev-parse public/main)" \\
        --source-sha "$(git rev-parse HEAD)" \\
        --note "v1.1.5 publish"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LEDGER_PATH = "_state/public-export-2026-07-21/export-ledger.jsonl"
DEFAULT_PUBLIC_REF = "refs/remotes/public/main"


class PublishRecordError(RuntimeError):
    """The publish could not be recorded truthfully."""


def _resolve(root: Path, ref: str) -> str:
    try:
        done = subprocess.run(
            ("git", "-C", str(root), "rev-parse", "--verify", f"{ref}^{{commit}}"),
            check=False, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PublishRecordError(f"cannot resolve {ref}: {error}") from error
    if done.returncode:
        raise PublishRecordError(f"cannot resolve {ref}: {done.stderr.strip()}")
    return done.stdout.strip()


def record_publish(
    *,
    ledger_path: Path,
    root: Path,
    published_tip: str,
    public_ref: str = DEFAULT_PUBLIC_REF,
    source_sha: str,
    note: str,
) -> dict[str, object]:
    """Append a verified publish record. Raises unless the tip is really live."""
    live = _resolve(root, public_ref)
    if live != published_tip:
        raise PublishRecordError(
            f"refusing to record a publish that did not happen: "
            f"{public_ref}={live}, claimed={published_tip}"
        )
    record: dict[str, object] = {
        "event": "publish",
        "published_tip": published_tip,
        "public_ref": public_ref,
        "source_sha": source_sha,
        "note": note,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise PublishRecordError(
            f"cannot append export ledger {ledger_path}: {error}"
        ) from error
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--ledger")
    parser.add_argument("--published-tip", required=True)
    parser.add_argument("--public-ref", default=DEFAULT_PUBLIC_REF)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--note", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    ledger = Path(args.ledger) if args.ledger else root / DEFAULT_LEDGER_PATH
    try:
        record = record_publish(
            ledger_path=ledger, root=root, published_tip=args.published_tip,
            public_ref=args.public_ref, source_sha=args.source_sha, note=args.note,
        )
    except PublishRecordError as error:
        print(f"record-publish error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(record, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
