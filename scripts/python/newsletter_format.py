#!/usr/bin/env python3
"""Format the daily raw brief into a reader-friendly newsletter.

Inputs:
- `_state/morning-briefs/<utc-date>.md`
- `_state/content-synthesis-<utc-date>.md`
- `_state/content-triage-<utc-date>.json`
- `_state/cross-day-<utc-date>.md`
- `_state/improvements-<utc-date>.json`
- `_state/content-actions/*.md` with `status: pending`

Output:
- `_state/newsletter-<utc-date>.md` as the Telegram-targeted digest
- `_state/newsletter-archive-<utc-date>.md` as the full multi-dimensional archive
- `_state/cleanup-logs/<utc-date>-newsletter-format.md` on failure
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
DELIVERY_CHAR_LIMIT = 2500
DELIVERY_TOP_ITEMS = 3
ARCHIVE_SIGNAL_LIMIT = 8


@dataclass
class FormatInputs:
    date: str
    morning: str
    synthesis: str
    cross_day_context: str
    improvements: str
    actions: list[str]
    triage_summary: str
    todays_signals: str
    depth_count: int


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[truncated for newsletter formatter]"


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return {}
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_depth_signals(date: str, triage_path: Path) -> str:
    try:
        triage = json.loads(triage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "[]"
    depth_titles = {
        str((item.get("feed_metadata") or {}).get("title") or "")
        for item in triage.get("items") or []
        if item.get("tier") == "depth"
    }
    signals: list[dict[str, Any]] = []
    for path in sorted((STATE_DIR / "blog-summaries").glob(f"{date}-*.md")):
        text = read_text(path)
        fm = parse_frontmatter(text)
        if not fm.get("analysis_json"):
            continue
        title = fm.get("title", "")
        if depth_titles and title not in depth_titles:
            continue
        raw_analysis = fm["analysis_json"]
        try:
            analysis = json.loads(raw_analysis)
        except json.JSONDecodeError:
            try:
                analysis = json.loads(raw_analysis.replace('\\"', '"'))
            except json.JSONDecodeError:
                continue
        def short(value: Any, limit: int = 700) -> str:
            text = str(value or "").strip()
            return text if len(text) <= limit else text[:limit].rstrip() + "..."

        def short_list(value: Any, limit: int = 260, max_items: int = 4) -> list[str]:
            return [short(v, limit) for v in nonempty_values(value)[:max_items]]

        compact_analysis = {
            "core_finding": short(analysis.get("core_finding"), 900),
            "relevance_to_me": {
                "current_work_connections": short_list((analysis.get("relevance_to_me") or {}).get("current_work_connections") if isinstance(analysis.get("relevance_to_me"), dict) else [], 260, 3),
                "why_now": short((analysis.get("relevance_to_me") or {}).get("why_now") if isinstance(analysis.get("relevance_to_me"), dict) else "", 260),
            },
            "time_horizon": analysis.get("time_horizon") or fm.get("time_horizon") or "near-term",
            "what_it_enables": short_list(analysis.get("what_it_enables"), 260, 3),
            "immediate_fixes": short_list(analysis.get("immediate_fixes"), 260, 3),
            "hypothetical_combinations": short_list(analysis.get("hypothetical_combinations"), 260, 2),
            "risks_of_action": short_list(analysis.get("risks_of_action"), 260, 3),
            "connections": short_list(analysis.get("connections"), 260, 3),
        }
        signals.append({
            "lane": fm.get("source_lane") or "unknown",
            "title": title,
            "url": fm.get("url"),
            "source": fm.get("feed"),
            "time_horizon": compact_analysis["time_horizon"],
            "analysis": compact_analysis,
        })
        if len(signals) >= ARCHIVE_SIGNAL_LIMIT:
            break
    return json.dumps(signals, ensure_ascii=False, indent=2) if signals else "[]"


def nonempty_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        value = [value] if value else []
    out = []
    for item in value:
        text = str(item or "").strip()
        if text and text.lower() not in {"none", "(none)", "none observed", "(none observed)"}:
            out.append(text)
    return out


def render_signal_cards(signals_json: str) -> str:
    try:
        signals = json.loads(signals_json)
    except json.JSONDecodeError:
        return ""
    if not isinstance(signals, list) or not signals:
        return ""
    cards: list[str] = []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        analysis = signal.get("analysis") if isinstance(signal.get("analysis"), dict) else {}
        relevance = analysis.get("relevance_to_me") if isinstance(analysis.get("relevance_to_me"), dict) else {}
        card = [
            f"### [{signal.get('lane', 'unknown')}] {signal.get('title', '(untitled)')}",
            f"*Source: [{signal.get('source') or 'source'}]({signal.get('url')}) | time horizon: {signal.get('time_horizon') or analysis.get('time_horizon') or 'near-term'}*",
            "",
            f"**Core:** {analysis.get('core_finding') or '(missing core finding)'}",
            "",
        ]
        why_parts = nonempty_values(relevance.get("current_work_connections"))
        why_now = str(relevance.get("why_now") or "").strip()
        if why_parts or why_now:
            card += [f"**Why for you:** {'; '.join(why_parts)}" + (f" — {why_now}" if why_now else ""), ""]
        for label, key in (
            ("What it enables", "what_it_enables"),
            ("Immediate fixes", "immediate_fixes"),
            ("Hypothetical combos", "hypothetical_combinations"),
            ("Risks", "risks_of_action"),
            ("Connections", "connections"),
        ):
            values = nonempty_values(analysis.get(key))
            if not values:
                continue
            card += [f"**{label}:**", "", *(f"- {v}" for v in values), ""]
        cards.append("\n".join(card).strip())
    return "\n\n".join(cards)


def enforce_todays_signals(body: str, signals_json: str) -> str:
    rendered = render_signal_cards(signals_json)
    if not rendered:
        return body
    section = f"## Today's signals\n\n{rendered}\n"
    pattern = r"(?ms)^## Today's signals\s*\n.*?(?=^## |\Z)"
    if re.search(pattern, body):
        return re.sub(pattern, lambda _match: section, body, count=1)
    marker = re.search(r"(?m)^## Continuity\s*$|^## Skim queue\s*$|^## What's out\s*$", body)
    if marker:
        return body[:marker.start()].rstrip() + "\n\n" + section + "\n" + body[marker.start():].lstrip()
    return body.rstrip() + "\n\n" + section


def load_pending_actions(actions_dir: Path) -> list[str]:
    cards: list[str] = []
    if not actions_dir.exists():
        return cards
    for path in sorted(actions_dir.glob("*.md")):
        text = read_text(path)
        frontmatter = parse_frontmatter(text)
        if frontmatter.get("status", "").lower() != "pending":
            continue
        card_id = frontmatter.get("id", path.stem)
        title = frontmatter.get("title", path.stem)
        rationale = frontmatter.get("rationale", "")
        proposed = frontmatter.get("proposed_action", "")
        cards.append(
            "\n".join(
                [
                    f"card_path: {path}",
                    f"id: {card_id}",
                    f"title: {title}",
                    f"rationale: {rationale}",
                    f"proposed_action: {proposed}",
                    "",
                    truncate(text, 1800),
                ]
            )
        )
    return cards


def compact_item(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("feed_metadata") or {}
    return {
        "tier": item.get("tier"),
        "depth_kind": item.get("depth_kind"),
        "lane": item.get("source_lane"),
        "source": item.get("source_name"),
        "title": metadata.get("title"),
        "url": metadata.get("url"),
        "score": item.get("relevance_score"),
        "reason": item.get("reason"),
    }


def load_triage_summary(path: Path) -> tuple[str, int]:
    if not path.exists():
        return "triage file missing", 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"triage unreadable: {exc}", 0

    items = data.get("items") or []
    summary = data.get("summary") or {}
    lanes: dict[str, int] = {}
    for item in items:
        lane = str(item.get("source_lane") or "unknown")
        lanes[lane] = lanes.get(lane, 0) + 1

    depth_items = [compact_item(i) for i in items if i.get("tier") == "depth"]
    skim_items = [compact_item(i) for i in items if i.get("tier") == "skim"][:12]
    dropped = [compact_item(i) for i in items if i.get("tier") == "drop"][:5]
    payload = {
        "total": summary.get("total_items", len(items)),
        "depth": summary.get("depth_count", len(depth_items)),
        "skim": summary.get("skim_count"),
        "drop": summary.get("drop_count"),
        "lanes": lanes,
        "depth_items": depth_items,
        "top_skim_items": skim_items,
        "dropped_examples": dropped,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2), int(summary.get("depth_count") or len(depth_items))


def load_cross_day_context(path: Path) -> str:
    text = read_text(path).strip()
    if not text or text == "insufficient history; skipping":
        return "no continuity context for today"
    return truncate(text, 1800)


def load_improvements(path: Path) -> str:
    if not path.exists():
        return "no proposals today"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "no proposals today"
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not candidates:
        return "no proposals today"
    compact = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        source = candidate.get("source") or {}
        compact.append({
            "id": candidate.get("id"),
            "source": {
                "title": source.get("title"),
                "url": source.get("url"),
                "lane": source.get("lane"),
                "score": source.get("score"),
            },
            "proposed_change": candidate.get("proposed_change"),
            "what_it_entails": candidate.get("what_it_entails"),
            "risks": candidate.get("risks"),
            "reversibility": candidate.get("reversibility"),
            "model_opinions": candidate.get("model_opinions"),
            "aggregate_score": candidate.get("aggregate_score"),
            "divergence": candidate.get("divergence"),
            "recurrence_count": candidate.get("recurrence_count"),
            "previous_scores": candidate.get("previous_scores"),
            "first_seen": candidate.get("first_seen"),
            "score_delta": candidate.get("score_delta"),
        })
    return truncate(json.dumps({"candidates": compact}, ensure_ascii=False, indent=2), 9000)


def load_inputs(args: argparse.Namespace) -> FormatInputs:
    date = args.date or utc_date()
    morning_path = Path(args.morning or STATE_DIR / "morning-briefs" / f"{date}.md")
    synthesis_path = Path(args.synthesis or STATE_DIR / f"content-synthesis-{date}.md")
    triage_path = Path(args.triage or STATE_DIR / f"content-triage-{date}.json")
    cross_day_path = STATE_DIR / f"cross-day-{date}.md"
    improvements_path = STATE_DIR / f"improvements-{date}.json"
    actions_dir = Path(args.actions_dir or STATE_DIR / "content-actions")

    triage_summary, depth_count = load_triage_summary(triage_path)
    return FormatInputs(
        date=date,
        morning=truncate(read_text(morning_path), 9000),
        synthesis=truncate(read_text(synthesis_path), 6000),
        cross_day_context=load_cross_day_context(cross_day_path),
        improvements=load_improvements(improvements_path),
        actions=load_pending_actions(actions_dir),
        triage_summary=triage_summary,
        todays_signals=load_depth_signals(date, triage_path),
        depth_count=depth_count,
    )


def no_signal(inputs: FormatInputs) -> bool:
    text = f"{inputs.morning}\n{inputs.synthesis}".lower()
    if inputs.actions:
        return False
    if inputs.depth_count > 0:
        return False
    # These mirror the legacy email skip markers. If the brief has operational
    # signal but no content depth picks, let Claude format it instead of
    # collapsing it to the deterministic no-signal stub.
    non_content_signal_markers = (
        "warnings / 1",
        "issues",
        "### warnings",
        "### issues",
        "processed blog artifacts",
        "podcast headline artifacts",
        "pending dream proposals",
        "cards for your decision",
        "active modes",
        "top n worth reading",
        "depth synthesis",
    )
    if any(marker in text for marker in non_content_signal_markers):
        return False
    return True


def build_no_signal_newsletter(inputs: FormatInputs) -> tuple[str, str]:
    subject = "No notable signal today"
    body = "## Lead\nNo notable signal today.\n\n## Today's signals\nNothing cleared the depth bar."
    return body, subject


def weekday_label(date: str) -> str:
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return date
    return f"{dt.strftime('%A')}, {dt.strftime('%B')} {dt.day}"


def clean_inline(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = text.replace("_", " ")
    text = re.sub(r"[*`#]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -")


def clip(value: Any, limit: int) -> str:
    text = clean_inline(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rstrip()
    sentence_end = max(clipped.rfind("."), clipped.rfind(";"), clipped.rfind(":"))
    if sentence_end >= max(40, limit // 2):
        clipped = clipped[: sentence_end + 1]
    elif " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" .,:;") + "..."


def parse_json_object(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def parse_json_list(value: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def top_signals(inputs: FormatInputs) -> list[dict[str, Any]]:
    return parse_json_list(inputs.todays_signals)[:DELIVERY_TOP_ITEMS]


def signal_summary(signal: dict[str, Any], core_limit: int = 190, why_limit: int = 120) -> str:
    analysis = signal.get("analysis") if isinstance(signal.get("analysis"), dict) else {}
    relevance = analysis.get("relevance_to_me") if isinstance(analysis.get("relevance_to_me"), dict) else {}
    core = clip(analysis.get("core_finding"), core_limit) or "Depth signal available in the archive."
    why_parts = nonempty_values(relevance.get("current_work_connections"))
    why_now = clean_inline(relevance.get("why_now"))
    why = clip("; ".join(why_parts[:1]) or why_now, why_limit)
    source = clean_inline(signal.get("source")) or "source"
    url = str(signal.get("url") or "").strip()
    link = f"[{source}]({url})" if url.startswith("http") else source
    title = clip(signal.get("title") or "(untitled)", 90)
    why_sentence = f" {why}" if why else ""
    return f"**{title}** — {core}{why_sentence} {link}".strip()


def selected_decisions(inputs: FormatInputs) -> list[str]:
    decisions: list[str] = []
    for action in inputs.actions[:3]:
        title = re.search(r"(?m)^title:\s*(.+)$", action)
        proposed = re.search(r"(?m)^proposed_action:\s*(.+)$", action)
        card_id = re.search(r"(?m)^id:\s*(.+)$", action)
        label = clean_inline(title.group(1) if title else "Pending action")
        detail = clean_inline(proposed.group(1) if proposed else "")
        suffix = f" [{clean_inline(card_id.group(1))}]" if card_id else ""
        decisions.append(clip(f"{label}: {detail}{suffix}", 180))

    improvements = parse_json_object(inputs.improvements)
    for candidate in (improvements.get("candidates") or [])[:5]:
        if not isinstance(candidate, dict):
            continue
        try:
            score = float(candidate.get("aggregate_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score < 7:
            continue
        change = clip(candidate.get("proposed_change"), 170)
        if change:
            decisions.append(f"{change} (score {score:g}/10)")
        if len(decisions) >= 4:
            break
    return decisions


def pulse_line(inputs: FormatInputs) -> str:
    if inputs.cross_day_context == "no continuity context for today":
        return ""
    triage = parse_json_object(inputs.triage_summary)
    total = triage.get("total")
    depth = triage.get("depth")
    improvements = parse_json_object(inputs.improvements)
    recurring = 0
    for candidate in improvements.get("candidates") or []:
        if isinstance(candidate, dict) and int(candidate.get("recurrence_count") or 0) >= 3:
            recurring += 1
    pieces = []
    if total is not None:
        pieces.append(f"{total} items")
    if depth is not None:
        pieces.append(f"{depth} depth")
    if recurring:
        pieces.append(f"{recurring} recurring")
    return "; ".join(pieces)[:100]


def render_delivery_body(inputs: FormatInputs, archive_rel: str) -> str:
    signals = top_signals(inputs)
    if not signals:
        return "\n".join([
            f"# Vibe Squad — {weekday_label(inputs.date)}",
            "",
            "No notable signal today.",
        ])

    first_analysis = signals[0].get("analysis") if isinstance(signals[0].get("analysis"), dict) else {}
    lead = clip(first_analysis.get("core_finding"), 260)
    lines = [
        f"# Vibe Squad — {weekday_label(inputs.date)}",
        "",
        lead,
        "",
        "## Worth your time today (top 3)",
        "",
    ]
    lines.extend(f"{idx}. {signal_summary(signal)}" for idx, signal in enumerate(signals, 1))

    decisions = selected_decisions(inputs)
    if decisions:
        lines += ["", "## Decisions for you", ""]
        lines.extend(f"- {decision}" for decision in decisions)

    pulse = pulse_line(inputs)
    if pulse:
        lines += ["", "## Pulse", "", pulse]

    return "\n".join(lines).strip()


def fit_delivery_body(inputs: FormatInputs, archive_rel: str, subject: str) -> str:
    body = render_delivery_body(inputs, archive_rel)
    if len(render_newsletter(inputs.date, body, subject, archive_rel)) <= DELIVERY_CHAR_LIMIT:
        return body

    signals = top_signals(inputs)
    lines = [
        f"# Vibe Squad — {weekday_label(inputs.date)}",
        "",
        clip((signals[0].get("analysis") or {}).get("core_finding") if signals else "No notable signal today.", 180),
        "",
        "## Worth your time today (top 3)",
        "",
    ]
    lines.extend(
        f"{idx}. {signal_summary(signal, core_limit=135, why_limit=70)}"
        for idx, signal in enumerate(signals, 1)
    )
    body = "\n".join(lines).strip()
    if len(render_newsletter(inputs.date, body, subject, archive_rel)) <= DELIVERY_CHAR_LIMIT:
        return body
    suffix = "\n"
    wrapper_len = len(render_newsletter(inputs.date, "", subject, archive_rel))
    budget = max(200, DELIVERY_CHAR_LIMIT - wrapper_len - len(suffix) - 5)
    return body[:budget].rstrip() + suffix


def deterministic_newsletter(inputs: FormatInputs, reason: str) -> tuple[str, str]:
    signal_cards = render_signal_cards(inputs.todays_signals)
    improvements = inputs.improvements if inputs.improvements != "no proposals today" else ""
    signals = top_signals(inputs)
    subject = clip(signals[0].get("title") if signals else "Structured signals fallback", 80)
    parts = [
        "## Lead",
        f"Formatter fallback used because {reason}. See Today's signals for the depth analysis cards.",
        "",
    ]
    if improvements:
        parts += ["## System improvements proposed", "", "```json", truncate(improvements, 7000), "```", ""]
    parts += ["## Today's signals", "", signal_cards or "No depth signal cards available.", ""]
    if inputs.cross_day_context != "no continuity context for today":
        parts += ["## Continuity", "", inputs.cross_day_context, ""]
    parts += ["## Skim queue", "", "See triage summary for skim items.", "", "## What's out", "", "See triage summary for dropped items."]
    return "\n".join(parts).strip(), subject or "Structured signals fallback"


def build_prompt(inputs: FormatInputs) -> str:
    pending_actions = "\n\n---\n\n".join(inputs.actions) if inputs.actions else "none"
    return f"""You are the daily-newsletter editor for Vibe Squad's content brief. Produce a single markdown digest under 16 KB suitable for email. Required structure in this order:

{current_time_section()}

Use these exact markdown section headings, in this order:
1. ## Lead
   1-2 sentences: the single most important thing in today's brief, named explicitly. Picked from depth-tier items. If a content-action card is pending APPROVE, that takes precedence as the lead.
2. ## Decisions to make
   Only if pending action cards exist. List each card as a 2-3 line item with: title, why it matters, "Reply APPROVE or REJECT [card-id]". Skip section entirely if no cards.
3. ## System improvements proposed
   For each candidate from the input JSON, format as:
   **[IMP-id]: <proposed_change>** (avg score: <aggregate_score>/10) plus `🔁 recurring across N days` when recurrence_count >= 3 and `📈 score +X.X` or `📉 score -X.X` when absolute score_delta >= 1.5.
   - *Source:* [<title>](<url>)
   - *What it entails:* <what_it_entails>
   - *Risks:* <risks>; *Reversibility:* <reversibility>
   - *Model opinions:* claude <score>/10 (<opinion>); kimi <score>/10 (<opinion>); gpt-codex <score>/10 (<opinion>)
   - If divergence >= 3: *⚠️ models disagree*
   If the input JSON has no candidates, skip this section entirely.
4. ## Today's signals
   Render each item from TODAY'S SIGNALS exactly as:
   ### [<lane>] <Title>
   *Source: <link> | time horizon: <horizon>*
   **Core:** <core_finding>
   **Why for you:** <current_work_connections semicolon-joined> — <why_now>
   **What it enables:** bullet list
   **Immediate fixes:** bullet list, skip if empty
   **Hypothetical combos:** bullet list, skip if empty
   **Risks:** bullet/list
   **Connections:** bullet/list
   Skip subsections whose arrays are empty or contain only none/none observed.
5. ## Continuity
   Use this as the cross-day context if present and non-empty. If CROSS-DAY CONTEXT is exactly "no continuity context for today", do not print this section.
6. ## Skim queue
   5-12 items from highest-scoring skim items. One-line each, source-tagged. Group by lane if it adds clarity; flat list is also fine.
7. ## What's out
   1 sentence or skip if uninteresting. If anything notable was muted/dropped, mention by source/topic.
8. SUBJECT:
   Last block only. One line, <=80 chars, reflects today's lead story, no quotes, no "Daily Brief" prefix.

Constraints:
- Researcher-voice prose, not AI rhetorical tells. No "let me know if you have questions," no "I hope this helps," no triple-bullet emoji headers.
- Output only the newsletter markdown and final SUBJECT block. No preface, no analysis, no insight block.
- Do not call tools. This is a text-generation-only formatting pass.
- Do not invent content. Every named item, link, or fact must come from the input.
- Preserve all URLs verbatim from the input.
- If input is empty or near-empty, produce a 2-line "no notable signal today" digest.

Input:
=== MORNING BRIEF ===
{inputs.morning or "(missing)"}

=== CONTENT SYNTHESIS ===
{inputs.synthesis or "(missing)"}

=== CROSS-DAY CONTEXT ===
{inputs.cross_day_context}

=== SYSTEM IMPROVEMENTS PROPOSED ===
{inputs.improvements}

=== TODAY'S SIGNALS ===
{inputs.todays_signals}

=== PENDING ACTION CARDS ===
{pending_actions}

=== TRIAGE SUMMARY ===
{inputs.triage_summary}
"""


def call_claude(prompt: str) -> tuple[int, str, str, float]:
    if not shutil.which(CLAUDE_BIN):
        return 127, "", f"{CLAUDE_BIN} not found", 0.0
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    start = time.monotonic()
    try:
        result = subprocess.run(
            [
                CLAUDE_BIN,
                "-p",
                "--output-format",
                "text",
                "--no-session-persistence",
                "--allowed-tools",
                "",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        return result.returncode, result.stdout or "", result.stderr or "", time.monotonic() - start
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\nclaude command timed out after 300s"
        return 124, stdout, stderr, time.monotonic() - start


def extract_subject(raw: str) -> tuple[str, str]:
    lines = raw.strip().splitlines()
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        stripped = line.strip().strip("#` ")
        match = re.match(r"^(?:\*\*)?SUBJECT:(?:\*\*)?\s*(.*)$", stripped)
        if not match:
            continue
        tail = [l.strip() for l in lines[idx + 1 :] if l.strip()]
        inline_subject = match.group(1).strip().strip("*` ")
        if not inline_subject:
            if len(tail) != 1:
                continue
            subject = tail[0].strip("*` ")
            body = "\n".join(lines[:idx]).strip()
            if body and subject:
                return body, subject
            continue
        if tail:
            continue
        body = "\n".join(lines[:idx]).strip()
        if body:
            return body, inline_subject
    raise ValueError("Claude response missing parseable SUBJECT block")


def normalize_body(body: str) -> str:
    text = body.strip()
    lead_match = re.search(r"(?m)^## Lead\s*$", text)
    if lead_match:
        text = text[lead_match.start() :].strip()
        return re.sub(
            r"(?ms)^## Continuity\s*\n\s*no continuity context for today\s*(?=\n## |\Z)",
            "",
            text,
        ).strip()

    split_match = re.search(r"(?m)^## Today's signals\s*$", text)
    if split_match:
        lead = text[: split_match.start()].strip()
        rest = text[split_match.start() :].lstrip()
        lead_lines = [
            line
            for line in lead.splitlines()
            if not re.match(r"^#(?!#)\s+", line.strip())
        ]
        lead = "\n".join(lead_lines).strip()
        if lead:
            return f"## Lead\n{lead}\n\n{rest}".strip()

    return f"## Lead\n{text}".strip()


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def clamp_subject(subject: str, limit: int = 80) -> str:
    subject = " ".join(subject.split())
    if len(subject) <= limit:
        return subject
    clipped = subject[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" .:-")


def render_newsletter(date: str, body: str, subject: str, archive_path: str = "") -> str:
    subject = clamp_subject(subject)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    archive_line = f"archive_path: {archive_path}\n" if archive_path else ""
    return f"---\ndate: {date}\nsubject: {yaml_quote(subject)}\ngenerated_at: {generated_at}\n{archive_line}---\n\n{body.strip()}\n"


def write_failure_log(path: Path, date: str, reason: str, prompt: str, stdout: str = "", stderr: str = "", duration: float = 0.0) -> None:
    content = f"""# Newsletter Format - {date}

Run at: {datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
Status: failed
Reason: {reason}
Prompt length: {len(prompt)}
Stdout length: {len(stdout)}
Stderr length: {len(stderr)}
Duration seconds: {duration:.1f}

## Stdout first 1000

```
{stdout[:1000]}
```

## Stderr first 4000

```
{stderr[:4000]}
```
"""
    atomic_write(path, content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--morning")
    parser.add_argument("--synthesis")
    parser.add_argument("--triage")
    parser.add_argument("--actions-dir")
    parser.add_argument("--output")
    parser.add_argument("--log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs = load_inputs(args)
    output_path = Path(args.output or STATE_DIR / f"newsletter-{inputs.date}.md")
    archive_path = STATE_DIR / f"newsletter-archive-{inputs.date}.md"
    archive_rel = f"_state/newsletter-archive-{inputs.date}.md"
    log_path = Path(args.log or STATE_DIR / "cleanup-logs" / f"{inputs.date}-newsletter-format.md")

    if no_signal(inputs):
        body, subject = build_no_signal_newsletter(inputs)
        atomic_write(archive_path, render_newsletter(inputs.date, body, subject))
        atomic_write(output_path, render_newsletter(inputs.date, body, subject, archive_rel))
        print(f"Newsletter: {output_path}")
        return 0

    prompt = build_prompt(inputs)
    rc, stdout, stderr, duration = call_claude(prompt)
    if rc != 0:
        write_failure_log(log_path, inputs.date, f"claude exited {rc}", prompt, stdout, stderr, duration)
        archive_body, subject = deterministic_newsletter(inputs, f"claude exited {rc}")
        delivery_body = fit_delivery_body(inputs, archive_rel, subject)
        atomic_write(archive_path, render_newsletter(inputs.date, archive_body, subject))
        atomic_write(output_path, render_newsletter(inputs.date, delivery_body, subject, archive_rel))
        print(f"Newsletter: {output_path} (fallback)")
        return 0

    try:
        archive_body, subject = extract_subject(stdout)
    except ValueError as exc:
        write_failure_log(log_path, inputs.date, str(exc), prompt, stdout, stderr, duration)
        archive_body, subject = deterministic_newsletter(inputs, str(exc))
        delivery_body = fit_delivery_body(inputs, archive_rel, subject)
        atomic_write(archive_path, render_newsletter(inputs.date, archive_body, subject))
        atomic_write(output_path, render_newsletter(inputs.date, delivery_body, subject, archive_rel))
        print(f"Newsletter: {output_path} (fallback)")
        return 0

    archive_body = normalize_body(archive_body)
    archive_body = enforce_todays_signals(archive_body, inputs.todays_signals)
    delivery_body = fit_delivery_body(inputs, archive_rel, subject)
    atomic_write(archive_path, render_newsletter(inputs.date, archive_body, subject))
    atomic_write(output_path, render_newsletter(inputs.date, delivery_body, subject, archive_rel))
    print(f"Newsletter: {output_path}; archive: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
