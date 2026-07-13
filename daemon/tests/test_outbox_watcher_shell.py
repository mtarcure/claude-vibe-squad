from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


HOST_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def host_python_without_yaml() -> str:
    host_python = shutil.which("python3", path=HOST_PATH)
    assert host_python is not None
    bare = subprocess.run(
        [host_python, "-c", "import yaml"],
        env={"PATH": HOST_PATH, "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert bare.returncode != 0
    assert "No module named 'yaml'" in bare.stderr
    return host_python


def minimal_watcher_env(tmp_path: Path, repo: Path, state_root: Path) -> dict[str, str]:
    tool_bin = tmp_path / "minimal-bin"
    tool_bin.mkdir()
    uv = shutil.which("uv")
    assert uv is not None
    (tool_bin / "uv").symlink_to(uv)
    fake_python = tool_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "echo \"FAKE_HOST_PYTHON: ModuleNotFoundError: No module named 'yaml'\" >&2\n"
        "exit 86\n"
    )
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "FAILOVER_CONTROL_ENABLED": "1",
            "PATH": f"{tool_bin}:/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
            "UV_PYTHON": sys.executable,
            "VAULT_ROOT": str(repo),
            "VIBESQUAD_CONTROL_STATE": str(state_root),
        }
    )
    return env


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

    host_python = host_python_without_yaml()
    host_env = {
        "PATH": HOST_PATH,
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

    watcher_env = minimal_watcher_env(tmp_path, repo, state_root)
    fake_host = subprocess.run(
        ["python3", "-c", "import yaml"],
        env=watcher_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert fake_host.returncode == 86
    assert "FAKE_HOST_PYTHON" in fake_host.stderr
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


def test_controller_runtime_oserror_is_critical_not_rejected(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    cli = repo / "bin" / "failover-control.py"
    watcher = repo / "bin" / "outbox-watcher.sh"
    state_root = tmp_path / "failover"
    blocked_parent = tmp_path / "canonical-parent-is-a-file"
    blocked_parent.write_text("not a directory")
    canonical = blocked_parent / "TASK-runtime-error-response.md"
    task_file = tmp_path / "inbox" / "TASK-runtime-error.md"
    task_file.parent.mkdir()
    task_file.write_text(
        "---\n"
        "id: TASK-runtime-error\n"
        "to_model: claude\n"
        "source_namespace: coding\n"
        f"return_artifact: {canonical}\n"
        "---\n\nForce a canonical write error.\n"
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
            "runtime-error-regression",
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
        "id: TASK-runtime-error-response\n"
        "in_response_to: TASK-runtime-error\n"
        "status: completed\n"
        "---\n\nValid response with an unwritable canonical destination.\n"
    )
    failed = subprocess.run(
        ["bash", str(watcher), "--publish-once", str(staging)],
        env=minimal_watcher_env(tmp_path, repo, state_root),
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 70
    assert "CRITICAL FAILOVER PUBLISH RUNTIME" in failed.stderr
    assert '"status": "error"' in failed.stderr
    assert "staging artifact rejected by controller" not in failed.stderr
    assert staging.exists()
    assert not canonical.exists()
