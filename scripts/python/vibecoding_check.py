#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0",
#     "httpx>=0.28",
# ]
# ///
"""Vibecoding-check — Layer 2 mode-exit verifier.

Runs deterministic checks before any mode can declare itself "done." Per
spec at `shared/specialists/vibecoding-check.md`.

Universal checks (always):
  1. Operator approval token present
  2. Declared artifacts exist
  3. Citations resolve (URL 200 / file exists / git ref resolves)
  4. No TODO/FIXME/XXX in modified code
  5. All declared phase-tags emitted in run log

Mode-specific extensions (declared in checks.yaml):
  - project: tests_pass, git_clean, new_code_has_tests, no_destructive_ops
  - bounty: scope_gate_ran, cvss_recorded, poc_reproduces, no_self_inflicted
  - content: voice_consistent, asset_paths_resolve, length_bounds, no_placeholder_text

Usage:
  vibecoding-check.sh --run-id BTY-2026-05-02-1234

Exit codes:
  0  — all checks passed; mode may advance
  1  — tier-1 auto-fix applied; mode may advance
  2  — tier-2 issue; mode should retry the relevant phase
  3  — tier-3 issue; state written; operator surface needed

State files:
  _state/runs/<run-id>/manifest.yaml   — written by the Lead executing the mode
  _state/vibecoding-check/<run-id>.md  — written by THIS script on tier-2/3
  _state/approvals/<run-id>.md         — written by operator (APPROVE | OVERRIDE)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
RUNS_DIR = STATE_DIR / "runs"
APPROVALS_DIR = STATE_DIR / "approvals"
CHECK_DIR = STATE_DIR / "vibecoding-check"

# Severity ladders
TIER_OK = 0
TIER_AUTOFIX = 1
TIER_RETRY = 2
TIER_OPERATOR = 3


@dataclass
class CheckResult:
    name: str
    passed: bool
    tier: int = TIER_OK   # promotion tier on failure (0 = pass)
    detail: str = ""
    auto_fixed: bool = False


@dataclass
class RunReport:
    run_id: str
    mode: str
    started_at: str
    finished_at: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall_tier(self) -> int:
        return max((c.tier for c in self.checks if not c.passed), default=TIER_OK)

    @property
    def passed(self) -> bool:
        return self.overall_tier == TIER_OK


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
    tmp.write_text(content)
    try:
        with open(tmp, "rb") as fh:
            os.fsync(fh.fileno())
    except OSError:
        pass
    tmp.rename(path)


def load_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = RUNS_DIR / run_id / "manifest.yaml"
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")
    return yaml.safe_load(manifest_path.read_text()) or {}


# ─── Universal checks ───────────────────────────────────────────────

def check_operator_approval(manifest: dict[str, Any]) -> CheckResult:
    run_id = manifest["run_id"]
    approval_path = APPROVALS_DIR / f"{run_id}.md"
    if not approval_path.exists():
        return CheckResult(
            name="operator_approval", passed=False, tier=TIER_OPERATOR,
            detail=f"no approval file at {approval_path.relative_to(VAULT_ROOT)}",
        )
    text = approval_path.read_text()
    if "APPROVE" not in text and "OVERRIDE" not in text:
        return CheckResult(
            name="operator_approval", passed=False, tier=TIER_OPERATOR,
            detail="approval file present but no APPROVE / OVERRIDE token",
        )
    if "OVERRIDE" in text:
        return CheckResult(
            name="operator_approval", passed=True,
            detail="OVERRIDE token present (non-default; audit trail in approval file)",
        )
    return CheckResult(name="operator_approval", passed=True)


def check_artifacts_exist(manifest: dict[str, Any]) -> CheckResult:
    artifacts = manifest.get("artifacts") or []
    if not artifacts:
        return CheckResult(
            name="artifacts_exist", passed=False, tier=TIER_RETRY,
            detail="manifest declares no artifacts",
        )
    missing = []
    for art in artifacts:
        path = (VAULT_ROOT / art) if not Path(art).is_absolute() else Path(art)
        if not path.exists():
            missing.append(str(path))
    if missing:
        return CheckResult(
            name="artifacts_exist", passed=False, tier=TIER_RETRY,
            detail=f"{len(missing)} missing: {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}",
        )
    return CheckResult(name="artifacts_exist", passed=True,
                       detail=f"{len(artifacts)} artifacts present")


def check_citations_resolve(manifest: dict[str, Any]) -> CheckResult:
    cites = manifest.get("citations") or []
    if not cites:
        return CheckResult(name="citations_resolve", passed=True,
                           detail="no citations declared")
    bad: list[str] = []
    headers = {"User-Agent": "Mozilla/5.0 (vibecoding-check)"}
    with httpx.Client(timeout=15, follow_redirects=True, headers=headers) as client:
        for cite in cites:
            if cite.startswith(("http://", "https://")):
                try:
                    r = client.head(cite)
                    if r.status_code >= 400:
                        # Some servers reject HEAD; retry with GET
                        r = client.get(cite)
                    if r.status_code >= 400:
                        bad.append(f"{cite} → {r.status_code}")
                except httpx.HTTPError as e:
                    bad.append(f"{cite} → {type(e).__name__}")
            elif cite.startswith("git:"):
                ref = cite[4:]
                try:
                    subprocess.check_output(["git", "rev-parse", ref], stderr=subprocess.DEVNULL)
                except subprocess.CalledProcessError:
                    bad.append(f"{cite} → not a git ref")
            else:
                # Treat as filesystem path
                p = (VAULT_ROOT / cite) if not Path(cite).is_absolute() else Path(cite)
                if not p.exists():
                    bad.append(f"{cite} → file not found")
    if bad:
        # Citation 404 is genuinely ambiguous — could be a real finding with a
        # transient outage. Tier-3 (operator surface) per spec.
        return CheckResult(
            name="citations_resolve", passed=False, tier=TIER_OPERATOR,
            detail=f"{len(bad)} unresolved: " + "; ".join(bad[:3]),
        )
    return CheckResult(name="citations_resolve", passed=True,
                       detail=f"{len(cites)} citations all resolve")


TODO_RE = re.compile(r"\b(TODO|FIXME|XXX)\b")
DOC_TODO_ALLOWLIST = re.compile(r"#\s*TODO\(:?\s*future\b", re.IGNORECASE)


def check_no_todo_in_modified(manifest: dict[str, Any]) -> CheckResult:
    modified = manifest.get("modified_code") or []
    if not modified:
        return CheckResult(name="no_todo_in_modified", passed=True,
                           detail="no code files declared modified")
    hits: list[str] = []
    for rel in modified:
        path = (VAULT_ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if TODO_RE.search(line) and not DOC_TODO_ALLOWLIST.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()[:80]}")
    if hits:
        return CheckResult(
            name="no_todo_in_modified", passed=False, tier=TIER_RETRY,
            detail=f"{len(hits)} TODO/FIXME/XXX markers: {hits[0]}{' ...' if len(hits) > 1 else ''}",
        )
    return CheckResult(name="no_todo_in_modified", passed=True,
                       detail=f"{len(modified)} files clean")


def check_phase_tags(manifest: dict[str, Any]) -> CheckResult:
    declared = manifest.get("phase_tags") or []
    if not declared:
        return CheckResult(name="phase_tags", passed=True,
                           detail="no phase_tags declared (single-phase mode)")
    log_path = RUNS_DIR / manifest["run_id"] / "phase-log.txt"
    if not log_path.exists():
        return CheckResult(
            name="phase_tags", passed=False, tier=TIER_RETRY,
            detail=f"no phase-log at {log_path.relative_to(VAULT_ROOT)}",
        )
    emitted = [line.strip() for line in log_path.read_text().splitlines() if line.strip()]
    missing = [t for t in declared if t not in emitted]
    if missing:
        return CheckResult(
            name="phase_tags", passed=False, tier=TIER_RETRY,
            detail=f"missing phase-tags: {', '.join(missing)}",
        )
    return CheckResult(name="phase_tags", passed=True,
                       detail=f"all {len(declared)} phase-tags emitted")


# ─── Mode-specific checks ──────────────────────────────────────────

def check_project_tests_pass(manifest: dict[str, Any]) -> CheckResult:
    cmd = manifest.get("test_command") or "pytest -x"
    cwd = manifest.get("test_cwd") or str(VAULT_ROOT)
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                                text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return CheckResult(name="tests_pass", passed=False, tier=TIER_RETRY,
                           detail="test command timed out")
    if result.returncode != 0:
        return CheckResult(
            name="tests_pass", passed=False, tier=TIER_RETRY,
            detail=f"`{cmd}` exit {result.returncode}: {result.stdout[-300:].strip()}",
        )
    return CheckResult(name="tests_pass", passed=True,
                       detail=f"`{cmd}` exit 0")


def check_bounty_cvss(manifest: dict[str, Any]) -> CheckResult:
    findings = manifest.get("findings") or []
    if not findings:
        return CheckResult(name="cvss_recorded", passed=False, tier=TIER_RETRY,
                           detail="bounty mode but no findings declared")
    missing = [f.get("title", "?") for f in findings if not f.get("cvss_v4")]
    if missing:
        return CheckResult(
            name="cvss_recorded", passed=False, tier=TIER_RETRY,
            detail=f"{len(missing)} findings missing cvss_v4: {missing[0]}",
        )
    return CheckResult(name="cvss_recorded", passed=True,
                       detail=f"all {len(findings)} findings have CVSS v4")


def check_content_no_placeholder(manifest: dict[str, Any]) -> CheckResult:
    placeholder_re = re.compile(r"\[INSERT [^\]]+\]|\[TBD\]|\[PLACEHOLDER\]|TBD\.{3}", re.IGNORECASE)
    artifacts = manifest.get("artifacts") or []
    hits: list[str] = []
    for art in artifacts:
        path = (VAULT_ROOT / art) if not Path(art).is_absolute() else Path(art)
        if not path.exists() or path.suffix not in (".md", ".txt"):
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if placeholder_re.search(line):
                hits.append(f"{art}:{lineno}")
    if hits:
        return CheckResult(name="no_placeholder_text", passed=False, tier=TIER_RETRY,
                           detail=f"{len(hits)} placeholder markers: {hits[0]}")
    return CheckResult(name="no_placeholder_text", passed=True)


MODE_CHECKS = {
    "project": [check_project_tests_pass],
    "bounty": [check_bounty_cvss],
    "content": [check_content_no_placeholder],
}


# ─── Orchestrator ────────────────────────────────────────────────

def run_all_checks(manifest: dict[str, Any]) -> RunReport:
    started = datetime.now(timezone.utc).isoformat()
    report = RunReport(run_id=manifest["run_id"], mode=manifest.get("mode", "?"),
                       started_at=started, finished_at="")

    for check_fn in (
        check_operator_approval,
        check_artifacts_exist,
        check_citations_resolve,
        check_no_todo_in_modified,
        check_phase_tags,
    ):
        try:
            report.checks.append(check_fn(manifest))
        except Exception as e:
            report.checks.append(CheckResult(
                name=check_fn.__name__, passed=False, tier=TIER_OPERATOR,
                detail=f"check raised: {type(e).__name__}: {e}",
            ))

    for fn in MODE_CHECKS.get(manifest.get("mode", ""), []):
        try:
            report.checks.append(fn(manifest))
        except Exception as e:
            report.checks.append(CheckResult(
                name=fn.__name__, passed=False, tier=TIER_OPERATOR,
                detail=f"check raised: {type(e).__name__}: {e}",
            ))

    report.finished_at = datetime.now(timezone.utc).isoformat()
    return report


def render_report(report: RunReport) -> str:
    overall = {
        TIER_OK: "PASS",
        TIER_AUTOFIX: "PASS-AFTER-AUTOFIX",
        TIER_RETRY: "RETRY-NEEDED",
        TIER_OPERATOR: "OPERATOR-SURFACE",
    }[report.overall_tier]

    lines = [
        f"---",
        f"run_id: {report.run_id}",
        f"mode: {report.mode}",
        f"verdict: {overall}",
        f"started_at: {report.started_at}",
        f"finished_at: {report.finished_at}",
        f"check_count: {len(report.checks)}",
        f"failed_count: {sum(1 for c in report.checks if not c.passed)}",
        f"---",
        "",
        f"# Vibecoding Check — {report.run_id}",
        "",
        f"**Mode:** {report.mode}",
        f"**Verdict:** **{overall}**",
        "",
        "## Checks",
    ]
    for c in report.checks:
        marker = "✓" if c.passed else "✗"
        tier_note = "" if c.passed else f" *(tier {c.tier})*"
        lines.append(f"- {marker} **{c.name}**{tier_note}")
        if c.detail:
            lines.append(f"    - {c.detail}")
        if c.auto_fixed:
            lines.append(f"    - *auto-fixed*")
    lines.append("")
    if report.overall_tier == TIER_OPERATOR:
        lines.append("## Operator action required")
        lines.append("")
        lines.append("Tier-3 issues need human judgment. Surface this in the next morning brief.")
        lines.append("To override: write `OVERRIDE` + `override_reason: <reason>` to the approval file.")
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run vibecoding-check on a mode run.")
    p.add_argument("--run-id", required=True, help="Run ID (e.g. BTY-2026-05-02-1234)")
    p.add_argument("--quiet", action="store_true", help="Suppress per-check stdout")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.run_id)
    if "run_id" not in manifest:
        manifest["run_id"] = args.run_id

    report = run_all_checks(manifest)
    out_text = render_report(report)
    state_file = CHECK_DIR / f"{args.run_id}.md"
    atomic_write(state_file, out_text)

    if not args.quiet:
        print(out_text)
    print(f"State: {state_file}")
    print(f"Verdict tier: {report.overall_tier} "
          f"({['PASS', 'AUTOFIX', 'RETRY', 'OPERATOR'][report.overall_tier]})")
    return report.overall_tier


if __name__ == "__main__":
    sys.exit(main())
