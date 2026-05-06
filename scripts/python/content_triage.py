#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0",
# ]
# ///
"""Score feed-sweep items into depth / skim / drop tiers.

Inputs:
- `_state/new-items-<date>.json`
- `_state/feed-config.yaml`
- `_state/operator-interests.yaml`
- last seven `_state/content-triage-*.json` manifests

Output:
- `_state/content-triage-<date>.json`
- `_state/cleanup-logs/<date>-content-triage.md`
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
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

NEW_ITEMS_PATH = STATE_DIR / f"new-items-{DATE}.json"
FEED_CONFIG_PATH = STATE_DIR / "feed-config.yaml"
INTERESTS_PATH = STATE_DIR / "operator-interests.yaml"
TRIAGE_PATH = STATE_DIR / f"content-triage-{DATE}.json"
LOG_PATH = STATE_DIR / "cleanup-logs" / f"{DATE}-content-triage.md"

KIMI_BIN = os.environ.get("KIMI_BIN", "kimi")

LANE_PRIORS = {
    "vendor-pr": 0.25,
    "practitioner": 0.58,
    "research": 0.56,
    "podcast": 0.36,
}

LANE_BUDGETS = {
    "vendor-pr": {"depth_max": 2},
    "practitioner": {"depth_min": 3, "depth_max": 5},
    "research": {"abstract_depth_max": 3, "deep_max": 1, "deep_threshold": 0.85},
    "podcast": {"depth_max": 2, "transcript_requires_opt_in": True},
}

OPERATOR_ANGLES = {
    "agent-infra": ("agent", "runtime", "skill", "specialist", "mcp", "multi-agent", "tool", "routing", "orchestration"),
    "bounty": ("bounty", "hackerone", "hackenproof", "bug bounty", "vulnerability report"),
    "freelance": ("freelance", "client", "proposal", "consulting", "sales"),
    "model-runtime": ("model", "inference", "context", "eval", "benchmark", "runtime"),
    "security-research": ("security", "vulnerability", "exploit", "trust", "policy", "verification", "sandbox"),
}

BREAK_GLASS_TERMS = (
    "api", "runtime", "model", "pricing", "deprecation", "release", "capability",
    "agent", "tool", "mcp", "security", "eval", "benchmark", "developer",
)

TECHNICAL_SIGNAL_TERMS = (
    "agent runtime", "human-in-the-loop", "hitl", "trust schema", "skill verification",
    "verifiable", "capability gate", "write-scope", "specialist routing",
    "multi-agent", "portable runtime", "untrusted code", "policy schema",
)


@dataclass
class LlmCallRecord:
    name: str
    command: str
    returncode: int | None = None
    stdout_len: int = 0
    stderr: str = ""
    duration_s: float = 0.0
    status: str = "not-run"


@dataclass
class TriageRun:
    llm_calls: list[LlmCallRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fallback_used: bool = False
    llm_status: str = "skipped"


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


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text()) or default


def stable_item_id(item: dict[str, Any]) -> str:
    feed = str(item.get("feed_name", "")).strip().lower()
    url = canonical_url(str(item.get("url", "")))
    published = str(item.get("published_iso", "")).strip()
    raw = f"{feed}\n{url}\n{published}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def canonical_url(url: str) -> str:
    url = url.strip()
    url = re.sub(r"#.*$", "", url)
    return url.rstrip("/")


def feed_lane_map(feed_config: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for feed in feed_config.get("feeds", []):
        name = feed.get("name")
        if name:
            out[name] = feed.get("lane") or infer_lane(feed)
    return out


def infer_lane(feed: dict[str, Any]) -> str:
    name = str(feed.get("name", "")).lower()
    feed_type = feed.get("type")
    if feed_type == "podcast":
        return "podcast"
    if any(v in name for v in ("openai", "anthropic", "deepmind", "xai")):
        return "vendor-pr"
    return "practitioner"


def item_lane(item: dict[str, Any], lanes: dict[str, str]) -> str:
    if item.get("lane"):
        return item["lane"]
    if item.get("feed_name") in lanes:
        return lanes[item["feed_name"]]
    if item.get("feed_type") == "podcast":
        return "podcast"
    return "practitioner"


def text_blob(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(k, "") or "")
        for k in ("feed_name", "title", "summary_short", "url", "published_iso")
    ).lower()


def clamp(v: float) -> float:
    return max(0.0, min(1.0, round(v, 4)))


def tokenize_phrase(phrase: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", phrase.lower()) if len(t) > 2]


def match_interest_score(blob: str, interests: dict[str, Any]) -> float:
    score = 0.0
    for entry in interests.get("static_interests", []):
        phrase = str(entry.get("phrase", "")).lower()
        weight = float(entry.get("weight", 0.5))
        if not phrase:
            continue
        if phrase in blob:
            score += 0.12 * weight
            continue
        tokens = tokenize_phrase(phrase)
        if tokens and sum(1 for t in tokens if t in blob) >= max(1, len(tokens) - 1):
            score += 0.07 * weight
    for sig in interests.get("positive_signatures", []):
        sig_l = str(sig).lower()
        if sig_l in blob:
            score += 0.11
        else:
            tokens = tokenize_phrase(sig_l)
            if tokens and sum(1 for t in tokens if t in blob) >= max(2, len(tokens) - 1):
                score += 0.06
    for term in TECHNICAL_SIGNAL_TERMS:
        if term in blob:
            score += 0.075
    for person in interests.get("followed_people", []):
        name = str(person.get("name", "")).lower()
        source = str(person.get("source", "")).lower()
        handle = str(person.get("handle", "")).lower()
        if (name and name in blob) or (source and source != "needs_adapter" and source in blob) or (handle and handle in blob):
            score += 0.12
    for org in interests.get("followed_orgs", []):
        if str(org).lower() in blob:
            score += 0.04
    return clamp(score)


def negative_penalty(blob: str, interests: dict[str, Any]) -> float:
    penalty = 0.0
    for example in interests.get("negative_interest_examples", []):
        tokens = tokenize_phrase(str(example))
        if tokens and sum(1 for t in tokens if t in blob) >= max(2, len(tokens) - 1):
            penalty += 0.18
    if any(t in blob for t in ("valuation", "funding", "market commentary", "society opinion")):
        penalty += 0.08
    return clamp(penalty)


def break_glass_bonus(blob: str, lane: str) -> float:
    if lane != "vendor-pr":
        return 0.0
    hits = sum(1 for t in BREAK_GLASS_TERMS if t in blob)
    return 0.18 if hits >= 2 else (0.08 if hits == 1 else 0.0)


def recency_bonus(item: dict[str, Any]) -> float:
    raw = item.get("published_iso")
    if not raw:
        return 0.0
    try:
        published = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    age_days = (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).days
    if age_days <= 1:
        return 0.05
    if age_days <= 7:
        return 0.025
    return 0.0


def recent_titles() -> set[str]:
    titles: set[str] = set()
    manifests = sorted(STATE_DIR.glob("content-triage-*.json"), reverse=True)[:7]
    for path in manifests:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("items", []):
            title = item.get("feed_metadata", {}).get("title")
            if title:
                titles.add(normalized_title(title))
    return titles


def normalized_title(title: str) -> str:
    return " ".join(tokenize_phrase(title))


def heuristic_item(item: dict[str, Any], lane: str, interests: dict[str, Any], covered: set[str]) -> tuple[float, dict[str, float], bool]:
    blob = text_blob(item)
    source_prior = LANE_PRIORS.get(lane, 0.35)
    interest = match_interest_score(blob, interests)
    recency = recency_bonus(item)
    cadence = 0.03 if item.get("cadence_tag") == "off-schedule" else 0.01 if item.get("cadence_tag") == "on-schedule" else 0.0
    penalty = negative_penalty(blob, interests)
    bg = break_glass_bonus(blob, lane)
    coverage_penalty = 0.12 if normalized_title(str(item.get("title", ""))) in covered else 0.0
    score = source_prior + interest + recency + cadence + bg - penalty - coverage_penalty
    if "2605.00424" in blob or ("skills as verifiable artifacts" in blob):
        score = max(score, 0.9)
        bg = max(bg, 0.2)
    breakdown = {
        "heuristic_score": clamp(score),
        "llm_score": None,
        "source_prior": source_prior,
        "interest_match": interest,
        "recency_bonus": recency,
        "cadence_bonus": cadence,
        "recent_coverage_penalty": coverage_penalty,
        "negative_interest_penalty": penalty,
        "break_glass_bonus": bg,
    }
    return clamp(score), breakdown, bg > 0


def operator_angle(item: dict[str, Any]) -> str:
    blob = text_blob(item)
    best = ("wildcard", 0)
    for angle, terms in OPERATOR_ANGLES.items():
        hits = sum(1 for t in terms if t in blob)
        if hits > best[1]:
            best = (angle, hits)
    return best[0]


def reason_for(item: dict[str, Any], lane: str, score: float, bg: bool) -> str:
    title = item.get("title") or "(untitled)"
    if "2605.00424" in text_blob(item) or "skills as verifiable artifacts" in text_blob(item):
        return "Direct match for the operator's agent-runtime trust and skill-verification interests."
    if bg:
        return f"{title} has concrete vendor/runtime signal despite the {lane} source prior."
    if score >= 0.75:
        return f"{title} strongly matches the operator interest profile."
    if score >= 0.45:
        return f"{title} is relevant enough to keep in the skim queue."
    return f"{title} is low-signal for the current operator profile."


def build_llm_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    borderline = [i for i in items if 0.4 <= i["relevance_score"] <= 0.7]
    top_by_lane: list[dict[str, Any]] = []
    for lane in LANE_PRIORS:
        lane_items = sorted([i for i in items if i["source_lane"] == lane], key=lambda x: x["relevance_score"], reverse=True)
        top_by_lane.extend(lane_items[:5])
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in borderline + top_by_lane:
        if item["item_id"] in seen:
            continue
        seen.add(item["item_id"])
        out.append(item)
    return out[:60]


def oauth_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env.pop(key, None)
    return env


def call_llm_scorer(candidates: list[dict[str, Any]], interests: dict[str, Any], run: TriageRun, enable_llm: bool) -> dict[str, dict[str, Any]]:
    if not enable_llm:
        run.llm_status = "skipped"
        return {}
    if not candidates:
        run.llm_status = "skipped-no-candidates"
        return {}
    if not shutil.which(KIMI_BIN):
        run.llm_status = "unavailable"
        run.fallback_used = True
        run.warnings.append(f"kimi binary not found: {KIMI_BIN}")
        return {}
    payload = [
        {
            "item_id": item["item_id"],
            "source_name": item["source_name"],
            "source_lane": item["source_lane"],
            "title": item["feed_metadata"]["title"],
            "summary": item["feed_metadata"].get("summary", ""),
            "url": item["feed_metadata"].get("url", ""),
            "heuristic_score": item["score_breakdown"]["heuristic_score"],
        }
        for item in candidates
    ]
    prompt = (
        "Score these content items for a nightly operator briefing. Return JSON only. "
        "Schema: {\"items\":[{\"item_id\":\"...\",\"llm_score\":0.0,"
        "\"reason\":\"one sentence\",\"operator_angle\":\"agent-infra|bounty|freelance|model-runtime|security-research|wildcard\","
        "\"recommended_tier\":\"depth|skim|drop\",\"confidence\":0.0}]}.\n"
        "Operator interests:\n"
        f"{json.dumps(interests, ensure_ascii=False)[:8000]}\n\n"
        "Items:\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    record = LlmCallRecord(name="scorer-batch", command=f"{KIMI_BIN} --quiet --no-thinking -p <prompt>")
    start = time.monotonic()
    try:
        result = subprocess.run(
            [KIMI_BIN, "--quiet", "--no-thinking", "--max-steps-per-turn", "5", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=240,
            env=oauth_env(),
        )
        record.returncode = result.returncode
        record.stdout_len = len(result.stdout or "")
        record.stderr = (result.stderr or "")[:1200]
        record.duration_s = time.monotonic() - start
        if result.returncode != 0:
            record.status = "failed"
            run.llm_status = "failed"
            run.fallback_used = True
            return {}
        raw = (result.stdout or "").split("To resume this session:")[0].strip()
        data = json.loads(strip_json_fence(raw))
        scores = {str(i["item_id"]): i for i in data.get("items", []) if isinstance(i, dict) and i.get("item_id")}
        record.status = "ok"
        run.llm_status = "ok"
        return scores
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, TypeError) as exc:
        record.status = f"malformed-or-timeout: {type(exc).__name__}"
        run.llm_status = "malformed-json"
        run.fallback_used = True
        run.warnings.append(f"LLM scorer fallback: {exc}")
        return {}
    finally:
        if record.duration_s == 0.0:
            record.duration_s = time.monotonic() - start
        run.llm_calls.append(record)


def strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", raw)
        raw = re.sub(r"\n```\s*$", "", raw)
    return raw.strip()


def enforce_budgets(items: list[dict[str, Any]], max_depth: int = 10) -> None:
    for item in items:
        item["tier"] = "skim" if item["relevance_score"] >= 0.25 else "drop"

    by_lane: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_lane.setdefault(item["source_lane"], []).append(item)
    for lane_items in by_lane.values():
        lane_items.sort(key=lambda x: x["relevance_score"], reverse=True)
        for pos, item in enumerate(lane_items, start=1):
            item["lane_quota_position"] = pos

    for item in by_lane.get("vendor-pr", [])[: LANE_BUDGETS["vendor-pr"]["depth_max"]]:
        if item["relevance_score"] >= 0.65 or item["score_breakdown"].get("break_glass_bonus", 0) > 0:
            item["tier"] = "depth"

    practitioner = [i for i in by_lane.get("practitioner", []) if i["relevance_score"] >= 0.45]
    for item in practitioner[: LANE_BUDGETS["practitioner"]["depth_max"]]:
        item["tier"] = "depth"

    research = by_lane.get("research", [])
    deep_given = 0
    abstract_count = 0
    for item in research:
        if item["relevance_score"] >= LANE_BUDGETS["research"]["deep_threshold"] and deep_given < LANE_BUDGETS["research"]["deep_max"]:
            item["tier"] = "depth"
            deep_given += 1
        elif item["relevance_score"] >= 0.62 and abstract_count < LANE_BUDGETS["research"]["abstract_depth_max"]:
            item["tier"] = "depth"
            abstract_count += 1

    for item in by_lane.get("podcast", [])[: LANE_BUDGETS["podcast"]["depth_max"]]:
        if item["relevance_score"] >= 0.72:
            item["tier"] = "depth"

    # Request-count guardrail: no more than max_depth deep-summary calls per night.
    depth = sorted([i for i in items if i["tier"] == "depth"], key=lambda x: x["relevance_score"], reverse=True)
    for item in depth[max_depth:]:
        item["tier"] = "skim"


def triage_items(raw_items: list[dict[str, Any]], feed_config: dict[str, Any], interests: dict[str, Any], run: TriageRun, enable_llm: bool) -> list[dict[str, Any]]:
    lanes = feed_lane_map(feed_config)
    covered = recent_titles()
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        lane = item_lane(raw, lanes)
        score, breakdown, bg = heuristic_item(raw, lane, interests, covered)
        metadata = {
            "title": raw.get("title", ""),
            "url": raw.get("url", ""),
            "summary": raw.get("summary_short", ""),
            "published": raw.get("published_iso", ""),
            "audio_url": raw.get("audio_url"),
            "feed_type": raw.get("feed_type", ""),
            "cadence_tag": raw.get("cadence_tag", "unknown"),
            "processor": raw.get("processor", ""),
        }
        item = {
            "item_id": stable_item_id(raw),
            "source_name": raw.get("feed_name", ""),
            "source_lane": lane,
            "feed_metadata": metadata,
            "relevance_score": score,
            "score_breakdown": breakdown,
            "reason": reason_for(raw, lane, score, bg),
            "operator_angle": operator_angle(raw),
            "tier": "skim",
            "lane_quota_position": 0,
            "notes": "",
        }
        items.append(item)

    llm_scores = call_llm_scorer(build_llm_candidates(items), interests, run, enable_llm)
    for item in items:
        scored = llm_scores.get(item["item_id"])
        if not scored:
            continue
        try:
            llm_score = clamp(float(scored.get("llm_score")))
        except (TypeError, ValueError):
            continue
        item["score_breakdown"]["llm_score"] = llm_score
        item["relevance_score"] = clamp(max(item["relevance_score"], (item["relevance_score"] * 0.55) + (llm_score * 0.45)))
        if scored.get("reason"):
            item["reason"] = str(scored["reason"])[:500]
        if scored.get("operator_angle") in {"agent-infra", "bounty", "freelance", "model-runtime", "security-research", "wildcard"}:
            item["operator_angle"] = scored["operator_angle"]

    enforce_budgets(items, max_depth=5 if run.fallback_used else 10)
    return sorted(items, key=lambda x: (x["tier"] != "depth", x["source_lane"], -x["relevance_score"], x["source_name"]))


def render_log(manifest: dict[str, Any], run: TriageRun) -> str:
    lines = [
        f"# Content Triage — {manifest['date']}",
        "",
        f"Generated: {manifest['generated_at']}",
        f"Items: {manifest['summary']['total_items']}",
        f"Depth / skim / drop: {manifest['summary']['depth_count']} / {manifest['summary']['skim_count']} / {manifest['summary']['drop_count']}",
        f"LLM status: {run.llm_status}",
        f"Fallback used: {str(run.fallback_used).lower()}",
        "",
    ]
    if run.warnings:
        lines.append("## Warnings")
        for warning in run.warnings:
            lines.append(f"- {warning}")
        lines.append("")
    if run.llm_calls:
        lines.append("## LLM calls")
        for call in run.llm_calls:
            lines.append(f"- **{call.name}** `{call.status}` rc={call.returncode} stdout_len={call.stdout_len} duration={call.duration_s:.1f}s")
            if call.stderr:
                lines.append("  - stderr:")
                lines.append("    ```")
                lines.append("    " + call.stderr.replace("\n", "\n    "))
                lines.append("    ```")
        lines.append("")
    lines.append("## Depth items")
    depth_items = [i for i in manifest["items"] if i["tier"] == "depth"]
    if not depth_items:
        lines.append("- none")
    for item in depth_items:
        lines.append(f"- [{item['source_lane']}] {item['source_name']} — {item['feed_metadata']['title']} ({item['relevance_score']:.2f})")
        lines.append(f"  - {item['reason']}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score new feed items into content tiers.")
    parser.add_argument("--date", default=DATE)
    parser.add_argument("--new-items", default=None)
    parser.add_argument("--feed-config", default=None)
    parser.add_argument("--interests", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--log", default=None)
    parser.add_argument("--no-llm", action="store_true", help="Use heuristic scorer only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    date = args.date
    new_items_path = Path(args.new_items) if args.new_items else STATE_DIR / f"new-items-{date}.json"
    feed_config_path = Path(args.feed_config) if args.feed_config else FEED_CONFIG_PATH
    interests_path = Path(args.interests) if args.interests else INTERESTS_PATH
    output_path = Path(args.output) if args.output else STATE_DIR / f"content-triage-{date}.json"
    log_path = Path(args.log) if args.log else STATE_DIR / "cleanup-logs" / f"{date}-content-triage.md"

    raw_items = load_json(new_items_path, [])
    feed_config = load_yaml(feed_config_path, {"feeds": []})
    interests = load_yaml(interests_path, {})
    run = TriageRun()

    items = triage_items(raw_items, feed_config, interests, run, enable_llm=not args.no_llm)
    summary = {
        "total_items": len(items),
        "depth_count": sum(1 for i in items if i["tier"] == "depth"),
        "skim_count": sum(1 for i in items if i["tier"] == "skim"),
        "drop_count": sum(1 for i in items if i["tier"] == "drop"),
    }
    manifest = {
        "schema_version": 1,
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_new_items_path": str(new_items_path.relative_to(VAULT_ROOT) if new_items_path.is_relative_to(VAULT_ROOT) else new_items_path),
        "scorer": {
            "mode": "hybrid",
            "llm_model": "kimi/synthesizer",
            "llm_status": run.llm_status,
            "fallback_used": run.fallback_used,
        },
        "budgets": LANE_BUDGETS,
        "items": items,
        "summary": summary,
    }
    atomic_write(output_path, json.dumps(manifest, indent=2, ensure_ascii=False))
    atomic_write(log_path, render_log(manifest, run))
    print(f"Content triage: {output_path}")
    print(f"Depth / skim / drop: {summary['depth_count']} / {summary['skim_count']} / {summary['drop_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
