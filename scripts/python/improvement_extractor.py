#!/usr/bin/env python3
"""Extract surfaced-only Vibe Squad improvement proposals from depth content.

This phase never edits executable files, instruction surfaces, configs, memory,
or mailbox tasks. It reads today's depth-tier research/practitioner content and
writes `_state/improvements-<date>.json` plus a cleanup log.

Write policy: same-day reruns intentionally overwrite the date-suffixed JSON
via atomic write. The artifact is advisory and fully regenerable from triage and
summary inputs.

Subprocess timeout policy: each LLM call gets 120s. With at most 5 extraction
candidates and scoring only for accepted proposals, this bounds nightly runtime
while still giving subscription-auth CLIs enough room for structured JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
BLOG_SUMMARIES_DIR = STATE_DIR / "blog-summaries"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
KIMI_BIN = os.environ.get("KIMI_BIN", "kimi")
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
MODEL_NAMES = ("claude", "kimi", "gpt-codex")


@dataclass
class CallRecord:
    name: str
    model: str
    command: str
    status: str
    returncode: int | None = None
    duration_s: float = 0.0
    stdout_len: int = 0
    stderr: str = ""


@dataclass
class CandidateInput:
    source: dict[str, Any]
    summary: str
    triage_reason: str


@dataclass
class RunState:
    calls: list[CallRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def current_time_section() -> str:
    now_utc = datetime.now(timezone.utc)
    local = now_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"=== CURRENT TIME ===\nUTC: {now_utc.isoformat()}\nLocal (PDT/PST): {local.isoformat()}"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def strip_json_fence(raw: str) -> str:
    raw = (raw or "").split("To resume this session:")[0].strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


def token_set(value: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if len(t) >= 4}


def slug(value: str) -> str:
    return "-".join(t for t in re.split(r"[^a-z0-9]+", value.lower()) if t)


def find_summary(candidate: dict[str, Any], date: str) -> str:
    title = str(candidate["source"].get("title", ""))
    source = str(candidate["source"].get("source_name", ""))
    title_tokens = token_set(title)
    source_tokens = token_set(source)
    best_score = -1
    best_path: Path | None = None
    for path in BLOG_SUMMARIES_DIR.glob(f"{date}-*.md"):
        name = path.name.lower()
        score = sum(3 for t in title_tokens if t in name) + sum(1 for t in source_tokens if t in name)
        if score > best_score:
            best_score = score
            best_path = path
    if best_path and best_score >= 6:
        return read_text(best_path)[:7000]
    return str(candidate.get("summary") or "")


def load_candidates(triage_path: Path, date: str, max_candidates: int) -> list[CandidateInput]:
    data = json.loads(triage_path.read_text(encoding="utf-8"))
    items = []
    for item in data.get("items", []):
        if item.get("tier") != "depth":
            continue
        if item.get("source_lane") not in {"research", "practitioner"}:
            continue
        metadata = item.get("feed_metadata") or {}
        source = {
            "title": metadata.get("title") or "(untitled)",
            "url": metadata.get("url") or "",
            "lane": item.get("source_lane"),
            "score": item.get("relevance_score"),
            "source_name": item.get("source_name"),
            "published": metadata.get("published") or date,
            "ingestion_date": date,
        }
        items.append({
            "source": source,
            "summary": metadata.get("summary") or "",
            "triage_reason": item.get("reason") or "",
        })
    items.sort(key=lambda i: float(i["source"].get("score") or 0), reverse=True)
    candidate_inputs: list[CandidateInput] = []
    for item in items[:max_candidates]:
        item["summary"] = find_summary(item, date)
        candidate_inputs.append(CandidateInput(**item))
    return candidate_inputs


def run_subprocess(name: str, model: str, cmd: list[str], prompt: str, env_drop: list[str], timeout: float, run: RunState) -> tuple[int | None, str, str]:
    env = os.environ.copy()
    for key in env_drop:
        env.pop(key, None)
    start = time.monotonic()
    display_cmd = list(cmd)
    if "-p" in display_cmd:
        idx = display_cmd.index("-p")
        if idx + 1 < len(display_cmd) and not display_cmd[idx + 1].startswith("--"):
            display_cmd[idx + 1] = "<prompt>"
    elif prompt:
        display_cmd = display_cmd + ["<prompt>"]
    try:
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env, cwd=str(VAULT_ROOT))
        record = CallRecord(
            name=name,
            model=model,
            command=" ".join(display_cmd),
            status="ok" if result.returncode == 0 else "failed",
            returncode=result.returncode,
            duration_s=time.monotonic() - start,
            stdout_len=len(result.stdout or ""),
            stderr=result.stderr or "",
        )
        run.calls.append(record)
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired as exc:
        record = CallRecord(
            name=name,
            model=model,
            command=" ".join(display_cmd),
            status="timeout",
            returncode=124,
            duration_s=time.monotonic() - start,
            stdout_len=len(exc.stdout or ""),
            stderr=(exc.stderr or "") + f"\nsubprocess timed out after {timeout}s",
        )
        run.calls.append(record)
        return 124, exc.stdout or "", record.stderr


def call_claude(prompt: str, name: str, run: RunState, timeout: float = 120.0) -> tuple[int | None, str, str]:
    if not shutil.which(CLAUDE_BIN):
        run.calls.append(CallRecord(name=name, model="claude", command=CLAUDE_BIN, status="missing-binary", stderr=f"{CLAUDE_BIN} not found"))
        return 127, "", f"{CLAUDE_BIN} not found"
    cmd = [CLAUDE_BIN, "-p", "--output-format", "text", "--no-session-persistence", "--allowed-tools", ""]
    return run_subprocess(name, "claude", cmd, prompt, ["ANTHROPIC_API_KEY"], timeout, run)


def call_kimi(prompt: str, name: str, run: RunState, timeout: float = 120.0) -> tuple[int | None, str, str]:
    if not shutil.which(KIMI_BIN):
        run.calls.append(CallRecord(name=name, model="kimi", command=KIMI_BIN, status="missing-binary", stderr=f"{KIMI_BIN} not found"))
        return 127, "", f"{KIMI_BIN} not found"
    cmd = [KIMI_BIN, "--quiet", "--no-thinking", "--max-steps-per-turn", "1", "-p", prompt]
    return run_subprocess(name, "kimi", cmd, "", [], timeout, run)


def call_codex(prompt: str, name: str, run: RunState, timeout: float = 120.0) -> tuple[int | None, str, str]:
    if not shutil.which(CODEX_BIN):
        run.calls.append(CallRecord(name=name, model="gpt-codex", command=CODEX_BIN, status="missing-binary", stderr=f"{CODEX_BIN} not found"))
        return 127, "", f"{CODEX_BIN} not found"
    cmd = [CODEX_BIN, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-C", str(VAULT_ROOT), "-"]
    return run_subprocess(name, "gpt-codex", cmd, prompt, ["OPENAI_API_KEY"], timeout, run)


def extraction_prompt(candidate: CandidateInput) -> str:
    payload = {
        "source": candidate.source,
        "triage_reason": candidate.triage_reason,
        "summary": candidate.summary[:7000],
    }
    return (
        "You are an improvement extractor for Vibe Squad. This is surface-only: do not propose auto-execution.\n"
        f"{current_time_section()}\n\n"
        "Does this paper/post propose a technique Vibe Squad could adopt? If yes, describe: "
        "(a) the change in 1-2 sentences, (b) what it would entail with specific files/specialists affected, "
        "(c) risks, (d) reversibility high/medium/low. If no, mark has_proposal false.\n"
        "Return JSON only with schema: {\"has_proposal\":true|false,\"proposed_change\":\"...\","
        "\"what_it_entails\":\"...\",\"risks\":\"...\",\"reversibility\":\"high|medium|low\",\"reason\":\"...\"}.\n"
        "Every claim must come from the source summary/title. Do not invent files as changes to execute; mention affected surfaces only.\n\n"
        f"Candidate:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def scoring_prompt(candidate: dict[str, Any]) -> str:
    return (
        "You are independently scoring a proposed Vibe Squad self-improvement. Return JSON only.\n"
        f"{current_time_section()}\n\n"
        "Score 0-10 using this rubric: 0-3 vague/unsafe/no provenance; 4-6 plausible but risky or broad; "
        "7-8 concrete, reversible, aligns with HITL/write-scope safety; 9-10 urgent, low-risk, clearly high-leverage.\n"
        "Prefer lower scores for overcomplication or corruption risk. Provide exactly one sentence opinion.\n"
        "Schema: {\"score\":0-10,\"opinion\":\"one sentence\"}.\n\n"
        f"Candidate proposal:\n{json.dumps(candidate, ensure_ascii=False)}"
    )


def model_failure(reason: str) -> dict[str, Any]:
    return {"score": None, "opinion": f"subprocess failed: {reason}"}


def parse_score(raw: str) -> dict[str, Any]:
    data = json.loads(strip_json_fence(raw))
    score = data.get("score")
    if isinstance(score, str) and re.fullmatch(r"\d+(?:\.\d+)?", score):
        score = float(score)
    if not isinstance(score, (int, float)):
        raise ValueError("score missing or non-numeric")
    score = max(0, min(10, float(score)))
    opinion = str(data.get("opinion") or "").strip()
    if not opinion:
        raise ValueError("opinion missing")
    return {"score": round(score, 2), "opinion": opinion}


def score_with_model(model: str, proposal: dict[str, Any], run: RunState) -> dict[str, Any]:
    prompt = scoring_prompt(proposal)
    if model == "claude":
        rc, out, err = call_claude(prompt, f"score:{proposal['id']}:claude", run)
    elif model == "kimi":
        rc, out, err = call_kimi(prompt, f"score:{proposal['id']}:kimi", run)
    else:
        rc, out, err = call_codex(prompt, f"score:{proposal['id']}:gpt-codex", run)
    if rc != 0:
        return model_failure((err or f"exit {rc}").strip().splitlines()[-1][:180])
    try:
        return parse_score(out)
    except (json.JSONDecodeError, ValueError) as exc:
        return model_failure(f"malformed-json: {exc}")


def proposal_id(date: str, title: str, proposed_change: str) -> str:
    base = slug(proposed_change or title)[:48].strip("-") or slug(title)[:48] or "proposal"
    return f"IMP-{date}-{base}"


def tracking_hash(source_url: str, proposed_change: str) -> str:
    prefix = " ".join(str(proposed_change or "").split())[:120]
    return hashlib.sha256(f"{source_url}\n{prefix}".encode()).hexdigest()[:24]


def prior_improvement_files(date: str, days: int = 14) -> list[Path]:
    try:
        today = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return []
    paths = []
    for offset in range(1, days + 1):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        path = STATE_DIR / f"improvements-{day}.json"
        if path.exists():
            paths.append(path)
    return paths


def load_prior_index(date: str) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for path in prior_improvement_files(date):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        prior_date = str(manifest.get("date") or path.stem.removeprefix("improvements-"))
        for candidate in manifest.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            source = candidate.get("source") or {}
            key = candidate.get("tracking_hash") or tracking_hash(str(source.get("url") or ""), str(candidate.get("proposed_change") or ""))
            if key:
                index.setdefault(key, []).append({
                    "path": path,
                    "date": prior_date,
                    "candidate": candidate,
                })
    return index


def apply_tracking(proposals: list[dict[str, Any]], date: str, run: RunState) -> None:
    prior = load_prior_index(date)
    touched: dict[Path, dict[str, Any]] = {}
    for proposal in proposals:
        source = proposal.get("source") or {}
        key = tracking_hash(str(source.get("url") or ""), str(proposal.get("proposed_change") or ""))
        proposal["tracking_hash"] = key
        matches = prior.get(key, [])
        previous_scores = [
            m["candidate"].get("aggregate_score")
            for m in matches
            if isinstance(m["candidate"].get("aggregate_score"), (int, float))
        ]
        proposal["recurrence_count"] = len(matches) + 1
        proposal["previous_scores"] = previous_scores
        proposal["first_seen"] = min([m["date"] for m in matches] + [date])
        if previous_scores:
            proposal["score_delta"] = round(float(proposal.get("aggregate_score") or 0) - float(previous_scores[0]), 2)
        for match in matches:
            path = match["path"]
            if path not in touched:
                try:
                    touched[path] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    run.warnings.append(f"could not mark superseded in {path}")
                    continue
            for prior_candidate in touched[path].get("candidates") or []:
                prior_source = prior_candidate.get("source") or {}
                prior_key = prior_candidate.get("tracking_hash") or tracking_hash(str(prior_source.get("url") or ""), str(prior_candidate.get("proposed_change") or ""))
                if prior_key == key:
                    prior_candidate["superseded"] = True
    for path, manifest in touched.items():
        atomic_write(path, json.dumps(manifest, indent=2, ensure_ascii=False))


def aggregate_scores(opinions: dict[str, dict[str, Any]]) -> tuple[float | None, float | None]:
    scores = [float(v["score"]) for v in opinions.values() if isinstance(v.get("score"), (int, float))]
    if not scores:
        return None, None
    return round(sum(scores) / len(scores), 2), round(max(scores) - min(scores), 2)


def extract_proposals(candidates: list[CandidateInput], date: str, run: RunState) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for candidate in candidates:
        rc, out, err = call_claude(extraction_prompt(candidate), f"extract:{candidate.source['title'][:60]}", run)
        if rc != 0:
            run.warnings.append(f"extract failed for {candidate.source['title']}: {(err or f'exit {rc}').strip()[:200]}")
            continue
        try:
            data = json.loads(strip_json_fence(out))
        except json.JSONDecodeError as exc:
            run.warnings.append(f"extract malformed JSON for {candidate.source['title']}: {exc}")
            continue
        if not data.get("has_proposal"):
            continue
        proposal = {
            "id": proposal_id(date, candidate.source["title"], str(data.get("proposed_change") or "")),
            "source": {
                "title": candidate.source["title"],
                "url": candidate.source["url"],
                "lane": candidate.source["lane"],
                "score": candidate.source["score"],
                "published": candidate.source["published"],
                "ingestion_date": candidate.source["ingestion_date"],
            },
            "proposed_change": str(data.get("proposed_change") or "").strip(),
            "what_it_entails": str(data.get("what_it_entails") or "").strip(),
            "risks": str(data.get("risks") or "").strip(),
            "reversibility": str(data.get("reversibility") or "medium").strip().lower(),
            "extractor_reason": str(data.get("reason") or "").strip(),
            "model_opinions": {},
        }
        if not proposal["proposed_change"]:
            continue
        for model in MODEL_NAMES:
            proposal["model_opinions"][model] = score_with_model(model, proposal, run)
        aggregate, divergence = aggregate_scores(proposal["model_opinions"])
        proposal["aggregate_score"] = aggregate
        proposal["divergence"] = divergence
        proposals.append(proposal)
    return proposals


def render_log(date: str, run: RunState, manifest: dict[str, Any]) -> str:
    lines = [
        f"# Improvement Extractor - {date}",
        "",
        f"Run at: {generated_at()}",
        f"Candidates considered: {manifest.get('input_candidate_count', 0)}",
        f"Proposals emitted: {len(manifest.get('candidates', []))}",
        "",
        "## Warnings",
    ]
    if run.warnings:
        lines.extend(f"- {w}" for w in run.warnings)
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Calls")
    for call in run.calls:
        lines.append(f"- {call.name} [{call.model}]: status={call.status}, rc={call.returncode}, duration={call.duration_s:.1f}s, stdout={call.stdout_len}")
        if call.stderr:
            lines.append("  - stderr first 1000:")
            lines.append("")
            lines.append("```")
            lines.append(call.stderr[:1000])
            lines.append("```")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--triage")
    parser.add_argument("--output")
    parser.add_argument("--log")
    parser.add_argument("--max-candidates", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    date = args.date or utc_date()
    triage_path = Path(args.triage or STATE_DIR / f"content-triage-{date}.json")
    output_path = Path(args.output or STATE_DIR / f"improvements-{date}.json")
    log_path = Path(args.log or STATE_DIR / "cleanup-logs" / f"{date}-improvement-extractor.md")
    run = RunState()

    if not triage_path.exists():
        manifest = {
            "generated_at": generated_at(),
            "generation_id": f"{date}-{int(time.time())}",
            "date": date,
            "write_policy": "same-day reruns intentionally overwrite this date-suffixed JSON via atomic write",
            "input_candidate_count": 0,
            "candidates": [],
            "warnings": [f"missing triage file: {triage_path}"],
        }
        atomic_write(output_path, json.dumps(manifest, indent=2, ensure_ascii=False))
        atomic_write(log_path, render_log(date, run, manifest))
        print(f"Improvement extractor: {output_path} (missing triage)")
        return 0

    candidates = load_candidates(triage_path, date, max(0, min(args.max_candidates, 5)))
    if not candidates:
        manifest = {
            "generated_at": generated_at(),
            "generation_id": f"{date}-{int(time.time())}",
            "date": date,
            "write_policy": "same-day reruns intentionally overwrite this date-suffixed JSON via atomic write",
            "input_candidate_count": 0,
            "candidates": [],
            "warnings": [],
        }
        atomic_write(output_path, json.dumps(manifest, indent=2, ensure_ascii=False))
        atomic_write(log_path, render_log(date, run, manifest))
        print(f"Improvement extractor: {output_path} (no qualifying depth items)")
        return 0

    proposals = extract_proposals(candidates, date, run)
    apply_tracking(proposals, date, run)
    manifest = {
        "generated_at": generated_at(),
        "generation_id": f"{date}-{int(time.time())}",
        "date": date,
        "write_policy": "same-day reruns intentionally overwrite this date-suffixed JSON via atomic write",
        "input_candidate_count": len(candidates),
        "candidates": proposals,
        "warnings": run.warnings,
    }
    atomic_write(output_path, json.dumps(manifest, indent=2, ensure_ascii=False))
    atomic_write(log_path, render_log(date, run, manifest))
    print(f"Improvement extractor: {output_path} ({len(proposals)} proposals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
