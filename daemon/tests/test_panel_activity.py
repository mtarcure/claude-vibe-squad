from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time


def panel_command(tmp_path: Path, *args: str) -> tuple[dict, float]:
    repo = Path(__file__).resolve().parents[2]
    helper = repo / "bin" / "panel-activity.sh"
    env = os.environ.copy()
    env["PANEL_ACTIVITY_DIR"] = str(tmp_path / "activity")
    started = time.monotonic()
    completed = subprocess.run(
        [str(helper), *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )
    return json.loads(completed.stdout), time.monotonic() - started


def create_panel(tmp_path: Path, task_id: str = "TASK-panel-poll") -> None:
    panel_command(
        tmp_path,
        "create",
        "--task-id",
        task_id,
        "--lane",
        "gpt-codex",
        "--coordinator",
        "ai-engineer",
        "--members",
        "fast-member,slow-member",
    )
    for member in ("fast-member", "slow-member"):
        panel_command(
            tmp_path,
            "update",
            "--task-id",
            task_id,
            "--member",
            member,
            "--state",
            "running",
        )


def test_poll_returns_immediately_and_reports_numeric_quorum(tmp_path):
    task_id = "TASK-panel-quorum"
    create_panel(tmp_path, task_id)

    waiting, elapsed = panel_command(
        tmp_path,
        "poll",
        "--task-id",
        task_id,
        "--quorum",
        "1",
        "--timeout",
        "10",
    )
    assert elapsed < 0.75
    assert waiting["outcome"] == "waiting"
    assert waiting["done_count"] == 0
    assert waiting["terminal_count"] == 0
    assert waiting["required_count"] == 1
    assert waiting["pending"] == ["fast-member", "slow-member"]

    record = json.loads(
        (tmp_path / "activity" / f"{task_id}.json").read_text()
    )
    started = record["collection_started_monotonic"]
    deadline = record["deadline_monotonic"]
    assert deadline - started == 10

    panel_command(
        tmp_path,
        "update",
        "--task-id",
        task_id,
        "--member",
        "fast-member",
        "--state",
        "done",
    )
    met, elapsed = panel_command(
        tmp_path,
        "poll",
        "--task-id",
        task_id,
        "--quorum",
        "1",
        "--timeout",
        "10",
    )
    assert elapsed < 0.75
    assert met["outcome"] == "quorum_met"
    assert met["done_count"] == 1
    assert met["terminal_count"] == 2
    assert met["pending"] == []
    assert met["timed_out"] == ["slow-member"]

    record = json.loads(
        (tmp_path / "activity" / f"{task_id}.json").read_text()
    )
    states = {
        member["specialist"]: member["state"] for member in record["members"]
    }
    assert states == {"fast-member": "done", "slow-member": "timed_out"}
    assert record["collection_outcome"] == "quorum_met"


def test_poll_deadline_atomically_marks_unreturned_members_timed_out(tmp_path):
    task_id = "TASK-panel-timeout"
    create_panel(tmp_path, task_id)
    panel_command(
        tmp_path,
        "poll",
        "--task-id",
        task_id,
        "--quorum",
        "all",
        "--timeout",
        "1",
    )
    panel_command(
        tmp_path,
        "update",
        "--task-id",
        task_id,
        "--member",
        "fast-member",
        "--state",
        "done",
    )

    time.sleep(1.05)
    result, elapsed = panel_command(
        tmp_path,
        "poll",
        "--task-id",
        task_id,
        "--quorum",
        "all",
        "--timeout",
        "1",
    )
    assert elapsed < 0.75
    assert result["outcome"] == "timed_out"
    assert result["done_count"] == 1
    assert result["terminal_count"] == 2
    assert result["required_count"] == 2
    assert result["pending"] == []
    assert result["timed_out"] == ["slow-member"]

    record = json.loads(
        (tmp_path / "activity" / f"{task_id}.json").read_text()
    )
    states = {
        member["specialist"]: member["state"] for member in record["members"]
    }
    assert states == {"fast-member": "done", "slow-member": "timed_out"}
    assert record["collection_outcome"] == "timed_out"
