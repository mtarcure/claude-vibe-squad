#!/usr/bin/env python3
"""Validate capability cards against the locked schema and runtime registries."""

from __future__ import annotations

import argparse
import csv
import json
import re
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
        registry = read_tsv(root / "shared/registries/skill-tool-registry.tsv")
        self.tools: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.skills: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in registry:
            target = self.tools if row["record_kind"] == "tool" else self.skills
            target[row["name"]].append(row)
        runtime_rows = read_tsv(root / "shared/specialist-runtime-map.tsv")
        self.specialists = Counter(row["specialist"] for row in runtime_rows)

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
    return sorted(path for path in base.rglob("*.md") if not path.name.startswith("_"))


def resolve_paths(root: Path, values: Iterable[str]) -> list[Path]:
    paths = []
    for value in values:
        path = Path(value)
        paths.append(path if path.is_absolute() else root / path)
    return paths


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


def self_test(validator: Validator) -> int:
    golden = [
        validator.root / "shared/capabilities/project/web-app.md",
        validator.root / "shared/capabilities/bounty/smart-contract-web3.md",
        validator.root / "shared/capabilities/content/image.md",
        validator.root / "shared/capabilities/project/self-extension-agent-tooling.md",
        validator.root / "shared/capabilities/project/ai-llm-application.md",
        validator.root / "shared/capabilities/project/backend-service-api.md",
        validator.root / "shared/capabilities/project/data-pipeline.md",
        validator.root / "shared/capabilities/project/platform-release.md",
        validator.root / "shared/capabilities/project/smart-contract-web3.md",
        validator.root / "shared/capabilities/project/systems-low-level.md",
    ]
    golden_results = [validator.validate_path(path) for path in golden]
    golden_text = {
        path.relative_to(validator.root).as_posix(): path.read_text(encoding="utf-8")
        for path in golden
    }
    broken = """---
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
| **S0** | `phantom-specialist` | `missing-tool` (codex · yes · subscription) | `requirements-elicitation` (authored) | Bad input |
| **S7** | `Chrono` | — | — | Done |
"""
    unbolded_exploit = """---
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
| S3 Produce | `phantom-specialist` | `evil-tool` (claude · yes · subscription) | `fake-skill` (authored) | — |
| **S7** Capture | `Chrono` | — | — | — |
"""
    bold_exploit_control = unbolded_exploit.replace("| S3 Produce |", "| **S3** Produce |", 1)
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
        "| **S3** Produce | `phantom-specialist` | "
        "`evil-tool` (claude · yes · subscription) | `fake-skill` (authored) | — |"
    )
    out_of_block_after = (
        f"{out_of_block_frontmatter}\n{canonical_minimal_table}\n\n{out_of_block_payload}\n"
    )
    out_of_block_before = (
        f"{out_of_block_frontmatter}\n{out_of_block_payload}\n{canonical_minimal_table}\n"
    )
    out_of_block_unbolded_after = out_of_block_after.replace(
        "| **S3** Produce |", "| S3 Produce |", 1
    )

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

    dead_digitalocean_base = policy_fixture(
        "dead-digitalocean",
        "needs_tool",
        "`DigitalOcean API` (none · no · unknown)",
    )
    state_overclaim_fixture = guarded_replace(
        dead_digitalocean_base,
        "capability_state: needs_tool",
        "capability_state: live",
        "state-overclaim",
    )
    mutation_guard_raised = False
    try:
        guarded_replace("no matching state token", "capability_state: needs_tool", "capability_state: live", "mutation-guard")
    except AssertionError:
        mutation_guard_raised = True

    policy_positive_fixtures = {
        "grounding-live-positive": policy_fixture(
            "grounding-live-positive",
            "live",
            "`Google Search grounding` (gemini · yes · subscription)",
            "claim_to_citation=true reject_unsupported=true",
        ),
        "perplexity-valid-truth-gate": policy_fixture(
            "perplexity-valid-truth-gate",
            "degraded-blueprint",
            "`Perplexity Sonar structured+recency` (codex · partial · metered)",
            "claim_to_citation=true date_window=24h reject_unsupported=true",
            "metered with budget ceiling",
        ),
        "higgs-free-read-positive": policy_fixture(
            "higgs-free-read-positive",
            "degraded-blueprint",
            "`higgsfield__models_explore` (claude · partial · —)",
        ),
        "kimi-metered-bounded": policy_fixture(
            "kimi-metered-bounded",
            "live",
            "`xai_search` (kimi · lane-live · metered)",
            "external-budget-ceiling=5calls",
            "metered with budget ceiling",
        ),
    }
    negative_fixtures = {
        "composite": (
            broken,
            {"specialist-registry", "tool-catalog-claim", "skill-registry-mismatch"},
        ),
        "multi-lane": (
            golden_text["shared/capabilities/project/web-app.md"].replace(
                "(claude · lane-live · subscription)",
                "(claude+codex · lane-live · subscription)",
                1,
            ),
            {"tool-lane-invalid"},
        ),
        "registry-mismatch": (
            golden_text["shared/capabilities/project/self-extension-agent-tooling.md"].replace(
                "(all · yes · subscription)", "(all · yes · unknown)", 1
            ),
            {"tool-registry-mismatch"},
        ),
        "state-overclaim": (
            state_overclaim_fixture,
            {"capability-state-overclaim"},
        ),
        "metered-without-guard": (
            re.sub(
                r"(?m)^cost_note:.*$",
                "cost_note: —",
                golden_text["shared/capabilities/bounty/smart-contract-web3.md"],
                count=1,
            ),
            {"metered-cost-note"},
        ),
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
        "step-row-after-block": (
            out_of_block_after,
            {"step-row-out-of-block"},
        ),
        "step-row-before-header": (
            out_of_block_before,
            {"step-row-out-of-block"},
        ),
        "unbolded-step-row-after-block": (
            out_of_block_unbolded_after,
            {"step-row-out-of-block"},
        ),
        "dead-digitalocean-negative": (
            state_overclaim_fixture,
            {"capability-state-overclaim"},
        ),
        "dead-twitter-negative": (
            policy_fixture(
                "dead-twitter-negative",
                "live",
                "`Twitter API v2` (none · no · unknown)",
            ),
            {"capability-state-overclaim"},
        ),
        "perplexity-missing-truth-gate": (
            policy_fixture(
                "perplexity-missing-truth-gate",
                "degraded-blueprint",
                "`Perplexity Sonar structured+recency` (codex · partial · metered)",
                "paid research",
                "metered with budget ceiling",
            ),
            {"perplexity-truth-gate-missing"},
        ),
        "higgs-raw-generation-negative": (
            policy_fixture(
                "higgs-raw-generation-negative",
                "live",
                "`Higgsfield raw generation` (none · no · metered)",
                "paid_media get_cost:true",
                "metered with budget ceiling",
            ),
            {"capability-state-overclaim", "higgsfield-raw-generation-unavailable"},
        ),
        "higgs-paid-without-cost-preflight": (
            policy_fixture(
                "higgs-paid-without-cost-preflight",
                "degraded-blueprint",
                "`higgsfield__upscale_image` (claude · partial · metered)",
                "paid_media",
                "metered with budget ceiling",
            ),
            {"higgsfield-cost-preflight-missing"},
        ),
        "kimi-metered-unbounded": (
            policy_fixture(
                "kimi-metered-unbounded",
                "live",
                "`xai_search` (kimi · lane-live · metered)",
                "budget discussed in prose",
                "metered with budget ceiling",
            ),
            {"external-budget-ceiling-missing"},
        ),
    }
    policy_positive_results = {
        name: validator.validate_text(text, f"<self-test-{name}>", None)
        for name, text in policy_positive_fixtures.items()
    }
    negative_results = {
        name: validator.validate_text(text, f"<self-test-{name}>", None)
        for name, (text, _) in negative_fixtures.items()
    }
    typed_failure_checks = {
        "401-auth": unavailable_reason([{"notes": "HTTP 401 Unauthorized"}]) == "auth",
        "403-auth": unavailable_reason([{"notes": "HTTP 403 auth_failed"}]) == "auth",
        "402-budget": unavailable_reason([{"notes": "HTTP 402 budget_exhausted"}]) == "budget",
        "429-rate": unavailable_reason([{"notes": "HTTP 429 rate_limited"}]) == "rate_limited",
    }
    golden_ok = all(result["status"] == "pass" for result in golden_results)
    negatives_ok = all(
        result["status"] == "fail"
        and expected_codes.issubset({error["code"] for error in result["errors"]})
        for name, (_, expected_codes) in negative_fixtures.items()
        for result in [negative_results[name]]
    )
    negatives_ok = negatives_ok and "step-row-malformed" not in {
        error["code"] for error in negative_results["bold-step-control"]["errors"]
    }
    dead_reasons_ok = all(
        negative_results[name]["derived_state"] == "needs_tool:auth"
        for name in ("dead-digitalocean-negative", "dead-twitter-negative")
    )
    positives_ok = all(item["status"] == "pass" for item in policy_positive_results.values())
    typed_failures_ok = all(typed_failure_checks.values())
    result = {
        "type": "self-test",
        "status": (
            "pass"
            if golden_ok
            and negatives_ok
            and positives_ok
            and mutation_guard_raised
            and dead_reasons_ok
            and typed_failures_ok
            else "fail"
        ),
        "golden_statuses": {result["file"]: result["status"] for result in golden_results},
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
        "typed_failure_checks": typed_failure_checks,
    }
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
    validator = Validator(root)
    if args.self_test:
        return self_test(validator)
    paths = resolve_paths(root, args.paths) if args.paths else discover(root)
    return emit_results(
        [validator.validate_path(path.resolve()) for path in paths], explain=args.explain
    )


if __name__ == "__main__":
    sys.exit(main())
