#!/usr/bin/env python3
"""Mailbox reconciliation backstop for the live board rail."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", REPO_ROOT)).resolve()


def reconcile_once() -> dict[str, object]:
    timeout = float(os.environ.get("SQUAD_RECONCILE_SWEEP_TIMEOUT_SECONDS", "30"))
    command = [str(VAULT_ROOT / "bin/registry-reconciler.sh")]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"ok": result.returncode == 0, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "timeout": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("reconcile-sweep",))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            print(json.dumps(reconcile_once(), sort_keys=True), flush=True)
        except (OSError, RuntimeError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr, flush=True)
            if args.once:
                return 2
        if args.once:
            return 0
        interval = int(os.environ.get("SQUAD_RECONCILE_SWEEP_SECONDS", "60"))
        time.sleep(max(1, interval))


if __name__ == "__main__":
    raise SystemExit(main())
