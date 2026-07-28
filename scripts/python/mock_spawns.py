#!/usr/bin/env python3
"""Dev-only: create/clear MOCK board-dispatch spawns to demo the live dashboard.

A mock spawn writes a dispatch.json + context.json (authority lane/specialist +
a task title) backed by a real `sleep` process so its pid is alive and no receipt
exists — exactly the state the dashboard treats as an active spawn. `clear` kills
the sleeps and removes the mock files, so the board returns to idle with no history
residue (mocks never write a terminal receipt). Task ids are prefixed TASK-MOCK-.

  python3 scripts/python/mock_spawns.py create <n>
  python3 scripts/python/mock_spawns.py clear
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from repo_root import resolve_vault_root

VAULT = resolve_vault_root()
BOARD = VAULT / "_state" / "board-dispatch"
PREFIX = "TASK-MOCK-"

ROSTER = [
    ("gpt-codex", "systems-engineer", "Refactor board scheduler reservation path"),
    ("claude", "security-analyst", "Audit StarkGate bridge withdrawal proof"),
    ("gpt-codex", "technical-artist", "Regenerate the crew avatar set"),
    ("kimi", "summarizer", "Synthesize the 40-source competitive scan"),
    ("claude", "large-context-analyst", "Map the cross-module data-flow graph"),
    ("gpt-codex", "backend-engineer", "Wire the async ingestion pipeline"),
    ("claude", "scout", "Enumerate the target attack surface"),
    ("gpt-codex", "exploit-developer", "Weaponize the reentrancy finding"),
    ("gemini", "social-strategist", "Draft the launch announcement thread"),
    ("gpt-codex", "code-reviewer", "Adversarial review of the settle path"),
]


def create(n):
    BOARD.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        lane, specialist, summary = ROSTER[i % len(ROSTER)]
        task_id = f"{PREFIX}{i:02d}-{specialist}"
        attempt = f"d-mock{i:028d}"
        base = BOARD / f"{task_id}.{attempt}"
        proc = subprocess.Popen(["sleep", "3600"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        # stagger start times so the elapsed timers differ
        started = time.time() - (i * 37 + 5)
        (Path(str(base) + ".context.json")).write_text(json.dumps({
            "authority": {"lane": lane, "specialist": specialist, "task_id": task_id},
            "task_prompt": f"## Exact task packet\n\n# {summary}\n\nmock\n",
            "schema": "trusted-launch-context/v1",
        }), encoding="utf-8")
        (Path(str(base) + ".dispatch.json")).write_text(json.dumps({
            "task_id": task_id, "pid": proc.pid,
            "log_path": str(base) + ".log", "context_path": str(base) + ".context.json",
            "receipt_path": str(base) + ".receipt.json", "attempt_id": attempt,
            "generation": 1, "schema": "board-dispatch/v1",
        }), encoding="utf-8")
        os.utime(Path(str(base) + ".dispatch.json"), (started, started))
        print(f"  + {task_id}  (pid {proc.pid}, {lane}/{specialist})")


def clear():
    removed = 0
    for dispatch in BOARD.glob(f"{PREFIX}*.dispatch.json"):
        data = json.loads(dispatch.read_text(encoding="utf-8"))
        pid = data.get("pid")
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError, PermissionError):
                pass
        base = str(dispatch)[: -len(".dispatch.json")]
        for ext in (".dispatch.json", ".context.json", ".receipt.json", ".log"):
            Path(base + ext).unlink(missing_ok=True)
        removed += 1
    print(f"  cleared {removed} mock spawns")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "clear"
    if cmd == "create":
        create(int(sys.argv[2]) if len(sys.argv) > 2 else 2)
    else:
        clear()
