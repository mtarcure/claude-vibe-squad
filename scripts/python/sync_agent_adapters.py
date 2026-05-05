#!/usr/bin/env python3
"""Generate model-lane native agent adapters from the specialist runtime map."""

from __future__ import annotations

import csv
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_MAP = ROOT / "shared" / "specialist-runtime-map.tsv"


LANE_DIRS = {
    "gpt-codex": ROOT / "model-lanes" / "gpt-codex" / ".codex" / "agents",
    "claude": ROOT / "model-lanes" / "claude" / ".claude" / "agents",
    "gemini": ROOT / "model-lanes" / "gemini" / ".gemini" / "agents",
    "kimi": ROOT / "model-lanes" / "kimi",
}


def read_rows() -> list[dict[str, str]]:
    with RUNTIME_MAP.open(newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        rows: list[dict[str, str]] = []
        for raw in reader:
            if not raw or raw[0].startswith("#"):
                continue
            if len(raw) < 7:
                raise SystemExit(f"Malformed runtime-map row: {raw!r}")
            specialist, model, review, namespace, tools, safety, notes = raw[:7]
            rows.append(
                {
                    "specialist": specialist,
                    "model": model,
                    "review": review,
                    "namespace": namespace,
                    "tools": tools,
                    "safety": safety,
                    "notes": notes,
                }
            )
        return rows


def specialist_path(name: str, namespace: str) -> Path:
    if namespace == "shared":
        path = ROOT / "shared" / "specialists" / f"{name}.md"
    else:
        path = ROOT / "departments" / namespace / "specialists" / f"{name}.md"
    if not path.exists():
        raise SystemExit(f"Missing specialist markdown for {name}: {path}")
    return path


def title_from_markdown(path: Path, fallback: str) -> str:
    for line in path.read_text().splitlines():
        if line.startswith("# Specialist:"):
            return line.removeprefix("# Specialist:").strip()
    return fallback.replace("-", " ").title()


def description(row: dict[str, str]) -> str:
    desc = row["notes"].strip()
    desc = re.sub(r"\s+", " ", desc)
    return desc.replace('"', '\\"')


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def common_instructions(row: dict[str, str], canonical: Path) -> str:
    name = row["specialist"]
    kimi_mcp_note = ""
    if row["model"] == "kimi":
        kimi_mcp_note = "\n\nKimi MCP note: current Kimi CLI behavior exposes MCP tools to the main Kimi lane, not inside `Agent(...)` subagents. If the task requires an MCP call such as `arxiv_search`, `xai_search`, vault tools, content tools, or sequential thinking, perform that MCP call in the main Kimi lane and report `subagent_mcp_gap` instead of retrying the subagent path."
    return f"""You are the `{name}` specialist running inside the `{row['model']}` model lane.

Canonical specialist instructions live at `{rel(canonical)}`. Read that file at task start and follow it over this adapter.

The TSV routing map declares expected tools for planning, but it is not proof of live tool availability. Verify tools/MCPs in your current runtime before relying on them. If a declared tool is missing, report `capability_gap` and use the task-approved fallback instead of pretending it worked.

Execute the task packet assigned by Chrono. Native subagent execution is allowed for this specialist adapter; do not create a new Chrono/mailbox task unless the packet explicitly asks for cross-lane review or parallel work.{kimi_mcp_note}

Stay inside the packet's write scope. Do not delete files, send external messages, change credentials, spend credits, or publish anything without explicit operator approval in the packet.
"""


def clean_dir(path: Path, suffixes: tuple[str, ...]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_file() and child.suffix in suffixes:
            child.unlink()


def write_codex(rows: list[dict[str, str]]) -> None:
    out = LANE_DIRS["gpt-codex"]
    clean_dir(out, (".toml",))
    (out / "README.md").write_text(
        "# GPT/Codex Agent Adapters\n\n"
        "Generated from `shared/specialist-runtime-map.tsv`. Do not edit these by hand; "
        "edit canonical specialist markdown and rerun `python3 scripts/python/sync_agent_adapters.py`.\n"
    )
    for row in rows:
        if row["model"] != "gpt-codex":
            continue
        name = row["specialist"]
        canonical = specialist_path(name, row["namespace"])
        agent_name = name.replace("-", "_")
        body = common_instructions(row, canonical).replace('"""', '\\"\\"\\"')
        effort = "high" if row["safety"] == "high" else "medium"
        (out / f"{name}.toml").write_text(
            f'name = "{agent_name}"\n'
            f'description = "{description(row)}"\n'
            f'model_reasoning_effort = "{effort}"\n'
            'sandbox_mode = "workspace-write"\n'
            'developer_instructions = """\n'
            f"{body}"
            '"""\n'
        )


def write_claude(rows: list[dict[str, str]]) -> None:
    out = LANE_DIRS["claude"]
    clean_dir(out, (".md",))
    (out / "README.md").write_text(
        "# Claude Agent Adapters\n\n"
        "Generated from `shared/specialist-runtime-map.tsv`. Each adapter points back to canonical markdown.\n"
    )
    for row in rows:
        if row["model"] != "claude":
            continue
        name = row["specialist"]
        canonical = specialist_path(name, row["namespace"])
        title = title_from_markdown(canonical, name)
        (out / f"{name}.md").write_text(
            "---\n"
            f"name: {name}\n"
            f'description: "{description(row)}"\n'
            "model: inherit\n"
            "---\n\n"
            f"# Specialist Adapter: {title}\n\n"
            f"{common_instructions(row, canonical)}"
        )


def write_gemini(rows: list[dict[str, str]]) -> None:
    out = LANE_DIRS["gemini"]
    clean_dir(out, (".md",))
    root_gemini_agents = ROOT / ".gemini" / "agents"
    if root_gemini_agents.exists():
        shutil.rmtree(root_gemini_agents)
    for row in rows:
        if row["model"] != "gemini":
            continue
        name = row["specialist"]
        canonical = specialist_path(name, row["namespace"])
        title = title_from_markdown(canonical, name)
        (out / f"{name}.md").write_text(
            "---\n"
            f"name: {name}\n"
            f'description: "{description(row)}"\n'
            "kind: local\n"
            'tools: ["read_file", "replace", "write_file", "run_shell_command", "glob", "grep_search"]\n'
            "model: inherit\n"
            "max_turns: 30\n"
            "---\n\n"
            f"# Specialist Adapter: {title}\n\n"
            f"{common_instructions(row, canonical)}"
        )


def write_kimi(rows: list[dict[str, str]]) -> None:
    lane = LANE_DIRS["kimi"]
    subagents = lane / "subagents"
    prompts = lane / "prompts"
    clean_dir(subagents, (".yaml", ".yml"))
    clean_dir(prompts, (".md",))

    kimi_rows = [row for row in rows if row["model"] == "kimi"]
    subagent_lines = []
    for row in kimi_rows:
        name = row["specialist"]
        canonical = specialist_path(name, row["namespace"])
        title = title_from_markdown(canonical, name)
        prompt_path = prompts / f"{name}.md"
        prompt_path.write_text(f"# Specialist Adapter: {title}\n\n{common_instructions(row, canonical)}")
        (subagents / f"{name}.yaml").write_text(
            "version: 1\n"
            "agent:\n"
            f"  name: {name}\n"
            "  extend: default\n"
            f"  system_prompt_path: ../prompts/{name}.md\n"
        )
        subagent_lines.append(
            f"    {name}:\n"
            f"      path: ./subagents/{name}.yaml\n"
            f"      description: \"{description(row)}\"\n"
        )

    main = (
        "version: 1\n"
        "agent:\n"
        "  name: kimi-model-lead\n"
        "  extend: default\n"
        "  system_prompt_path: ./KIMI.md\n"
        "  subagents:\n"
        + "".join(subagent_lines)
    )
    (lane / "main.yaml").write_text(main)


def main() -> None:
    rows = read_rows()
    write_codex(rows)
    write_claude(rows)
    write_gemini(rows)
    write_kimi(rows)


if __name__ == "__main__":
    main()
