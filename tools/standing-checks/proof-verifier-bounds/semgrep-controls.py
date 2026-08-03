#!/usr/bin/env python3
"""Positive-control the auxiliary Solidity Semgrep evidence rules."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


RULES = {
    "I1": "proof-verifier-i1-strict-index-bounds-signal",
    "I2": "proof-verifier-i2-leaf-consumption-signal",
    "I3": "proof-verifier-i3-strict-order-signal",
    "I4": "proof-verifier-i4-proof-consumption-signal",
    "I5": "proof-verifier-i5-indexed-leaf-commitment-signal",
}

SLUGS = {
    "I1": "strict_index_bounds",
    "I2": "exhaustive_leaf_consumption",
    "I3": "strict_order_and_uniqueness",
    "I4": "total_proof_consumption",
    "I5": "positional_binding",
}


def main() -> int:
    root = Path(__file__).resolve().parent
    semgrep = shutil.which("semgrep")
    if semgrep is None:
        print("SEMGREP_CONTROL_ERROR executable not found")
        return 2

    temp = Path(tempfile.mkdtemp(prefix="proof-verifier-semgrep.", dir="/private/tmp"))
    result_path = temp / "result.json"
    command = [
        semgrep,
        "scan",
        "--quiet",
        "--disable-version-check",
        "--metrics=off",
        "--config",
        str(root / "semgrep-solidity.yml"),
        "--json-output",
        str(result_path),
        str(root / "fixtures" / "solidity"),
    ]
    env = os.environ.copy()
    env.update(
        {
            "SEMGREP_LOG_FILE": str(temp / "semgrep.log"),
            "SEMGREP_SETTINGS_FILE": str(temp / "settings.yml"),
            "SEMGREP_VERSION_CACHE_PATH": str(temp / "version"),
        }
    )

    print("COMMAND " + " ".join(command))
    completed = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    print(f"EXIT {completed.returncode}")
    if completed.returncode != 0 or not result_path.is_file():
        if completed.stdout:
            print(completed.stdout.rstrip())
        if completed.stderr:
            print(completed.stderr.rstrip())
        print("SEMGREP_CONTROL_ERROR scan failed")
        return 1

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    print(
        f"SEMGREP_SCAN_SUMMARY findings={len(payload.get('results', []))} "
        f"errors={len(payload.get('errors', []))}"
    )
    hits = {
        (Path(item["path"]).name, item["check_id"].rsplit(".", 1)[-1])
        for item in payload.get("results", [])
    }
    failures = 0
    for invariant, rule in RULES.items():
        fixed = f"{SLUGS[invariant]}_fixed.sol"
        vulnerable = f"{SLUGS[invariant]}_vulnerable.sol"
        fixed_has = (fixed, rule) in hits
        vulnerable_has = (vulnerable, rule) in hits
        passed = fixed_has and not vulnerable_has
        if not passed:
            failures += 1
        print(
            f"SEMGREP_CONTROL {invariant} fixed_signal={str(fixed_has).lower()} "
            f"vulnerable_signal={str(vulnerable_has).lower()} {'PASS' if passed else 'FAIL'}"
        )
    print(f"SEMGREP_CONTROL_SUMMARY total=5 passed={5 - failures} failed={failures}")
    print(f"SEMGREP_ARTIFACTS {temp}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
