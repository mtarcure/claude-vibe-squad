from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def test_panel_rendering_uses_tmux_markup_and_allowlists_labels(tmp_path: Path):
    repo = Path(__file__).resolve().parents[2]
    poller = repo / "bin" / "vs-lane-status.sh"
    vault = tmp_path / "vault"
    activity = vault / "_state" / "runtime" / "lane-activity"
    status = tmp_path / "status"
    roster = vault / "model-lanes" / "ROSTER.md"
    tasks = tmp_path / "tasks.json"

    activity.mkdir(parents=True)
    roster.parent.mkdir(parents=True)
    roster.write_text(
        "\n".join(
            (
                "- `code-reviewer` (source: `coding`)",
                "- `test-engineer` (source: `coding`)",
                "- `security-analyst` (source: `security`)",
            )
        )
        + "\n"
    )
    tasks.write_text(json.dumps({"tasks": []}))
    (activity / "TASK-render.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dispatch_kind": "panel",
                "lane": "claude",
                "state": "running",
                "started_at_epoch": 1000,
                "updated_at_epoch": 1950,
                "stale_ttl_seconds": 300,
                "deadline_at_epoch": 2500,
                "members": [
                    {"specialist": "code-reviewer", "state": "running"},
                    {
                        "specialist": "intruder#[fg=colour1]\nlabel",
                        "state": "running",
                    },
                    {"specialist": "test-engineer", "state": "done"},
                    {"specialist": "security-analyst", "state": "timed_out"},
                ],
            }
        )
    )

    env = os.environ.copy()
    env.update(
        {
            "VAULT_ROOT": str(vault),
            "PANEL_ACTIVITY_DIR": str(activity),
            "VIBESQUAD_STATUS_DIR": str(status),
            "VS_DAEMON_TASKS_FILE": str(tasks),
            "VS_STATUS_NOW": "2000",
            "VS_STATUS_ONCE": "1",
        }
    )
    subprocess.run(
        ["bash", str(poller)],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )

    lane_status = (status / "vs-lane-claude.status").read_text()
    swarm_status = (status / "vs-swarm.status").read_text()

    assert lane_status == (
        "#[fg=colour74]⣯ #[fg=colour252]16:40"
        "#[fg=colour240] · panel[3]: "
        "#[fg=colour74]code-reviewer "
        "#[fg=colour240]test-engineer✓ "
        "#[fg=colour214]security-analyst#[default]"
    )
    assert swarm_status == (
        "#[fg=colour252]claude #[fg=colour74]⣯ "
        "#[fg=colour252]16:40 ×3#[default] "
        "#[fg=colour240]· #[fg=colour214]⚡SWARM ×3#[default]"
    )
    assert "intruder" not in lane_status
    assert "colour1" not in lane_status
    assert "label" not in lane_status
