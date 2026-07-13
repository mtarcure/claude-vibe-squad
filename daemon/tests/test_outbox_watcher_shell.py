from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_outbox_watcher_missing_uv_is_a_distinct_runtime_alert(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    watcher = repo / "bin" / "outbox-watcher.sh"
    artifact = tmp_path / "attempt.md"
    artifact.write_text("---\nstatus: completed\n---\n")
    completed = subprocess.run(
        ["bash", str(watcher), "--publish-once", str(artifact)],
        env={
            "PATH": "/usr/bin:/bin",
            "VAULT_ROOT": str(repo),
            "SQUAD_SESSION": "missing-test-session",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 70
    assert "CRITICAL FAILOVER PUBLISH RUNTIME" in completed.stderr
    assert "uv is unavailable" in completed.stderr
    assert "rejected by controller" not in completed.stderr


def test_outbox_watcher_publish_uses_yaml_capable_uv_runtime(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    cli = repo / "bin" / "failover-control.py"
    watcher = repo / "bin" / "outbox-watcher.sh"

    host_python = shutil.which(
        "python3",
        path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    )
    assert host_python is not None
    host_env = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "PYTHONNOUSERSITE": "1",
    }
    bare = subprocess.run(
        [host_python, str(cli), "publish", "--help"],
        env=host_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bare.returncode != 0
    assert "No module named 'yaml'" in bare.stderr

    task_id = "TASK-shell-publish"
    state_root = tmp_path / "failover"
    canonical = tmp_path / "outbox" / f"{task_id}-response.md"
    task_file = tmp_path / "inbox" / f"{task_id}.md"
    task_file.parent.mkdir()
    task_file.write_text(
        "---\n"
        f"id: {task_id}\n"
        "to_model: claude\n"
        "source_namespace: coding\n"
        f"return_artifact: {canonical}\n"
        "---\n\nShell publish regression.\n"
    )
    initialized = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--state-root",
            str(state_root),
            "init-dispatch",
            "--task-file",
            str(task_file),
            "--primary-lane",
            "claude",
            "--backup-lane",
            "gpt-codex",
            "--lease-owner",
            "shell-regression",
            "--quiescence-seconds",
            "0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    attempt = json.loads(initialized.stdout)
    staging = Path(attempt["artifact_path"])
    staging.write_text(
        "---\n"
        f"id: {task_id}-response\n"
        f"in_response_to: {task_id}\n"
        "status: completed\n"
        "---\n\nPublished through the watcher shell path.\n"
    )

    watcher_env = os.environ.copy()
    watcher_env.update(
        {
            "FAILOVER_CONTROL_ENABLED": "1",
            "VAULT_ROOT": str(repo),
            "VIBESQUAD_CONTROL_STATE": str(state_root),
        }
    )
    published = subprocess.run(
        ["bash", str(watcher), "--publish-once", str(staging)],
        env=watcher_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "fenced staging artifact published" in published.stdout
    assert canonical.exists()
    assert "Published through the watcher shell path" in canonical.read_text()

    staging.write_text("---\nstatus:\n---\n")
    rejected = subprocess.run(
        ["bash", str(watcher), "--publish-once", str(staging)],
        env=watcher_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 2
    assert "staging artifact rejected by controller" in rejected.stderr
    assert "CRITICAL FAILOVER PUBLISH RUNTIME" not in rejected.stderr
