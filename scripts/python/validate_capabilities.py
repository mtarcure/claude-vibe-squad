#!/usr/bin/env python3
"""Validate capability cards against the locked schema and runtime registries."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REQUIRED_FRONTMATTER = (
    "id",
    "mode",
    "title",
    "capability_state",
    "state_reason",
    "state_evidence",
    "overlays",
    "gates",
    "cost_note",
)
MODES = {
    "project",
    "bounty",
    "content",
    "outreach",
    "research",
    "incident",
    "maintenance",
    "triage",
}
# A5 mode consolidation (10 modes → project + bounty): the content / outreach /
# research / maintenance domain modes were folded into `project` as capabilities
# (grouped by the `profile_family` frontmatter field) and their cards moved into
# `shared/capabilities/project/`. This map keeps every retired domain-mode
# capability id resolving to its canonical project id so old packets, cards, and
# links still dispatch. Stage-1 is resolve-only: gates are re-anchored onto each
# card before the move, so a resolved id carries identical gates/overlays — the
# resolution canonicalizes the home, it never changes a capability's meaning.
#
# An alias is only valid while its target card exists — `test_capability_alias_
# resolution.py` pins that. The 2026-08-14 (P13.64) roster consolidation retired
# the study-coaching and personal-operations roles and their capability cards, so
# `research/learning-study` and `maintenance/personal-operations` were dropped
# from this map rather than left pointing at deleted files. Those two legacy ids
# now fail resolution, which is the intended signal that the capability is gone.
CAPABILITY_ALIASES = {
    "content/audio-assets": "project/audio-assets",
    "content/editorial-longform": "project/editorial-longform",
    "content/image": "project/image",
    "content/marketing-campaign": "project/marketing-campaign",
    "content/search-discoverability": "project/search-discoverability",
    "content/video": "project/video",
    "research/data-extraction-dataset": "project/data-extraction-dataset",
    "research/investigation-synthesis": "project/investigation-synthesis",
    "outreach/prospecting-outreach": "project/prospecting-outreach",
    "maintenance/dependency-release-integrity": "project/dependency-release-integrity",
    "maintenance/environment-repo-health": "project/environment-repo-health",
    "maintenance/harness-audit-compatibility": "project/harness-audit-compatibility",
    "maintenance/memory-vault-hygiene": "project/memory-vault-hygiene",
}
CAPABILITY_STATES = {"live", "lane-gated", "degraded-blueprint", "needs_tool"}
LANES = {"claude", "codex", "gemini", "kimi", "all", "local", "none", "unknown"}
TOOL_STATES = {
    "yes",
    "lane-live",
    "partial",
    "needs-research",
    "catalog-absent",
    "needs_tool",
    "no",
}
COSTS = {"subscription", "metered", "unknown", "—"}
SENTINELS = {"Chrono", "operator", "cross-family-reviewer"}
LIVE_TOOL_STATES = {"yes", "lane-live"}
UNAVAILABLE_TOOL_STATES = {"catalog-absent", "needs_tool", "no"}
DEGRADED_TOOL_STATES = {"partial", "needs-research"}
PERPLEXITY_STRUCTURED_TOOL = "Perplexity Sonar structured+recency"
HIGGSFIELD_RAW_GENERATION_METHODS = {"generate_audio", "generate_image", "generate_video"}
HIGGSFIELD_FREE_READ_HINTS = {
    "balance",
    "list",
    "models_explore",
    "show",
    "show_plans",
    "status",
    "transactions",
}
EXTERNAL_BUDGET_RE = re.compile(
    r"\bexternal-budget-ceiling=(?:[$€£]\d+(?:\.\d+)?|"
    r"\d+(?:\.\d+)?(?:usd|eur|gbp|credits?|tokens?|requests?|calls?|provider-units?))\b",
    re.IGNORECASE,
)
FRONTMATTER_EXTERNAL_BUDGET_RE = re.compile(
    r"^external:max_(?:usd|eur|gbp|credits?|tokens?|requests?|calls?|provider_units?)="
    r"\d+(?:\.\d+)?$",
    re.IGNORECASE,
)
SKILL_LABELS = {
    "invokable": "SKILL.md",
    "authored-pattern-doc": "authored",
    "pattern-doc-stub": "stub",
    "pattern-doc-untyped": "untyped",
}
TOOL_TUPLE_RE = re.compile(
    r"`(?P<name>[^`]+)`\s*\("
    r"(?P<lane>[^·()]+?)\s*·\s*"
    r"(?P<state>[^·()]+?)\s*·\s*"
    r"(?P<cost>[^·()]+?)\)"
)
SKILL_TUPLE_RE = re.compile(
    r"`(?P<name>[^`]+)`\s*\((?P<label>SKILL\.md|authored|stub|untyped)\)"
)
STEP_RE = re.compile(r"^\*\*(S[0-7])\*\*(?:\s+\S.*)?$")
STEP_SHAPED_RE = re.compile(r"^\**S\d+")
STEP_HEADER = [
    "Step",
    "Specialists",
    "Tools `(lane · state · cost_tier)`",
    "Skills `(type)`",
    "Gate / Overlay",
]
STEP_SEPARATOR = ["---", "---", "---", "---", "---"]
FIX_HINTS = {
    "capability-state-overclaim": (
        "HINT: keep a partial tool in a prose needs_tool profile instead of a live tuple, "
        "or lower the declared capability state."
    ),
    "tool-lane-invalid": (
        "HINT: lane chrono is controller-only and is not card-citable; use a verified "
        "model/local lane or describe the controller handoff in prose."
    ),
    "metered-cost-contradiction": (
        "HINT: replace 'no metered' or 'subscription-only' with 'no paid' when metered "
        "tuples are present, and retain the required budget control."
    ),
    "skill-promotion-needs-2nd-row": (
        "HINT: keep the authored-pattern row and add a second invokable SKILL.md registry "
        "row before citing the promoted skill as SKILL.md."
    ),
}
REGISTRY_RELATIVE = Path("shared/registries/skill-tool-registry.tsv")


def registry_publication_state(root: Path) -> str:
    """Classify the validator registry as published, withheld, or broken.

    Public projections deliberately omit the registry, while maintainer trees
    track it.  Absence therefore needs one extra fact before it can be
    interpreted: an untracked path is ``not-published``; a tracked-but-missing
    path is a real failure.  Extracted public archives have no Git metadata, so
    they take the same non-published path as a public clone.
    """
    registry_path = root / REGISTRY_RELATIVE
    if registry_path.is_file():
        return "published"

    try:
        worktree = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return "unknown" if (root / ".git").exists() else "not-published"
    if worktree.returncode != 0:
        return "unknown" if (root / ".git").exists() else "not-published"

    try:
        tracked = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--error-unmatch",
                "--",
                REGISTRY_RELATIVE.as_posix(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return "unknown"
    if tracked.returncode == 0:
        return "missing"
    if tracked.returncode == 1:
        return "not-published"
    return "unknown"


def emit_registry_configuration(state: str) -> int:
    """Emit a typed result when registry-backed validation cannot start."""
    if state == "not-published":
        result_status = "not-applicable"
        summary_status = "pass"
        code = "registry-not-published"
        message = (
            "shared skill-tool registry is withheld from this tree by export policy; "
            "registry-backed capability validation is not applicable"
        )
        return_code = 0
    elif state == "missing":
        result_status = "fail"
        summary_status = "fail"
        code = "missing-registry"
        message = (
            "shared skill-tool registry is tracked by this tree but missing; "
            "capability validation failed closed"
        )
        return_code = 1
    else:
        result_status = "could-not-run"
        summary_status = "could-not-run"
        code = "registry-publication-undetermined"
        message = (
            "could not determine whether the absent shared skill-tool registry "
            "belongs to this distribution"
        )
        return_code = 2

    print(
        json.dumps(
            {
                "type": "registry-degradation",
                "file": REGISTRY_RELATIVE.as_posix(),
                "status": result_status,
                "code": code,
                "message": message,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    print(
        json.dumps(
            {
                "type": "summary",
                "files": 0,
                "passed": 0,
                "failed": 1 if result_status == "fail" else 0,
                "could_not_run": 1 if result_status == "could-not-run" else 0,
                "not_applicable": 1 if result_status == "not-applicable" else 0,
                "status": summary_status,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return return_code


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    line: int | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"code": self.code, "message": self.message}
        if self.line is not None:
            result["line"] = self.line
        return result


@dataclass(frozen=True)
class ToolUse:
    name: str
    lane: str
    state: str
    cost: str
    step: str
    line: int

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "lane": self.lane,
            "state": self.state,
            "cost": self.cost,
            "step": self.step,
            "line": self.line,
        }


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_frontmatter(text: str) -> tuple[dict[str, str], int, list[Finding]]:
    lines = text.splitlines()
    findings: list[Finding] = []
    if not lines or lines[0].strip() != "---":
        return {}, 0, [Finding("frontmatter-missing", "file must begin with ---", 1)]
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return {}, 0, [Finding("frontmatter-unclosed", "frontmatter has no closing ---", 1)]

    frontmatter: dict[str, str] = {}
    for index, line in enumerate(lines[1:end], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            findings.append(Finding("frontmatter-syntax", "frontmatter line has no colon", index))
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in frontmatter:
            findings.append(Finding("frontmatter-duplicate", f"duplicate key: {key}", index))
        frontmatter[key] = value.strip().strip('"').strip("'")
    return frontmatter, end + 1, findings


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def registry_lanes(value: str) -> set[str]:
    return {part.strip() for part in re.split(r"[|,]", value) if part.strip()}


def lane_supported(lane: str, registered: set[str]) -> bool:
    if lane in registered:
        return True
    return "all" in registered and lane in {"claude", "codex", "gemini", "kimi", "all"}


def add_once(items: list[ToolUse], use: ToolUse) -> None:
    if use not in items:
        items.append(use)


def unavailable_reason(rows: Iterable[dict[str, str]]) -> str | None:
    """Return a typed needs_tool reason when registry evidence names a provider failure."""
    evidence = " ".join(
        " ".join(
            row.get(field, "")
            for field in ("invocation", "evidence", "notes")
        )
        for row in rows
    ).lower()
    if re.search(r"(?:http\s*)?(?:401|403)\b|auth(?:entication)?[_ -]?failed|auth[- ]pending", evidence):
        return "auth"
    if re.search(r"(?:http\s*)?402\b|insufficient (?:credit|fund)|budget[- ]exhaust", evidence):
        return "budget"
    if re.search(r"(?:http\s*)?429\b|rate[- _]?limit", evidence):
        return "rate_limited"
    return None


def higgsfield_method(use: ToolUse, rows: Iterable[dict[str, str]]) -> str | None:
    lowered = use.name.lower()
    if lowered == "higgsfield raw generation":
        return "generate_image"
    if lowered == "higgsfield non-generation surface":
        return "non_generation_surface"
    if not lowered.startswith("higgsfield__"):
        return None
    method = lowered.split("higgsfield__", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "_", method).strip("_")


def guarded_replace(text: str, old: str, new: str, fixture_name: str) -> str:
    """Mutate exactly one fixture token and fail loudly when the source drifted."""
    mutated = text.replace(old, new, 1)
    if mutated == text:
        raise AssertionError(f"{fixture_name} fixture did not contain required token {old!r}")
    return mutated


def parse_tools(cell: str, step: str, line_number: int) -> tuple[list[ToolUse], list[Finding]]:
    if cell == "—":
        return [], []
    uses: list[ToolUse] = []
    findings: list[Finding] = []
    matches = list(TOOL_TUPLE_RE.finditer(cell))
    residual = TOOL_TUPLE_RE.sub("", cell)
    if not matches or not re.fullmatch(r"[\s,]*", residual):
        findings.append(
            Finding(
                "tool-grammar",
                "tools must use `tool` (lane · state · cost_tier), separated by commas",
                line_number,
            )
        )
    for match in matches:
        uses.append(
            ToolUse(
                name=match.group("name").strip(),
                lane=match.group("lane").strip(),
                state=match.group("state").strip(),
                cost=match.group("cost").strip(),
                step=step,
                line=line_number,
            )
        )
    return uses, findings


def parse_skills(cell: str, line_number: int) -> tuple[list[tuple[str, str]], list[Finding]]:
    if cell == "—":
        return [], []
    matches = list(SKILL_TUPLE_RE.finditer(cell))
    residual = SKILL_TUPLE_RE.sub("", cell)
    findings: list[Finding] = []
    if not matches or not re.fullmatch(r"[\s,;]*(?:—\s*stale)?[\s,;]*", residual):
        findings.append(
            Finding(
                "skill-grammar",
                "skills must use `skill` (SKILL.md|authored|stub|untyped)",
                line_number,
            )
        )
    return [(match.group("name").strip(), match.group("label")) for match in matches], findings


def parse_specialists(cell: str, line_number: int) -> tuple[list[str], list[Finding]]:
    names = [name.strip() for name in re.findall(r"`([^`]+)`", cell)]
    residual = re.sub(r"`[^`]+`", "", cell)
    findings: list[Finding] = []
    if not names or not re.fullmatch(r"[\s,+]*(?:if [A-Za-z0-9_ /+-]+)?", residual):
        findings.append(
            Finding(
                "specialist-grammar",
                "specialists must be backticked IDs separated by commas, with only + and a trailing if clause allowed",
                line_number,
            )
        )
    return names, findings


class Validator:
    def __init__(self, root: Path) -> None:
        self.root = root
        registry = read_tsv(root / REGISTRY_RELATIVE)
        self.registry_names = Counter(
            row["name"] for row in registry if row.get("name")
        )
        self.tools: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.skills: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in registry:
            target = self.tools if row["record_kind"] == "tool" else self.skills
            target[row["name"]].append(row)
        runtime_rows = read_tsv(root / "shared/specialist-runtime-map.tsv")
        self.specialists = Counter(row["specialist"] for row in runtime_rows)

    def validate_catalog_registry(self) -> dict[str, object]:
        catalog_path = self.root / "shared/skills/catalog.txt"
        display_path = catalog_path.relative_to(self.root).as_posix()
        try:
            catalog_names = [
                line.strip()
                for line in catalog_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        except (OSError, UnicodeError) as exc:
            findings = [Finding("catalog-read", str(exc))]
            catalog_names = []
        else:
            findings = []
            for name in catalog_names:
                count = self.registry_names[name]
                if count == 0:
                    findings.append(
                        Finding(
                            "catalog-registry-missing",
                            f"catalog skill {name!r} has no registry row",
                        )
                    )
                elif count != 1:
                    findings.append(
                        Finding(
                            "catalog-registry-ambiguous",
                            f"catalog skill {name!r} has {count} registry rows; expected exactly one",
                        )
                    )
        return {
            "type": "catalog-registry",
            "file": display_path,
            "status": "fail" if findings else "pass",
            "errors": [finding.as_dict() for finding in findings],
            "catalog_count": len(catalog_names),
            "catalog_unique_count": len(set(catalog_names)),
        }

    def validate_text(self, text: str, display_path: str, expected_path: Path | None) -> dict[str, object]:
        findings: list[Finding] = []
        frontmatter, body_start, frontmatter_findings = parse_frontmatter(text)
        findings.extend(frontmatter_findings)
        for key in REQUIRED_FRONTMATTER:
            if not frontmatter.get(key):
                findings.append(Finding("frontmatter-required", f"missing or empty key: {key}"))

        mode = frontmatter.get("mode", "")
        declared = frontmatter.get("capability_state", "")
        if mode and mode not in MODES:
            findings.append(Finding("mode-invalid", f"invalid mode: {mode}"))
        if declared and declared not in CAPABILITY_STATES:
            findings.append(Finding("capability-state-invalid", f"invalid capability_state: {declared}"))
        if expected_path is not None:
            try:
                capability_relative = expected_path.relative_to(self.root / "shared/capabilities")
            except ValueError:
                findings.append(Finding("path-invalid", "capability is outside shared/capabilities"))
            else:
                expected_mode = capability_relative.parts[0] if len(capability_relative.parts) > 1 else ""
                expected_id = capability_relative.with_suffix("").as_posix()
                if mode and mode != expected_mode:
                    findings.append(
                        Finding("mode-path-mismatch", f"mode {mode!r} does not match path mode {expected_mode!r}")
                    )
                if frontmatter.get("id") and frontmatter["id"] != expected_id:
                    findings.append(
                        Finding("id-path-mismatch", f"id {frontmatter['id']!r} does not match path {expected_id!r}")
                    )

        lines = text.splitlines()
        steps: list[str] = []
        tool_uses: list[ToolUse] = []
        skill_uses: list[tuple[str, str, int]] = []
        specialist_uses: list[tuple[str, int]] = []
        gate_overlay_cells: list[str] = []
        body_lines = list(enumerate(lines[body_start:], body_start + 1))
        step_block_positions: set[int] = set()
        header_positions = [
            position
            for position, (_, line) in enumerate(body_lines)
            if line.lstrip().startswith("|") and table_cells(line) == STEP_HEADER
        ]
        if not header_positions:
            findings.append(Finding("step-header", "missing exact locked step-table header"))
            step_rows: list[tuple[int, str]] = []
        else:
            step_block_positions.add(header_positions[0])
            if len(header_positions) > 1:
                findings.append(
                    Finding("step-header-duplicate", "multiple locked step-table headers found")
                )
            step_rows = []
            for position, (index, line) in enumerate(
                body_lines[header_positions[0] + 1 :], header_positions[0] + 1
            ):
                if not line.lstrip().startswith("|"):
                    break
                step_block_positions.add(position)
                step_rows.append((index, line))
            if not step_rows or table_cells(step_rows[0][1]) != STEP_SEPARATOR:
                findings.append(
                    Finding(
                        "step-separator",
                        "locked step-table header must be followed by the exact five-column separator",
                        step_rows[0][0] if step_rows else body_lines[header_positions[0]][0] + 1,
                    )
                )

        for position, (index, line) in enumerate(body_lines):
            if position in step_block_positions or not line.lstrip().startswith("|"):
                continue
            cells = table_cells(line)
            if cells and STEP_SHAPED_RE.match(cells[0]):
                findings.append(
                    Finding(
                        "step-row-out-of-block",
                        "step-shaped pipe rows may only appear inside the canonical step-table block",
                        index,
                    )
                )

        for row_position, (index, line) in enumerate(step_rows):
            cells = table_cells(line)
            if cells == STEP_SEPARATOR:
                if row_position != 0:
                    findings.append(
                        Finding(
                            "step-row-malformed",
                            "the step-table separator may only appear immediately after the header",
                            index,
                        )
                    )
                continue
            if len(cells) != 5:
                findings.append(Finding("step-columns", "step row must have exactly five columns", index))
                continue
            step_match = STEP_RE.fullmatch(cells[0])
            if not step_match:
                if re.match(r"^\*\*S\d+", cells[0]):
                    findings.append(Finding("step-identifier", f"invalid step cell: {cells[0]!r}", index))
                else:
                    findings.append(
                        Finding(
                            "step-row-malformed",
                            "every row in the step table must begin with a bold **S0** through **S7** identifier",
                            index,
                        )
                    )
                step = f"INVALID@{index}"
            else:
                step = step_match.group(1)
                steps.append(step)
            specialist_tokens, specialist_findings = parse_specialists(cells[1], index)
            specialist_uses.extend((name, index) for name in specialist_tokens)
            findings.extend(specialist_findings)
            parsed_tools, tool_findings = parse_tools(cells[2], step, index)
            tool_uses.extend(parsed_tools)
            findings.extend(tool_findings)
            parsed_skills, skill_findings = parse_skills(cells[3], index)
            skill_uses.extend((name, label, index) for name, label in parsed_skills)
            findings.extend(skill_findings)
            gate_overlay_cells.append(cells[4])

        if not steps:
            findings.append(Finding("steps-missing", "no S0-S7 step rows found"))
        else:
            if len(steps) != len(set(steps)):
                findings.append(Finding("steps-duplicate", "step identifiers must be unique"))
            if steps != sorted(steps, key=lambda value: int(value[1:])):
                findings.append(Finding("steps-order", "step rows must be in ascending order"))
            if "S0" not in steps or "S7" not in steps:
                findings.append(Finding("steps-boundary", "step table must include S0 and S7"))

        for name, line_number in specialist_uses:
            if name in SENTINELS:
                continue
            count = self.specialists[name]
            if count != 1:
                findings.append(
                    Finding(
                        "specialist-registry",
                        f"specialist {name!r} occurs {count} times in the runtime map; expected exactly once",
                        line_number,
                    )
                )

        forcing_tools: list[ToolUse] = []
        metered: list[ToolUse] = []
        unavailable_reasons: set[str] = set()
        higgsfield_paid_actions: list[ToolUse] = []
        derived_needs_tool = False
        derived_degraded = False
        for use in tool_uses:
            if use.lane not in LANES:
                findings.append(Finding("tool-lane-invalid", f"invalid lane {use.lane!r} for {use.name}", use.line))
            if use.state not in TOOL_STATES:
                findings.append(Finding("tool-state-invalid", f"invalid state {use.state!r} for {use.name}", use.line))
            if use.cost not in COSTS:
                findings.append(Finding("tool-cost-invalid", f"invalid cost {use.cost!r} for {use.name}", use.line))

            candidates = self.tools.get(use.name, [])
            matching = [row for row in candidates if lane_supported(use.lane, registry_lanes(row["lanes"]))]
            if not matching:
                derived_needs_tool = True
                add_once(forcing_tools, use)
                if "/" in use.name:
                    findings.append(
                        Finding(
                            "tool-slash-grouping",
                            f"unregistered slash-grouped tool {use.name!r} is forbidden",
                            use.line,
                        )
                    )
                if (use.lane, use.state, use.cost) != ("unknown", "catalog-absent", "unknown"):
                    findings.append(
                        Finding(
                            "tool-catalog-claim",
                            f"{use.name!r} is absent for lane {use.lane!r}; use unknown · catalog-absent · unknown",
                            use.line,
                        )
                    )
            elif len(matching) > 1:
                derived_states = {row["verified_state"] for row in matching}
                derived_needs_tool |= bool(derived_states & UNAVAILABLE_TOOL_STATES)
                derived_degraded |= bool(derived_states & DEGRADED_TOOL_STATES)
                if derived_states & UNAVAILABLE_TOOL_STATES:
                    reason = unavailable_reason(matching)
                    if reason:
                        unavailable_reasons.add(reason)
                add_once(forcing_tools, use)
                findings.append(
                    Finding(
                        "tool-registry-ambiguous",
                        f"{use.name!r} has multiple registry rows matching lane {use.lane!r}",
                        use.line,
                    )
                )
            elif not (
                use.state == matching[0]["verified_state"] and use.cost == matching[0]["cost_tier"]
            ):
                registered_state = matching[0]["verified_state"]
                compared_states = {registered_state, use.state} & TOOL_STATES
                derived_needs_tool |= bool(compared_states & UNAVAILABLE_TOOL_STATES)
                derived_degraded |= bool(compared_states & DEGRADED_TOOL_STATES)
                if compared_states & UNAVAILABLE_TOOL_STATES:
                    reason = unavailable_reason(matching)
                    if reason:
                        unavailable_reasons.add(reason)
                if registered_state not in LIVE_TOOL_STATES or use.state not in LIVE_TOOL_STATES:
                    add_once(forcing_tools, use)
                expected = sorted({f"{row['verified_state']} · {row['cost_tier']}" for row in matching})
                findings.append(
                    Finding(
                        "tool-registry-mismatch",
                        f"{use.name!r} claims {use.state} · {use.cost}; expected one of {expected}",
                        use.line,
                    )
                )
            elif use.state in UNAVAILABLE_TOOL_STATES:
                derived_needs_tool = True
                reason = unavailable_reason(matching)
                if reason:
                    unavailable_reasons.add(reason)
                add_once(forcing_tools, use)
            elif use.state in DEGRADED_TOOL_STATES:
                derived_degraded = True
                add_once(forcing_tools, use)

            method = higgsfield_method(use, matching)
            if method in HIGGSFIELD_RAW_GENERATION_METHODS:
                derived_needs_tool = True
                add_once(forcing_tools, use)
                findings.append(
                    Finding(
                        "higgsfield-raw-generation-unavailable",
                        "raw Higgsfield generation is unavailable; use the governed "
                        "chrono-media-studio generate_image/generate_video/generate_audio wrapper",
                        use.line,
                    )
                )
            elif method and not any(hint in method for hint in HIGGSFIELD_FREE_READ_HINTS):
                higgsfield_paid_actions.append(use)
            if use.cost == "metered" or any(row["cost_tier"] == "metered" for row in matching):
                metered.append(use)

        for name, label, line_number in skill_uses:
            rows = self.skills.get(name, [])
            label_matches = [row for row in rows if SKILL_LABELS.get(row["type"], "untyped") == label]
            expected_labels = {SKILL_LABELS.get(row["type"], "untyped") for row in rows} or {"untyped"}
            valid = (not rows and label == "untyped") or len(label_matches) == 1
            if not valid:
                code = "skill-registry-mismatch"
                if label == "SKILL.md" and rows and not any(
                    row["type"] == "invokable" for row in rows
                ):
                    code = "skill-promotion-needs-2nd-row"
                findings.append(
                    Finding(
                        code,
                        f"{name!r} is labeled {label!r}; expected one of {sorted(expected_labels)}",
                        line_number,
                    )
                )

        if derived_needs_tool:
            derived = (
                f"needs_tool:{next(iter(unavailable_reasons))}"
                if len(unavailable_reasons) == 1
                else "needs_tool"
            )
        elif derived_degraded:
            derived = "degraded-blueprint"
        else:
            derived = "live"

        generosity = {"needs_tool": 0, "degraded-blueprint": 1, "lane-gated": 2, "live": 3}
        derived_base = derived.split(":", 1)[0]
        if declared in generosity and generosity[declared] > generosity[derived_base]:
            findings.append(
                Finding(
                    "capability-state-overclaim",
                    f"declared {declared!r} is more generous than derived {derived!r}",
                )
            )

        gate_overlay_text = "\n".join(
            [frontmatter.get("gates", ""), frontmatter.get("overlays", ""), *gate_overlay_cells]
        )
        if any(use.name == PERPLEXITY_STRUCTURED_TOOL for use in tool_uses):
            truth_gate_patterns = {
                "claim_to_citation=true": r"\bclaim_to_citation=true\b",
                "date_window=<explicit interval>": (
                    r"\bdate_window=(?!(?:true|false)(?:\b|$)|<)[^\s,;\]|]+"
                ),
                "reject_unsupported=true": r"\breject_unsupported=true\b",
            }
            missing = [
                token
                for token, pattern in truth_gate_patterns.items()
                if not re.search(pattern, gate_overlay_text, re.IGNORECASE)
            ]
            if missing:
                findings.append(
                    Finding(
                        "perplexity-truth-gate-missing",
                        "Perplexity structured+recency requires Gate / Overlay tokens: "
                        + ", ".join(missing),
                    )
                )

        if higgsfield_paid_actions:
            if not re.search(r"\bpaid_media\b", gate_overlay_text):
                findings.append(
                    Finding(
                        "higgsfield-paid-media-gate-missing",
                        "paid Higgsfield utility actions require the paid_media gate",
                    )
                )
            if not re.search(r"\bget_cost:true\b", gate_overlay_text, re.IGNORECASE):
                findings.append(
                    Finding(
                        "higgsfield-cost-preflight-missing",
                        "paid Higgsfield utility actions require get_cost:true before invocation",
                    )
                )

        kimi_routed = any(use.lane == "kimi" for use in tool_uses)
        frontmatter_budget = frontmatter.get("budget_control", "")
        external_budget_present = bool(
            EXTERNAL_BUDGET_RE.search(gate_overlay_text)
            or FRONTMATTER_EXTERNAL_BUDGET_RE.fullmatch(frontmatter_budget)
        )
        if kimi_routed and metered and not external_budget_present:
            findings.append(
                Finding(
                    "external-budget-ceiling-missing",
                    "Kimi-mediated metered tools require a numeric external budget ceiling",
                )
            )
        if kimi_routed and "--max-ralph-iterations=-1" in text:
            findings.append(
                Finding(
                    "kimi-unbounded-iterations",
                    "governed Kimi runs may not use --max-ralph-iterations=-1",
                )
            )

        cost_note = frontmatter.get("cost_note", "")
        lowered_note = cost_note.lower()
        if metered and not (
            "metered" in lowered_note and ("budget" in lowered_note or "rate-limit" in lowered_note)
        ):
            findings.append(
                Finding(
                    "metered-cost-note",
                    "metered tools require a cost_note naming metering and a budget or rate-limit",
                )
            )
        if metered and re.search(r"\bno metered\b|subscription[- ]only", lowered_note):
            findings.append(
                Finding("metered-cost-contradiction", "cost_note contradicts the metered tool tuples")
            )

        return {
            "type": "capability",
            "file": display_path,
            "status": "fail" if findings else "pass",
            "errors": [finding.as_dict() for finding in findings],
            "declared_state": declared or None,
            "derived_state": derived,
            "forcing_tools": [use.as_dict() for use in forcing_tools],
            "metered_tool_count": len(metered),
            "metered_unique_count": len({use.name for use in metered}),
            "metered_tools": sorted({use.name for use in metered}),
            "cost_note": cost_note or None,
            "specialist_occurrences": len(specialist_uses),
            "tool_occurrences": len(tool_uses),
            "skill_occurrences": len(skill_uses),
        }

    def validate_path(self, path: Path) -> dict[str, object]:
        try:
            display_path = path.relative_to(self.root).as_posix()
        except ValueError:
            display_path = str(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return {
                "type": "capability",
                "file": display_path,
                "status": "fail",
                "errors": [Finding("file-read", str(exc)).as_dict()],
                "declared_state": None,
                "derived_state": None,
                "forcing_tools": [],
                "metered_tool_count": 0,
                "metered_tools": [],
                "cost_note": None,
                "specialist_occurrences": 0,
                "tool_occurrences": 0,
                "skill_occurrences": 0,
            }
        return self.validate_text(text, display_path, path)


def discover(root: Path) -> list[Path]:
    base = root / "shared/capabilities"
    return sorted(
        path
        for path in base.rglob("*.md")
        if not path.name.startswith("_")
        # `public/` holds the generated export variants. They deliberately drop
        # capability_state, state_reason, state_evidence and cost_note -- that
        # stripping is the point, since those fields are a census of what works
        # on OUR machine. Validating a derived artifact against the source
        # schema fails by construction; freshness is enforced instead by
        # tools/export/build_public_capability_cards.py --check in CI, which
        # also re-runs the private-state guard.
        and "public" not in path.relative_to(base).parts
    )


def resolve_paths(root: Path, values: Iterable[str]) -> list[Path]:
    paths = []
    for value in values:
        path = Path(value)
        paths.append(path if path.is_absolute() else root / path)
    return paths


def resolve_capability_alias(mode: str, reference: str) -> tuple[str, str, bool]:
    """Resolve a legacy domain-mode capability pointer to its canonical project id.

    `mode` is the packet's declared mode; `reference` is its capability value
    (a full `<mode>/<slug>` id or a bare slug). The legacy full id is `reference`
    when it already contains '/', else `<mode>/<slug>`. Returns
    `(canonical_mode, canonical_reference, aliased)`. A pointer with no alias
    entry is returned unchanged with `aliased=False`, so non-legacy packets are
    unaffected. See CAPABILITY_ALIASES for the stage-1 resolve-only map.
    """
    mode = (mode or "").strip()
    reference = (reference or "").strip()
    # A5-review P1: when the reference carries an explicit `<mode>/<slug>` prefix, the
    # packet's declared mode MUST agree with it before we alias — otherwise a
    # `mode=bounty` packet pointing at a `content/<slug>` id would silently change
    # mode meaning. Reject the mismatch rather than resolving it.
    if "/" in reference:
        ref_prefix = reference.split("/", 1)[0]
        if mode and ref_prefix != mode:
            raise ValueError(
                f"capability alias mode mismatch: packet mode {mode!r} disagrees with "
                f"reference prefix {ref_prefix!r} ({reference!r})"
            )
    legacy_id = reference if "/" in reference else (f"{mode}/{reference}" if mode else reference)
    canonical = CAPABILITY_ALIASES.get(legacy_id)
    if canonical is None:
        return mode, reference, False
    return canonical.split("/", 1)[0], canonical, True


def add_fix_hints(result: dict[str, object]) -> dict[str, object]:
    """Copy one result and add one-line remedies for explainable findings."""
    explained = dict(result)
    errors = result.get("errors")
    if isinstance(errors, list):
        explained_errors: list[object] = []
        for error in errors:
            if not isinstance(error, dict):
                explained_errors.append(error)
                continue
            explained_error = dict(error)
            hint = FIX_HINTS.get(str(error.get("code", "")))
            if hint:
                explained_error["hint"] = hint
            explained_errors.append(explained_error)
        explained["errors"] = explained_errors
    return explained


def emit_results(results: list[dict[str, object]], explain: bool = False) -> int:
    for result in results:
        output = add_fix_hints(result) if explain else result
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    failed = sum(result["status"] == "fail" for result in results)
    summary = {
        "type": "summary",
        "files": len(results),
        "passed": len(results) - failed,
        "failed": failed,
        "status": "fail" if failed else "pass",
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Self-test fixtures
# ---------------------------------------------------------------------------
# Fixture rule: a fixture's INTENDED defect must never be produced by a real
# skill / tool / specialist whose registry status can change. Wave 2 authored
# `requirements-elicitation` (stub -> authored); that single flip silently
# deleted the `composite` fixture's skill-registry-mismatch and turned this
# self-test red for a reason nothing in the diff named. Because a negative
# fixture only asserts that its expected codes are a SUBSET of the emitted
# codes, such a flip is silent coverage loss, not a loud failure. Exactly three
# fixture constructions are allowed:
#
#   1. synthetic - the defect comes from a guaranteed-absent id (ABSENT_*) or an
#      intrinsically invalid literal (a multi-lane tuple, an unbolded step row).
#      No registry can flip it. Prefer this.
#   2. registry-derived - the fixture must name a real entity because the rule
#      under test keys on that name (Perplexity truth gate, Higgsfield cost
#      preflight). Every mutable field - verified_state, cost_tier, and the
#      declared capability_state derived from them - is read from the registry
#      at build time, so the fixture cannot desynchronise from it; only
#      structural fields (tool name, lane) stay literal. Where the defect itself
#      requires one specific value (the metered cost tier in
#      `kimi-metered-unbounded`) that value stays literal and says so inline.
#   3. precondition-guarded - the defect is *about* real registry state (typed
#      dead-key reasons; a metered tuple inside a real golden card). The
#      assumption is asserted, and drift is reported as a named precondition
#      failure instead of an opaque expected-vs-actual error-set diff.
#
# Never add a real registry name to the ABSENT_* ids, and never hardcode a real
# entity's status into a fixture again.

ABSENT_SPECIALIST = "phantom-specialist"
ABSENT_SKILL = "fake-skill"
ABSENT_TOOL = "missing-tool"
ABSENT_TOOL_ALT = "evil-tool"
WEB_APP_CARD = "shared/capabilities/project/web-app.md"
SELF_EXTENSION_CARD = "shared/capabilities/project/self-extension-agent-tooling.md"
BOUNTY_CONTRACT_CARD = "shared/capabilities/bounty/smart-contract-web3.md"
GOLDEN_CARDS = (
    WEB_APP_CARD,
    BOUNTY_CONTRACT_CARD,
    "shared/capabilities/project/image.md",
    SELF_EXTENSION_CARD,
    "shared/capabilities/project/ai-llm-application.md",
    "shared/capabilities/project/backend-service-api.md",
    "shared/capabilities/project/data-pipeline.md",
    "shared/capabilities/project/platform-release.md",
    "shared/capabilities/project/smart-contract-web3.md",
    "shared/capabilities/project/systems-low-level.md",
)


@dataclass(frozen=True)
class ToolRef:
    """A fixture tool tuple whose mutable fields come from the live registry."""

    text: str
    state: str
    cost: str

    @property
    def declared_state(self) -> str:
        """The capability_state the validator will derive from this single tool."""
        if self.state in LIVE_TOOL_STATES:
            return "live"
        if self.state in DEGRADED_TOOL_STATES:
            return "degraded-blueprint"
        return "needs_tool"

    @property
    def cost_note(self) -> str:
        """A cost_note that satisfies the metered guard for this tool's cost tier."""
        return "metered with budget ceiling" if self.cost == "metered" else "subscription only"


@dataclass
class FixtureSuite:
    """Self-test fixtures plus the drift diagnostics collected while building them."""

    positives: dict[str, str]
    negatives: dict[str, tuple[str, set[str]]]
    dead_key_fixtures: dict[str, str]
    preconditions: list[str]


def policy_fixture(
    fixture_id: str,
    declared_state: str,
    tool_tuple: str,
    gate: str = "—",
    cost_note: str = "subscription only",
    budget_control: str | None = None,
) -> str:
    budget_line = f"budget_control: {budget_control}\n" if budget_control else ""
    return f"""---
id: project/{fixture_id}
mode: project
title: Policy fixture {fixture_id}
capability_state: {declared_state}
state_reason: Self-test policy fixture.
state_evidence: Self-test registry evidence.
overlays: []
gates: []
cost_note: {cost_note}
{budget_line}---
| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake | `Chrono` | — | — | — |
| **S3** Produce | `Chrono` | {tool_tuple} | — | {gate} |
| **S7** Capture | `Chrono` | — | — | — |
"""


def first_step_tool_tuple(text: str) -> tuple[re.Match[str], int] | None:
    """Locate the first tool tuple inside a step row's Tools cell.

    Fixtures that mutate a real card must anchor on the same cell the validator
    parses; searching the whole document also matches the prose and the header's
    `(lane · state · cost_tier)` legend.
    """
    offset = 0
    for line in text.splitlines(keepends=True):
        segments = line.split("|")
        if line.lstrip().startswith("|") and len(segments) >= 5:
            cells = table_cells(line)
            if len(cells) == len(STEP_HEADER) and STEP_RE.match(cells[0]):
                match = TOOL_TUPLE_RE.search(segments[3])
                if match is not None:
                    return match, offset + len("|".join(segments[:3])) + 1
        offset += len(line)
    return None


def build_self_test_fixtures(
    validator: Validator, golden_text: dict[str, str]
) -> FixtureSuite:
    """Build every self-test fixture under the fixture rule documented above."""
    preconditions: list[str] = []

    def registry_row(name: str, lane: str, fixture: str) -> dict[str, str] | None:
        rows = [
            row
            for row in validator.tools.get(name, [])
            if lane_supported(lane, registry_lanes(row["lanes"]))
        ]
        if len(rows) != 1:
            preconditions.append(
                f"{fixture}: registry holds {len(rows)} rows for tool {name!r} on lane "
                f"{lane!r}; expected exactly 1 - repoint the fixture at a live registry row"
            )
            return None
        return rows[0]

    def tool_ref(name: str, lane: str, fixture: str, cost: str | None = None) -> ToolRef:
        """Registry-derived tuple; `cost` is only pinned when the defect requires it."""
        row = registry_row(name, lane, fixture)
        state = row["verified_state"] if row else "needs-research"
        resolved_cost = cost if cost is not None else (row["cost_tier"] if row else "unknown")
        return ToolRef(f"`{name}` ({lane} · {state} · {resolved_cost})", state, resolved_cost)

    # -- synthetic fixtures -------------------------------------------------
    broken = f"""---
id: project/broken
mode: project
title: Broken fixture
capability_state: live
state_reason: Deliberate overclaim.
state_evidence: Self-test fixture.
overlays: []
gates: []
cost_note: —
---
| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** | `{ABSENT_SPECIALIST}` | `{ABSENT_TOOL}` (codex · yes · subscription) | `{ABSENT_SKILL}` (authored) | Bad input |
| **S7** | `Chrono` | — | — | Done |
"""
    unbolded_exploit = f"""---
id: project/unbolded-exploit
mode: project
title: Unbolded malicious step fixture
capability_state: live
state_reason: Deliberately malformed step row.
state_evidence: Self-test fixture.
overlays: []
gates: []
cost_note: —
---
| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake | `Chrono` | — | — | — |
| S3 Produce | `{ABSENT_SPECIALIST}` | `{ABSENT_TOOL_ALT}` (claude · yes · subscription) | `{ABSENT_SKILL}` (authored) | — |
| **S7** Capture | `Chrono` | — | — | — |
"""
    bold_exploit_control = guarded_replace(
        unbolded_exploit, "| S3 Produce |", "| **S3** Produce |", "bold-step-control"
    )
    out_of_block_frontmatter = """---
id: project/out-of-block-exploit
mode: project
title: Out-of-block malicious step fixture
capability_state: live
state_reason: Deliberately misplaced step row.
state_evidence: Self-test fixture.
overlays: []
gates: []
cost_note: —
---"""
    canonical_minimal_table = """| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake | `Chrono` | — | — | — |
| **S7** Capture | `Chrono` | — | — | — |"""
    out_of_block_payload = (
        f"| **S3** Produce | `{ABSENT_SPECIALIST}` | "
        f"`{ABSENT_TOOL_ALT}` (claude · yes · subscription) | `{ABSENT_SKILL}` (authored) | — |"
    )
    out_of_block_after = (
        f"{out_of_block_frontmatter}\n{canonical_minimal_table}\n\n{out_of_block_payload}\n"
    )
    out_of_block_before = (
        f"{out_of_block_frontmatter}\n{out_of_block_payload}\n{canonical_minimal_table}\n"
    )
    out_of_block_unbolded_after = guarded_replace(
        out_of_block_after, "| **S3** Produce |", "| S3 Produce |", "unbolded-step-row-after-block"
    )
    # A catalog-absent tuple is the one absent-tool shape the validator accepts,
    # so this fixture derives needs_tool with no second defect riding along.
    state_overclaim_fixture = guarded_replace(
        policy_fixture(
            "state-overclaim",
            "needs_tool",
            f"`{ABSENT_TOOL}` (unknown · catalog-absent · unknown)",
        ),
        "capability_state: needs_tool",
        "capability_state: live",
        "state-overclaim",
    )

    # -- golden-card fixtures: anchored on structure, never on status -------
    web_app_card = golden_text[WEB_APP_CARD]
    multi_lane_text, lane_hits = re.subn(r"\(claude\s*·", "(claude+codex ·", web_app_card, count=1)
    if not lane_hits:
        preconditions.append(
            f"multi-lane: {WEB_APP_CARD} no longer contains a `claude`-lane tool tuple; the "
            "fixture anchors on the lane field so a status flip cannot break it, but the card "
            "must still route one tool through the claude lane"
        )

    self_extension_card = golden_text[SELF_EXTENSION_CARD]
    registry_mismatch_text = self_extension_card
    located = first_step_tool_tuple(self_extension_card)
    if located is None:
        preconditions.append(
            f"registry-mismatch: no step-row tool tuple found in {SELF_EXTENSION_CARD}"
        )
    else:
        first_tool, cell_offset = located
        mismatch_name = first_tool.group("name").strip()
        mismatch_lane = first_tool.group("lane").strip()
        mismatch_state = first_tool.group("state").strip()
        mismatch_row = registry_row(mismatch_name, mismatch_lane, "registry-mismatch")
        registered_cost = (
            mismatch_row["cost_tier"] if mismatch_row else first_tool.group("cost").strip()
        )
        # Pick a cost tier that provably differs from the registered one, so the
        # mismatch is guaranteed by construction rather than by today's registry.
        wrong_cost = next(
            (cost for cost in ("unknown", "subscription", "metered", "—") if cost != registered_cost),
            "unknown",
        )
        registry_mismatch_text = (
            self_extension_card[: cell_offset + first_tool.start()]
            + f"`{mismatch_name}` ({mismatch_lane} · {mismatch_state} · {wrong_cost})"
            + self_extension_card[cell_offset + first_tool.end() :]
        )

    bounty_card = golden_text[BOUNTY_CONTRACT_CARD]
    if not re.search(r"·\s*metered\s*\)", bounty_card):
        preconditions.append(
            f"metered-without-guard: {BOUNTY_CONTRACT_CARD} no longer declares a metered tool "
            "tuple, so stripping its cost_note cannot raise metered-cost-note - repoint the "
            "fixture at a card that still routes a metered tool"
        )
    metered_without_guard = re.sub(
        r"(?m)^cost_note:.*$", "cost_note: —", bounty_card, count=1
    )
    if metered_without_guard == bounty_card:
        preconditions.append(
            f"metered-without-guard: no cost_note line to strip in {BOUNTY_CONTRACT_CARD}"
        )

    # -- registry-derived policy fixtures -----------------------------------
    grounding = tool_ref("Google Search grounding", "gemini", "grounding-live-positive")
    perplexity_ok = tool_ref(
        PERPLEXITY_STRUCTURED_TOOL, "codex", "perplexity-valid-truth-gate"
    )
    higgs_free_read = tool_ref(
        "higgsfield__models_explore", "claude", "higgs-free-read-positive"
    )
    xai_bounded = tool_ref("xai_search", "kimi", "kimi-metered-bounded")
    positives = {
        "grounding-live-positive": policy_fixture(
            "grounding-live-positive",
            grounding.declared_state,
            grounding.text,
            "claim_to_citation=true reject_unsupported=true",
            grounding.cost_note,
        ),
        "perplexity-valid-truth-gate": policy_fixture(
            "perplexity-valid-truth-gate",
            perplexity_ok.declared_state,
            perplexity_ok.text,
            "claim_to_citation=true date_window=24h reject_unsupported=true",
            perplexity_ok.cost_note,
        ),
        "higgs-free-read-positive": policy_fixture(
            "higgs-free-read-positive",
            higgs_free_read.declared_state,
            higgs_free_read.text,
            cost_note=higgs_free_read.cost_note,
        ),
        "kimi-metered-bounded": policy_fixture(
            "kimi-metered-bounded",
            xai_bounded.declared_state,
            xai_bounded.text,
            "external-budget-ceiling=5calls",
            xai_bounded.cost_note,
        ),
    }

    perplexity_bad = tool_ref(
        PERPLEXITY_STRUCTURED_TOOL, "codex", "perplexity-missing-truth-gate"
    )
    higgs_raw = tool_ref(
        "Higgsfield raw generation", "none", "higgs-raw-generation-negative"
    )
    higgs_paid = tool_ref(
        "higgsfield__upscale_image", "claude", "higgs-paid-without-cost-preflight"
    )
    # The metered cost tier IS the defect precondition here (Kimi + metered with
    # no numeric ceiling), so it is pinned literally rather than read from the
    # registry: a cost-tier flip must not silently retire this fixture.
    xai_unbounded = tool_ref("xai_search", "kimi", "kimi-metered-unbounded", cost="metered")

    negatives: dict[str, tuple[str, set[str]]] = {
        "composite": (
            broken,
            {
                "specialist-registry",
                "tool-catalog-claim",
                "skill-registry-mismatch",
                # an absent tool derives needs_tool, so `capability_state: live`
                # is a deterministic second defect of this fixture
                "capability-state-overclaim",
            },
        ),
        "multi-lane": (multi_lane_text, {"tool-lane-invalid"}),
        "registry-mismatch": (registry_mismatch_text, {"tool-registry-mismatch"}),
        "state-overclaim": (state_overclaim_fixture, {"capability-state-overclaim"}),
        "metered-without-guard": (metered_without_guard, {"metered-cost-note"}),
        "unbolded-step-row": (
            unbolded_exploit,
            {
                "step-row-malformed",
                "specialist-registry",
                "tool-catalog-claim",
                "skill-registry-mismatch",
                "capability-state-overclaim",
            },
        ),
        "bold-step-control": (
            bold_exploit_control,
            {
                "specialist-registry",
                "tool-catalog-claim",
                "skill-registry-mismatch",
                "capability-state-overclaim",
            },
        ),
        "step-row-after-block": (out_of_block_after, {"step-row-out-of-block"}),
        "step-row-before-header": (out_of_block_before, {"step-row-out-of-block"}),
        "unbolded-step-row-after-block": (
            out_of_block_unbolded_after,
            {"step-row-out-of-block"},
        ),
        "perplexity-missing-truth-gate": (
            policy_fixture(
                "perplexity-missing-truth-gate",
                perplexity_bad.declared_state,
                perplexity_bad.text,
                "paid research",
                perplexity_bad.cost_note,
            ),
            {"perplexity-truth-gate-missing"},
        ),
        "higgs-raw-generation-negative": (
            policy_fixture(
                "higgs-raw-generation-negative",
                # raw generation always forces needs_tool, so `live` is a
                # deliberate overclaim independent of the registry row
                "live",
                higgs_raw.text,
                "paid_media get_cost:true",
                higgs_raw.cost_note,
            ),
            {"capability-state-overclaim", "higgsfield-raw-generation-unavailable"},
        ),
        "higgs-paid-without-cost-preflight": (
            policy_fixture(
                "higgs-paid-without-cost-preflight",
                higgs_paid.declared_state,
                higgs_paid.text,
                "paid_media",
                higgs_paid.cost_note,
            ),
            {"higgsfield-cost-preflight-missing"},
        ),
        "kimi-metered-unbounded": (
            policy_fixture(
                "kimi-metered-unbounded",
                xai_unbounded.declared_state,
                xai_unbounded.text,
                "budget discussed in prose",
                xai_unbounded.cost_note,
            ),
            {"external-budget-ceiling-missing"},
        ),
    }

    # -- precondition-guarded dead-key fixtures ------------------------------
    # These assert the typed needs_tool:<reason> derivation, which is inherently
    # about real registry evidence, so the keys are SELECTED from the registry
    # instead of hardcoded: any auth-typed dead key will do, and losing them all
    # is reported by name rather than as a mystery error-set diff.
    auth_dead: list[tuple[str, str, dict[str, str]]] = []
    for name in sorted(validator.tools):
        rows = validator.tools[name]
        if len(rows) != 1:
            continue
        row = rows[0]
        lanes = sorted(registry_lanes(row["lanes"]))
        if len(lanes) != 1 or lanes[0] not in LANES:
            continue
        if row["verified_state"] not in UNAVAILABLE_TOOL_STATES:
            continue
        if row["cost_tier"] not in COSTS:
            continue
        if unavailable_reason([row]) != "auth":
            continue
        auth_dead.append((name, lanes[0], row))

    dead_key_labels = ("dead-key-auth-primary", "dead-key-auth-secondary")
    dead_key_fixtures: dict[str, str] = {}
    for label, (name, lane, row) in zip(dead_key_labels, auth_dead):
        ref = ToolRef(
            f"`{name}` ({lane} · {row['verified_state']} · {row['cost_tier']})",
            row["verified_state"],
            row["cost_tier"],
        )
        dead_key_fixtures[label] = name
        negatives[label] = (
            policy_fixture(label, "live", ref.text, cost_note=ref.cost_note),
            {"capability-state-overclaim"},
        )
    if len(dead_key_fixtures) < len(dead_key_labels):
        preconditions.append(
            f"{'/'.join(dead_key_labels)}: the registry exposes only {len(auth_dead)} "
            "single-row auth-typed dead tools; the needs_tool:auth derivation check needs "
            f"{len(dead_key_labels)} - restore one or retarget the check at another reason"
        )

    return FixtureSuite(
        positives=positives,
        negatives=negatives,
        dead_key_fixtures=dead_key_fixtures,
        preconditions=preconditions,
    )


def self_test(validator: Validator) -> int:
    catalog_registry_result = validator.validate_catalog_registry()
    golden_results = [
        validator.validate_path(validator.root / path) for path in GOLDEN_CARDS
    ]
    golden_text = {
        path: (validator.root / path).read_text(encoding="utf-8") for path in GOLDEN_CARDS
    }
    mutation_guard_raised = False
    try:
        guarded_replace(
            "no matching state token",
            "capability_state: needs_tool",
            "capability_state: live",
            "mutation-guard",
        )
    except AssertionError:
        mutation_guard_raised = True

    suite = build_self_test_fixtures(validator, golden_text)
    policy_positive_results = {
        name: validator.validate_text(text, f"<self-test-{name}>", None)
        for name, text in suite.positives.items()
    }
    negative_results = {
        name: validator.validate_text(text, f"<self-test-{name}>", None)
        for name, (text, _) in suite.negatives.items()
    }
    negative_codes = {
        name: {error["code"] for error in result["errors"]}
        for name, result in negative_results.items()
    }
    # Name the drift instead of leaving an expected-vs-actual set diff to decode.
    negative_failures: dict[str, dict[str, object]] = {}
    for name, (_, expected_codes) in suite.negatives.items():
        missing = sorted(expected_codes - negative_codes[name])
        if negative_results[name]["status"] == "fail" and not missing:
            continue
        negative_failures[name] = {
            "status": negative_results[name]["status"],
            "missing_codes": missing,
            "actual_codes": sorted(negative_codes[name]),
        }
    if "step-row-malformed" in negative_codes.get("bold-step-control", set()):
        negative_failures["bold-step-control"] = {
            "status": negative_results["bold-step-control"]["status"],
            "unexpected_codes": ["step-row-malformed"],
            "actual_codes": sorted(negative_codes["bold-step-control"]),
        }

    typed_failure_checks = {
        "401-auth": unavailable_reason([{"notes": "HTTP 401 Unauthorized"}]) == "auth",
        "403-auth": unavailable_reason([{"notes": "HTTP 403 auth_failed"}]) == "auth",
        "402-budget": unavailable_reason([{"notes": "HTTP 402 budget_exhausted"}]) == "budget",
        "429-rate": unavailable_reason([{"notes": "HTTP 429 rate_limited"}]) == "rate_limited",
    }
    golden_ok = all(result["status"] == "pass" for result in golden_results)
    negatives_ok = not negative_failures
    preconditions_ok = not suite.preconditions
    dead_reasons_ok = bool(suite.dead_key_fixtures) and all(
        negative_results[name]["derived_state"] == "needs_tool:auth"
        for name in suite.dead_key_fixtures
    )
    positives_ok = all(item["status"] == "pass" for item in policy_positive_results.values())
    typed_failures_ok = all(typed_failure_checks.values())
    result = {
        "type": "self-test",
        "status": (
            "pass"
            if catalog_registry_result["status"] == "pass"
            and golden_ok
            and negatives_ok
            and positives_ok
            and mutation_guard_raised
            and dead_reasons_ok
            and preconditions_ok
            and typed_failures_ok
            else "fail"
        ),
        "golden_statuses": {result["file"]: result["status"] for result in golden_results},
        "catalog_registry": catalog_registry_result,
        "positive_fixtures": {
            name: {
                "status": item["status"],
                "error_codes": sorted(error["code"] for error in item["errors"]),
            }
            for name, item in policy_positive_results.items()
        },
        "negative_fixtures": {
            name: {
                "status": item["status"],
                "error_codes": sorted(error["code"] for error in item["errors"]),
            }
            for name, item in negative_results.items()
        },
        "mutation_guard": "pass" if mutation_guard_raised else "fail",
        "dead_key_reason_checks": "pass" if dead_reasons_ok else "fail",
        "dead_key_fixtures": suite.dead_key_fixtures,
        "fixture_preconditions": "pass" if preconditions_ok else "fail",
        "typed_failure_checks": typed_failure_checks,
    }
    if not preconditions_ok:
        result["fixture_precondition_failures"] = suite.preconditions
    if not golden_ok:
        result["golden_failures"] = {
            item["file"]: item["errors"] for item in golden_results if item["status"] == "fail"
        }
    if not positives_ok:
        result["positive_failures"] = {
            name: item["errors"]
            for name, item in policy_positive_results.items()
            if item["status"] == "fail"
        }
    if negative_failures:
        result["negative_failures"] = negative_failures
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="capability files (default: discover all)")
    parser.add_argument("--root", type=Path, required=True, help="repository root")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run current golden cards and deliberately broken fixtures",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="add one-line HINT fields for recurring validation failures",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    publication_state = registry_publication_state(root)
    if publication_state != "published":
        return emit_registry_configuration(publication_state)
    try:
        validator = Validator(root)
    except (OSError, UnicodeError) as exc:
        print(
            json.dumps(
                {
                    "type": "configuration",
                    "status": "could-not-run",
                    "code": "registry-read",
                    "file": REGISTRY_RELATIVE.as_posix(),
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    if args.self_test:
        return self_test(validator)
    paths = resolve_paths(root, args.paths) if args.paths else discover(root)
    return emit_results(
        [
            validator.validate_catalog_registry(),
            *[validator.validate_path(path.resolve()) for path in paths],
        ],
        explain=args.explain,
    )


if __name__ == "__main__":
    sys.exit(main())
