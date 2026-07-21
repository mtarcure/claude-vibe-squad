#!/usr/bin/env python3
"""Single-pass specialist, routing, adapter, and tool-semantics validator."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RUNTIME_HEADER = [
    "specialist", "source_namespace", "capability_class", "safety_level",
    "safety_tags", "tool_profile", "primary_lane", "primary_profile",
    "backup_lane", "backup_profile", "escalate_lane", "escalate_profile",
    "escalation_policy", "review_lane", "review_profile", "anti_affinity",
    "throughput_lane", "throughput_profile", "throughput_policy",
    "failover_policy", "operator_gate", "heightened_risk", "requires_approval",
    "required_tools", "preferred_tools", "notes", "tags", "version",
    "operator_model_consult",
]
LEGACY_RUNTIME_HEADER = RUNTIME_HEADER[:-1]
PROFILE_HEADER = ["profile_id", "lane", "model_id", "effort", "flags", "usage"]
POLICY_HEADER = ["policy_id", "family", "description"]
TOOL_HEADER = ["name", "record_kind", "type", "path_or_source", "lanes", "invocation",
               "verified_state", "cost_tier", "evidence", "notes"]
LANE_POLICY_HEADER = ["record_kind", "subject", "value", "scope", "notes"]
REQUIRED_SECTIONS = (
    "## Tools available to me", "## When to fan out", "## When to escalate",
    "## What I do NOT do",
)
STALE_ROUTE_NAMES = (
    "quick-lookup", "scope-checker", "legal-guard", "code-auditor",
    "variant-analyst", "chain-constructor", "cvss-scorer", "product-analyst",
    "repo-scout",
)
KNOWN_OPERATIONS = {
    "firecrawl": {"scrape"},
    "chrono-vault": {"recall"},
    "chrono-media-studio": {
        "elevenlabs__compose_music", "elevenlabs__video_to_music",
        "elevenlabs__upload_music_for_inpainting", "elevenlabs__text_to_sound_effects",
        "elevenlabs__create_agent", "elevenlabs__add_knowledge_base_to_agent",
        "elevenlabs__text_to_speech", "elevenlabs__voice_clone",
        "elevenlabs__speech_to_speech",
    },
}


@dataclass(frozen=True)
class Finding:
    file: str
    status: str
    issues: list[str]


def read_tsv(path: Path) -> list[list[str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle, delimiter="\t"))


def bracket_list(value: str) -> list[str] | None:
    if not (value.startswith("[") and value.endswith("]")):
        return None
    body = value[1:-1]
    if not body:
        return []
    items = [item.strip() for item in body.split(",")]
    return items if all(items) else None


def json_line(finding: Finding) -> str:
    return json.dumps({"file": finding.file, "status": finding.status,
                       "issues": finding.issues}, separators=(",", ":"))


def section(text: str, heading_pattern: str, level: str = "###") -> str:
    lines = text.splitlines()
    active = False
    selected: list[str] = []
    start = re.compile(heading_pattern)
    for line in lines:
        if not active and start.match(line):
            active = True
            continue
        if active and line.startswith(level + " "):
            break
        if active:
            selected.append(line)
    return "\n".join(selected)


class Validator:
    def __init__(self, root: Path, expected_rows: int | None = None,
                 strict_adapters: bool = False):
        self.root = root.resolve()
        self.expected_rows = expected_rows
        self.strict_adapters = strict_adapters
        self.findings: list[Finding] = []
        self.total = self.passed = 0

        self.runtime_path = self.root / "shared/specialist-runtime-map.tsv"
        self.profile_path = self.root / "shared/registries/profiles.tsv"
        self.policy_path = self.root / "shared/registries/policies.tsv"
        self.tool_path = self.root / "shared/registries/skill-tool-registry.tsv"
        self.lane_policy_path = self.root / "shared/lane-policy.tsv"
        bundled_lane_policy = Path(__file__).resolve().parents[2] / "shared/lane-policy.tsv"
        if not self.lane_policy_path.is_file() and bundled_lane_policy.is_file():
            # Hermetic validator fixtures intentionally construct only the registry
            # under test. Reuse this validator build's canonical policy data instead
            # of reintroducing policy/vocabulary literals into Python. A real vault
            # missing its own table has no distinct bundled path and still fails.
            self.lane_policy_path = bundled_lane_policy
        self.runtime = read_tsv(self.runtime_path)
        self.profiles = read_tsv(self.profile_path)
        self.policies = read_tsv(self.policy_path)
        self.tools = read_tsv(self.tool_path)
        self.lane_policy = read_tsv(self.lane_policy_path)
        self.profile_by_id = self.index(self.profiles)
        self.policy_by_id = self.index(self.policies)
        self.tool_by_name = {row[0]: row for row in self.tools[1:]
                             if len(row) == len(TOOL_HEADER) and row[1] == "tool"}
        self.specialist_files = self.discover_specialists()
        self.specialist_names = {path.stem for path in self.specialist_files}

    def policy_rows(self, record_kind: str, subject: str | None = None) -> list[list[str]]:
        return [row for row in self.lane_policy[1:]
                if len(row) == len(LANE_POLICY_HEADER) and row[0] == record_kind
                and (subject is None or row[1] == subject)]

    def vocabulary(self, subject: str) -> set[str]:
        return {row[2] for row in self.policy_rows("vocabulary", subject)}

    def primary_allowed(self, lane: str, specialist: str) -> bool:
        defaults = self.policy_rows("primary_default", lane)
        allowed = bool(defaults and defaults[-1][2] == "allow")
        for row in self.policy_rows("primary_exception", lane):
            if row[3] == specialist:
                allowed = row[2] == "allow"
        return allowed

    @staticmethod
    def index(rows: list[list[str]]) -> dict[str, list[str]]:
        return {row[0]: row for row in rows[1:] if row and row[0]}

    @staticmethod
    def normalize_runtime_row(row: list[str]) -> list[str] | None:
        """Return the 29-field semantic row, defaulting the optional flag false."""
        if len(row) == len(LEGACY_RUNTIME_HEADER):
            return [*row, "false"]
        if len(row) == len(RUNTIME_HEADER):
            normalized = list(row)
            normalized[-1] = normalized[-1] or "false"
            return normalized
        return None

    def normalized_runtime_rows(self) -> list[list[str]]:
        if not self.runtime:
            return []
        header = self.runtime[0]
        if header == RUNTIME_HEADER:
            width = len(RUNTIME_HEADER)
        elif header == LEGACY_RUNTIME_HEADER:
            width = len(LEGACY_RUNTIME_HEADER)
        else:
            return []
        return [normalized for row in self.runtime[1:]
                if len(row) == width
                and (normalized := self.normalize_runtime_row(row)) is not None]

    def add(self, path: Path | str, status: str, *issues: str) -> None:
        self.findings.append(Finding(str(path), status, list(issues)))

    def discover_specialists(self) -> list[Path]:
        paths = list(self.root.glob("departments/*/specialists/*.md"))
        paths.extend(self.root.glob("shared/specialists/*.md"))
        return sorted(set(paths), key=lambda p: str(p))

    def validate_registry(self, path: Path, rows: list[list[str]], header: list[str],
                          allowed: set[str] | None = None) -> None:
        issues: list[str] = []
        if not path.is_file():
            self.add(path, "fail", "missing-registry")
            return
        if not rows or rows[0] != header:
            issues.append("wrong-registry-header")
        bad = [f"{n}:{len(row)}" for n, row in enumerate(rows, 1) if len(row) != len(header)]
        if bad:
            issues.append("wrong-registry-column-count:" + ",".join(bad))
        ids = [row[0] for row in rows[1:] if row]
        if header == TOOL_HEADER:
            identities = [(row[0], row[1], row[2]) for row in rows[1:] if len(row) >= 3]
            duplicates = sorted({name for name, kind, record_type in identities
                                 if identities.count((name, kind, record_type)) > 1})
        elif header == LANE_POLICY_HEADER:
            identities = [tuple(row[:4]) for row in rows[1:] if len(row) == len(header)]
            duplicates = sorted({":".join(item) for item in identities
                                 if identities.count(item) > 1})
        else:
            duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            issues.append("duplicate-registry-ids:" + ",".join(duplicates))
        if header in (PROFILE_HEADER, POLICY_HEADER) and ids != sorted(ids):
            issues.append("registry-not-sorted")
        if allowed:
            for row in rows[1:]:
                if len(row) > 1 and row[1] not in allowed:
                    issues.append(f"invalid-registry-value:{row[0]}:{row[1]}")
                    break
        if issues:
            self.add(path, "fail", *issues)

    def validate_registries(self) -> None:
        self.validate_registry(self.profile_path, self.profiles, PROFILE_HEADER,
                               {"codex", "claude", "gemini", "kimi"})
        self.validate_registry(self.policy_path, self.policies, POLICY_HEADER,
                               {"escalation", "failover", "throughput"})
        self.validate_registry(self.tool_path, self.tools, TOOL_HEADER)
        self.validate_registry(self.lane_policy_path, self.lane_policy, LANE_POLICY_HEADER)

    @staticmethod
    def degradation_documented(tool: str, notes: str) -> bool:
        if not notes.strip():
            return False
        lower = notes.lower()
        signals = ("degrades[", "fallback", "handoff", "when unavailable", "needs_tool",
                   "partial", "limited", "schema-only", "blueprint", "requires",
                   "unverified", "optional", "read-only")
        primary_token = re.split(r"[^a-z0-9]+", tool.lower(), maxsplit=1)[0]
        explicit_marker = f"degrades[{tool.lower()}]=" in lower
        return (explicit_marker or primary_token in lower) and any(signal in lower for signal in signals)

    def validate_operations(self, row_id: str, required: list[str], preferred: list[str],
                            notes: str, issues: list[str]) -> None:
        references = set(required + preferred)
        seen: dict[str, set[str]] = {}
        for root, operation_text in re.findall(r"operations\[([^\]]+)\]=([^;]+)", notes):
            operations = {op.strip().rstrip(".") for op in operation_text.split("|") if op.strip()}
            seen.setdefault(root, set()).update(operations)
            if root not in references:
                issues.append(f"operation-root-not-referenced:{root}")
            known = KNOWN_OPERATIONS.get(root)
            if known is None:
                issues.append(f"unknown-operation-root:{root}")
            else:
                for operation in sorted(operations - known):
                    issues.append(f"unknown-operation:{root}:{operation}")
        for root in references & KNOWN_OPERATIONS.keys():
            # Roots can be used as families without an operation. An explicit clause,
            # when present, is strict and proves normalized child operations resolve.
            if root in seen and not seen[root]:
                issues.append(f"empty-operation-list:{root}")

    def validate_tool(self, specialist: str, kind: str, tool: str, routes: set[str],
                      notes: str, issues: list[str]) -> None:
        if ":" in tool and tool not in self.tool_by_name:
            issues.append(f"ambiguous-namespaced-tool:{kind}:{tool}")
            return
        record = self.tool_by_name.get(tool)
        if record is None or len(record) != len(TOOL_HEADER):
            issues.append(f"unresolved-tool-reference:{kind}:{tool}")
            return
        record_type, lanes, state = record[2], set(record[4].split("|")), record[6]
        retired = record_type == "retired-mcp"
        if kind == "required":
            if retired or state in {"no", "stale"}:
                issues.append(f"unusable-required-tool:{tool}:{state}:{record_type}")
            if "all" not in lanes and not (lanes & routes):
                issues.append(f"required-tool-wrong-lane:{tool}:{record[4]}")
        else:
            if retired or state in {"no", "stale"}:
                issues.append(f"unusable-preferred-tool:{tool}:{state}:{record_type}")
            if state == "partial" and not self.degradation_documented(tool, notes):
                issues.append(f"partial-preferred-missing-degradation:{tool}")
            if "all" not in lanes and not (lanes & routes) and not self.degradation_documented(tool, notes):
                issues.append(f"preferred-tool-wrong-lane-without-handoff:{tool}:{record[4]}")

    def validate_runtime(self) -> None:
        if not self.runtime_path.is_file():
            self.add(self.runtime_path, "fail", "missing-runtime-map")
            return
        if not self.profiles or not self.policies or not self.tools:
            self.add(self.runtime_path, "fail", "cannot-validate-map-without-registries")
            return
        global_issues: list[str] = []
        if not self.runtime or self.runtime[0] not in (RUNTIME_HEADER, LEGACY_RUNTIME_HEADER):
            global_issues.append("wrong-runtime-map-header")
        data = self.runtime[1:]
        if self.expected_rows is not None and len(data) != self.expected_rows:
            global_issues.append(f"wrong-row-count:{len(data)}-expected-{self.expected_rows}")
        header_width = (len(self.runtime[0]) if self.runtime
                        and self.runtime[0] in (RUNTIME_HEADER, LEGACY_RUNTIME_HEADER)
                        else len(RUNTIME_HEADER))
        bad = [f"{n}:{len(row)}" for n, row in enumerate(self.runtime, 1)
               if len(row) != header_width]
        if bad:
            global_issues.append("wrong-column-count:" + ",".join(bad))
        names = [row[0] for row in data if row]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            global_issues.append("duplicate-specialists:" + ",".join(duplicates))
        if names != sorted(names):
            global_issues.append("runtime-map-not-sorted")
        if global_issues:
            self.add(self.runtime_path, "fail", *global_issues)

        namespaces = self.vocabulary("source_namespace")
        capabilities = self.vocabulary("capability_class")
        safety_levels = self.vocabulary("safety_level")
        safety_tag_values = self.vocabulary("safety_tag")
        tool_profiles = self.vocabulary("tool_profile")
        route_lanes = self.vocabulary("route_lane")
        throughput_lanes = self.vocabulary("throughput_lane")
        anti_affinities = self.vocabulary("anti_affinity")
        allowed_gates = self.vocabulary("operator_gate")
        heightened_roles = {row[1] for row in self.policy_rows("heightened_role")
                            if row[2] == "true"}
        required_vocabularies = {
            "source_namespace": namespaces,
            "capability_class": capabilities,
            "safety_level": safety_levels,
            "safety_tag": safety_tag_values,
            "tool_profile": tool_profiles,
            "route_lane": route_lanes,
            "throughput_lane": throughput_lanes,
            "anti_affinity": anti_affinities,
            "operator_gate": allowed_gates,
        }
        for vocabulary_name, values in required_vocabularies.items():
            if not values:
                self.add(self.lane_policy_path, "fail",
                         f"missing-vocabulary:{vocabulary_name}")

        for raw_row in data:
            if len(raw_row) != header_width:
                continue
            row = self.normalize_runtime_row(raw_row)
            if row is None:
                continue
            (name, namespace, capability, safety, safety_tags, tool_profile,
             primary_lane, primary_profile, backup_lane, backup_profile,
             escalate_lane, escalate_profile, escalation_policy, review_lane,
             review_profile, anti_affinity, throughput_lane, throughput_profile,
             throughput_policy, failover_policy, operator_gate, heightened,
             requires_approval, required_text, preferred_text, notes, tags, version,
             operator_model_consult) = row
            issues: list[str] = []
            if namespace not in namespaces:
                issues.append(f"invalid-source-namespace:{namespace}")
            if capability not in capabilities:
                issues.append(f"invalid-capability-class:{capability}")
            if safety not in safety_levels:
                issues.append(f"invalid-safety-level:{safety}")
            parsed_safety = bracket_list(safety_tags)
            if parsed_safety is None or not set(parsed_safety) <= safety_tag_values:
                issues.append(f"invalid-safety-tags:{safety_tags}")
            if tool_profile not in tool_profiles:
                issues.append(f"invalid-tool-profile:{tool_profile}")
            routes = {primary_lane, backup_lane, escalate_lane, review_lane}
            for lane in (primary_lane, backup_lane, escalate_lane, review_lane):
                if lane not in route_lanes:
                    issues.append(f"invalid-routing-lane:{lane}")
            if throughput_lane not in throughput_lanes:
                issues.append(f"invalid-throughput-lane:{throughput_lane}")
            if throughput_lane != "none":
                routes.add(throughput_lane)
            if not self.primary_allowed(primary_lane, name):
                issues.append(f"primary-lane-forbidden:{primary_lane}:{name}")
            if primary_lane == backup_lane:
                issues.append(f"primary-backup-same-lane:{primary_lane}")
            for lane, profile in ((primary_lane, primary_profile), (backup_lane, backup_profile),
                                  (escalate_lane, escalate_profile), (review_lane, review_profile)):
                record = self.profile_by_id.get(profile)
                if record is None:
                    issues.append(f"unknown-profile:{profile}")
                elif len(record) > 1 and record[1] != lane:
                    issues.append(f"profile-lane-mismatch:{lane}:{profile}")
            if anti_affinity not in anti_affinities:
                issues.append(f"invalid-anti-affinity:{anti_affinity}")
            if heightened not in {"true", "false"}:
                issues.append(f"invalid-heightened-risk:{heightened}")
            expected_heightened = "true" if name in heightened_roles else "false"
            if heightened != expected_heightened:
                issues.append(f"heightened-risk-mismatch:{heightened}-expected-{expected_heightened}")
            for family, policy in (("escalation", escalation_policy),
                                   ("throughput", throughput_policy), ("failover", failover_policy)):
                record = self.policy_by_id.get(policy)
                if record is None:
                    issues.append(f"unknown-policy:{policy}")
                elif len(record) > 1 and record[1] != family:
                    issues.append(f"policy-family-mismatch:{family}:{policy}")
            if failover_policy != "failover.conservative.v1":
                issues.append(f"invalid-failover-policy:{failover_policy}")
            risk = safety == "high" or heightened == "true"
            if risk:
                if escalation_policy != "escalation.safety_floor.v1":
                    issues.append("risk-requires-safety-floor")
                if not (throughput_policy == "throughput.never.v1" and
                        throughput_lane == throughput_profile == "none"):
                    issues.append("risk-forbids-throughput")
            else:
                if escalation_policy != "escalation.signal.v1":
                    issues.append("non-heightened-requires-signal-escalation")
                if safety == "medium":
                    if not (throughput_policy == "throughput.never.v1" and
                            throughput_lane == throughput_profile == "none"):
                        issues.append("medium-safety-forbids-throughput")
                elif throughput_policy == "throughput.downshift_gated.v1":
                    if not (throughput_lane == "kimi" and throughput_profile == "kimi.k2.7.bulk"):
                        issues.append("gated-throughput-requires-kimi-profile")
                    if safety_tags != "[]":
                        issues.append("sensitive-tag-forbids-throughput")
                elif throughput_policy == "throughput.never.v1":
                    if throughput_lane != "none" or throughput_profile != "none":
                        issues.append("never-throughput-requires-none")
                else:
                    issues.append(f"invalid-low-safety-throughput-policy:{throughput_policy}")
            gate = bracket_list(operator_gate)
            if gate is None or not set(gate) <= allowed_gates:
                issues.append(f"invalid-operator-gate:{operator_gate}")
            if bracket_list(requires_approval) is None:
                issues.append(f"invalid-requires-approval:{requires_approval}")
            required = bracket_list(required_text)
            preferred = bracket_list(preferred_text)
            if required is None:
                issues.append(f"invalid-required-tools:{required_text}")
                required = []
            if preferred is None:
                issues.append(f"invalid-preferred-tools:{preferred_text}")
                preferred = []
            for tool in required:
                self.validate_tool(name, "required", tool, routes, notes, issues)
            for tool in preferred:
                self.validate_tool(name, "preferred", tool, routes, notes, issues)
            self.validate_operations(name, required, preferred, notes, issues)
            if bracket_list(tags) is None:
                issues.append(f"invalid-tags:{tags}")
            if not notes:
                issues.append("missing-notes")
            if not re.fullmatch(r"[0-9]+\.[0-9]+", version):
                issues.append(f"invalid-version:{version}")
            if operator_model_consult not in {"true", "false"}:
                issues.append(f"invalid-operator-model-consult:{operator_model_consult}")
            if name not in self.specialist_names:
                issues.append(f"map-specialist-file-missing:{name}")
            if issues:
                self.add(f"{self.runtime_path}:{name}", "fail", *issues)

    def verified_mcps(self) -> set[str]:
        catalog = self.root / "shared/api-catalog.md"
        if not catalog.is_file():
            return set()
        current = ""
        pane_pending = False
        selected: list[str] = []
        for line in catalog.read_text(encoding="utf-8").splitlines():
            if line.startswith("### "):
                current = line
                pane_pending = False
            elif line.startswith("- verified: yes"):
                selected.append(current)
            elif "verified per pane:" in line:
                pane_pending = True
            elif pane_pending:
                if "yes" in line:
                    selected.append(current)
                pane_pending = False
        pattern = re.compile(r"chrono-[a-z-]+|sequential-?thinking|playwright|chrome-devtools|context7|perplexity|elevenlabs|figma|firebase|sentry|linear|search|computer-use")
        return {match for text in selected for match in pattern.findall(text)}

    def local_skills(self) -> set[str]:
        skills: set[str] = set()
        shared = self.root / "shared/skills"
        if shared.is_dir():
            skills.update(path.stem for path in shared.glob("*.md"))
            catalog = shared / "catalog.txt"
            if catalog.is_file():
                skills.update(line.strip() for line in catalog.read_text().splitlines()
                              if line.strip() and not line.lstrip().startswith("#"))
        return skills

    def validate_specialists(self) -> None:
        verified = self.verified_mcps()
        skills = self.local_skills()
        for path in self.specialist_files:
            self.total += 1
            text = path.read_text(encoding="utf-8")
            issues: list[str] = []
            for heading in REQUIRED_SECTIONS:
                if heading not in text:
                    issues.append(f"missing-section: {heading}")
            if "<FILL:" in text:
                issues.append("fill-placeholder-present")
            if not any(row[0] == path.stem for row in self.normalized_runtime_rows()):
                issues.append(f"missing-runtime-map-entry:{path.stem}")
            mcp_block = section(text, r"^### (Expected )?MCPs")
            for mcp in sorted(set(re.findall(r"^\s*-\s*`([a-z][a-z-]*)`", mcp_block, re.M)) - {"FILL"}):
                if mcp not in verified:
                    issues.append(f"unverified-mcp: {mcp}")
            skill_block = section(text, r"^### Skills")
            for skill in sorted(set(re.findall(r"`([a-z][a-z0-9_-]*)`", skill_block)) -
                                {"FILL", "capability_gap", "needs_tool"}):
                if skill not in skills and f"`{skill}` (proposed" not in skill_block:
                    issues.append(f"missing-skill: {skill}")
                elif skill not in skills:
                    self.add(path, "warn", f"proposed-skill-not-registered:{skill}")
            fanout = section(text, r"^## When to fan out", level="##")
            for peer in sorted(set(re.findall(r"`([a-z][a-z-]*)`", fanout)) - {"FILL"}):
                if peer not in self.specialist_names:
                    self.add(path, "warn", f"unresolved-peer-reference:{peer}")
            if issues:
                self.add(path, "fail", *issues)
            else:
                self.add(path, "pass")
                self.passed += 1

    def validate_adapters(self) -> None:
        adapter_policies = {row[1]: row for row in self.policy_rows("adapter_template")}
        for row in self.normalized_runtime_rows():
            name, lane = row[0], row[6]
            issue = ""
            policy = adapter_policies.get(lane)
            if policy is None:
                self.add(self.lane_policy_path, "fail",
                         f"missing-adapter-template:{lane}")
                continue
            template, name_format = policy[2], policy[3]
            try:
                relative = template.format(specialist=name)
            except (KeyError, ValueError):
                self.add(self.lane_policy_path, "fail",
                         f"invalid-adapter-template:{lane}:{template}")
                continue
            path = self.root / relative
            if not path.is_file():
                issue = f"missing-{lane}-agent-adapter:{name}"
            elif name_format == "underscore_toml_name":
                expected = name.replace("-", "_")
                if f'name = "{expected}"' not in path.read_text(encoding="utf-8"):
                    issue = f"codex-agent-name-mismatch:{name}"
            elif name_format == "exact_frontmatter_name":
                text = path.read_text(encoding="utf-8")
                if not text.startswith("---\n"):
                    issue = f"{lane}-agent-missing-frontmatter:{name}"
                elif not re.search(rf"^name: {re.escape(name)}$", text, re.M):
                    issue = f"{lane}-agent-name-mismatch:{name}"
            elif name_format == "main_yaml_registration":
                main = self.root / "model-lanes/kimi/main.yaml"
                if not main.is_file() or not re.search(
                        rf"^\s*{re.escape(name)}:", main.read_text(encoding="utf-8"), re.M):
                    issue = f"kimi-main-missing-subagent:{name}"
            elif name_format != "frontmatter_optional":
                issue = f"unknown-adapter-name-format:{lane}:{name_format}"
            if issue:
                self.add(f"{self.runtime_path}:{name}",
                         "fail" if self.strict_adapters else "warn", issue)
        for path in sorted(self.root.glob("model-lanes/gemini/.gemini/agents/*.md")):
            if not path.read_text(encoding="utf-8").startswith("---\n"):
                self.add(path, "fail", f"gemini-agent-file-missing-frontmatter:{path.name}")

    def validate_routes(self) -> None:
        paths = list(self.root.glob("shared/modes/*.md"))
        paths.extend(self.root.glob("departments/*/NAMESPACE.md"))
        paths.extend(self.root / rel for rel in ("chrono/CLAUDE.md", "chrono/operator-setup.md",
                                                 "chrono/SPECIALIST-INDEX.md"))
        for path in sorted(set(paths), key=str):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            issues: list[str] = []
            for stale in STALE_ROUTE_NAMES:
                token = rf"(?<![A-Za-z0-9_-]){re.escape(stale)}(?![A-Za-z0-9_-])"
                if re.search(rf"subagent_type={re.escape(stale)}(?![A-Za-z0-9_-])|@{token}|{token}", text):
                    issues.append(f"stale-route-reference:{stale}")
            if path.parent == self.root / "shared/modes" and "vibecoding-check" not in text:
                issues.append("mode-missing-vibecoding-check")
            for ref in sorted(set(re.findall(r"subagent_type=([A-Za-z0-9_-]+)", text))):
                canonical = ref.replace("_", "-")
                if canonical not in self.specialist_names:
                    issues.append(f"missing-subagent-reference:{ref}")
            for ref in sorted(set(re.findall(r"@([a-z][a-z0-9-]+)", text))):
                if ref not in self.specialist_names:
                    issues.append(f"missing-at-reference:{ref}")
            if issues:
                self.add(path, "fail", *issues)

    def run(self) -> tuple[list[Finding], str, int]:
        self.validate_registries()
        self.validate_runtime()
        self.validate_specialists()
        self.validate_adapters()
        self.validate_routes()
        failed = sum(item.status == "fail" for item in self.findings)
        warnings = sum(item.status == "warn" for item in self.findings)
        summary = (f"Total: {self.total}  Passed: {self.passed}  Failed: {failed}  "
                   f"Warnings(non-fatal): {warnings}")
        return self.findings, summary, int(failed > 0)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get(
        "VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad")))
    expected_rows_env = os.environ.get("EXPECTED_RUNTIME_ROWS")
    parser.add_argument(
        "--expected-runtime-rows",
        type=int,
        default=int(expected_rows_env) if expected_rows_env else None,
        help="optional migration assertion; normal validation derives the row set from the map",
    )
    parser.add_argument("--quiet", action="store_true", help="accepted for shell compatibility")
    args = parser.parse_args(list(argv) if argv is not None else None)
    validator = Validator(args.root, args.expected_runtime_rows,
                          os.environ.get("STRICT_ADAPTERS", "0") == "1")
    findings, summary, code = validator.run()
    for finding in findings:
        print(json_line(finding))
    print(file=sys.stderr)
    print(summary, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
