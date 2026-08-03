#!/usr/bin/env python3
"""Coverage ledger: make technique omission impossible to do silently.

A campaign is scanned for measured evidence that each APPLICABLE technique was
exercised. Every applicable technique resolves to exactly one of:

    USED      at least one instrument left evidence of a real run
    DECLINED  a reason was recorded AND its citation verifies against the artifact
    MISSED    applicable, no evidence, no reason  <- the defect state

The close gate refuses a campaign while any entry is MISSED. Declining is always
allowed. Forgetting is not.

Subcommands
    scan      classify one campaign, emit a ledger JSON
    report    render markdown for one or more ledgers, plus a cumulative view
    gate      exit non-zero while any entry is MISSED or a decline fails to verify
    controls  run the positive-control fixture suite

Runtime state defaults outside the tracked tree: $COVERAGE_LEDGER_STATE, else
$XDG_STATE_HOME/coverage-ledger, else $HOME/.local/state/coverage-ledger, else
$TMPDIR/coverage-ledger.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from itertools import islice
from pathlib import Path

RIG_DIR = Path(__file__).resolve().parent

TIER_NAMES = {1: "tool_output", 2: "artifact_footprint", 3: "action_log"}
TIER_BLURB = {
    1: "literal native tool output",
    2: "artifact only a real run creates",
    3: "action-log record (lane-attested)",
}

# Directories holding the TARGET's own source. Excluded from both walking and
# reading: a target repo frequently ships its own fuzz corpora, test caches and
# CI logs, and counting those would credit us with the target's artifacts.
TARGET_TREES = {"repo", "core-repo", "snapshot", "crytic-export", "vendor"}
# Never descended: no evidence, huge, or machine-generated.
PRUNE_WALK = {".git", "node_modules", "__pycache__", ".venv"}
# Walked so paths still match tier-2 signatures, but never read for tier-1.
# Matched as a pattern, not a literal set: Foundry writes out-v9, out-v10, ... and
# an exact-name check silently admitted 144 MB of compiler build-info per campaign.
PRUNE_CONTENT_RE = re.compile(
    r"^(out|target|build|dist|artifacts|build-info|cache|coverage)([-_.].*|\d.*)?$")
# Bulk machine artifacts that are read-expensive and evidence-free. Coverage dumps
# additionally EMBED the target's own source, so reading them would credit
# source-review to a fuzzer's output file.
SKIP_CONTENT_RE = re.compile(
    r"(^covered\.\d+\.|\.lcov$|^coverage_report\.html$|^combined_solc\.json$)")

READ_SUFFIXES = {
    ".md", ".txt", ".log", ".json", ".jsonl", ".err", ".out", ".csv", ".stderr",
    ".stdout", ".lcov", ".tsv", ".yaml", ".yml", ".sol", ".rs", ".go", ".sha256",
    ".toml",
}
DEFAULT_MAX_READ_BYTES = 4 * 1024 * 1024
EVIDENCE_CAP = 3

ACTION_LOG_NAME = re.compile(r"action[-_]log", re.I)
EXIT_TOKEN = re.compile(r"\bexit(?:[ _]?code)?\b\s*[:= ]\s*-?\d+", re.I)
EXIT_KEYS = ("exit_code", "exitcode", "exit", "returncode", "status_code")


# ---------------------------------------------------------------- config load


def load_tsv(path: Path) -> list[dict[str, str]]:
    """Read a #-commented TSV whose first non-comment line is the header."""
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = line.split("\t")
            if header is None:
                header = cells
                continue
            cells += [""] * (len(header) - len(cells))
            rows.append(dict(zip(header, cells)))
    if header is None:
        raise SystemExit(f"{path}: no header row")
    return rows


@dataclass
class Signature:
    instrument: str
    tier: int
    kind: str
    pattern: str
    note: str
    regex: re.Pattern
    ci: bool = False


def load_signatures(path: Path) -> list[Signature]:
    sigs = []
    for row in load_tsv(path):
        ci = "i" in (row.get("flags") or "")
        # MULTILINE because matching runs over whole-file text, not line by line;
        # without it the ^-anchored signatures would only ever match at byte 0.
        flags = re.M | (re.I if ci else 0)
        try:
            rx = re.compile(row["pattern"], flags)
        except re.error as exc:
            raise SystemExit(f"{path}: bad regex for {row['instrument_id']}: {exc}")
        sigs.append(Signature(
            instrument=row["instrument_id"],
            tier=int(row["tier"]),
            kind=row["kind"],
            pattern=row["pattern"],
            note=row.get("note", ""),
            regex=rx,
            ci=ci,
        ))
    return sigs


def build_union(sigs: list[Signature]) -> re.Pattern:
    """One alternation used purely as a cheap reject filter.

    Most artifact files contain no signature at all. A single C-level scan rejects
    them, so the per-signature pass only runs on files that hold something. The
    union is never used for attribution -- inner capturing groups in the component
    patterns make `lastgroup` unreliable -- so which signature matched is resolved
    by the second pass.
    """
    parts = [f"(?:(?i:{s.pattern}))" if s.ci else f"(?:{s.pattern})" for s in sigs]
    return re.compile("|".join(parts), re.M)


@dataclass
class Config:
    techniques: dict[str, dict[str, str]]
    applicability: dict[str, list[dict[str, str]]]
    signatures: list[Signature]
    campaigns: dict[str, dict[str, str]]

    @classmethod
    def load(cls, rig: Path) -> "Config":
        techs = {r["technique_id"]: r for r in load_tsv(rig / "techniques.tsv")}
        appl: dict[str, list[dict[str, str]]] = {}
        for row in load_tsv(rig / "applicability.tsv"):
            if row["technique_id"] not in techs:
                raise SystemExit(
                    f"applicability.tsv references unknown technique {row['technique_id']!r}")
            appl.setdefault(row["target_class"], []).append(row)
        sigs = load_signatures(rig / "signatures.tsv")
        known = {s.instrument for s in sigs}
        for rows in appl.values():
            for row in rows:
                for inst in split_list(row["instruments"]):
                    if inst not in known:
                        raise SystemExit(
                            f"applicability.tsv names instrument {inst!r} with no signature")
        camps: dict[str, dict[str, str]] = {}
        camp_path = rig / "campaigns.tsv"
        if camp_path.exists():
            camps = {r["campaign_id"]: r for r in load_tsv(camp_path)}
        return cls(techs, appl, sigs, camps)


def split_list(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def default_state_dir() -> Path:
    env = os.environ.get("COVERAGE_LEDGER_STATE")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "coverage-ledger"
    home = os.environ.get("HOME")
    if home:
        return Path(home) / ".local" / "state" / "coverage-ledger"
    return Path(tempfile.gettempdir()) / "coverage-ledger"


# ------------------------------------------------------------------- scanning


@dataclass
class Evidence:
    instrument: str
    tier: int
    tier_name: str
    source: str
    line: int
    text: str
    signature: str


@dataclass
class Entry:
    technique_id: str
    name: str
    status: str
    instruments: list[str]
    used_instruments: list[str] = field(default_factory=list)
    best_tier: int | None = None
    evidence: list[Evidence] = field(default_factory=list)
    decline_reason: str = ""
    decline_citation: str = ""
    decline_error: str = ""


def truncate(text: str, limit: int = 220) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " ..."


def iter_campaign_files(roots: list[tuple[str, Path]], exclude: set[str],
                        max_bytes: int):
    """Yield (label_relpath, abs_path, readable) for every file under the roots."""
    for label, root in roots:
        if root.is_file():
            yield f"{label}/{root.name}", root, root.stat().st_size <= max_bytes
            continue
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            rel_dir = here.relative_to(root)
            # Prune before descending. Path signatures for pruned target trees are
            # intentionally not collected -- they are not our work product.
            kept = []
            for d in sorted(dirnames):
                if d in PRUNE_WALK or d in exclude:
                    continue
                kept.append(d)
            dirnames[:] = kept
            content_blocked = any(PRUNE_CONTENT_RE.match(p) for p in rel_dir.parts)
            for name in sorted(filenames):
                path = here / name
                rel = Path(label) / rel_dir / name
                rel_str = str(rel).replace("\\", "/").replace("/./", "/")
                readable = (
                    not content_blocked
                    and path.suffix.lower() in READ_SUFFIXES
                    and not SKIP_CONTENT_RE.search(name)
                )
                if readable:
                    try:
                        readable = path.stat().st_size <= max_bytes
                    except OSError:
                        readable = False
                yield rel_str, path, readable


def parse_action_log(path: Path, text: str) -> list[tuple[str, int]]:
    """Return (command, line_no) pairs that carry BOTH a command and an exit code.

    Requiring an exit code is what keeps a plan or arsenal list out of tier 3:
    a document that merely names a tool has no exit status to report.
    """
    out: list[tuple[str, int]] = []
    suffix = path.suffix.lower()

    def from_record(rec: object, line_no: int) -> None:
        if not isinstance(rec, dict):
            return
        cmd = rec.get("command") or rec.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():
            return
        if not any(k in rec for k in EXIT_KEYS):
            return
        out.append((cmd, line_no))

    if suffix == ".jsonl":
        for i, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                from_record(json.loads(line), i)
            except json.JSONDecodeError:
                continue
    elif suffix == ".json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            return out
        records = doc if isinstance(doc, list) else None
        if records is None and isinstance(doc, dict):
            for key in ("entries", "actions", "records", "log"):
                if isinstance(doc.get(key), list):
                    records = doc[key]
                    break
        for rec in records or []:
            from_record(rec, 0)
    else:
        for i, line in enumerate(text.splitlines(), 1):
            if EXIT_TOKEN.search(line):
                out.append((line, i))
    return out


def scan_campaign(cfg: Config, campaign_id: str, target_class: str,
                  roots: list[tuple[str, Path]], exclude: set[str],
                  max_bytes: int, declines: dict[str, dict[str, str]]) -> dict:
    path_sigs = [s for s in cfg.signatures if s.kind == "path_regex"]
    line_sigs = [s for s in cfg.signatures if s.kind == "line_regex"]
    cmd_sigs = [s for s in cfg.signatures if s.kind == "cmd_regex"]

    union = build_union(line_sigs)
    found: dict[str, list[Evidence]] = {}
    stats = {"files_seen": 0, "files_read": 0, "files_matched": 0,
             "bytes_read": 0, "action_logs": 0}

    def add(ev: Evidence) -> None:
        bucket = found.setdefault(ev.instrument, [])
        # Keep the strongest tiers; cap volume so a ledger stays readable.
        if len(bucket) >= EVIDENCE_CAP:
            weakest = max(bucket, key=lambda e: e.tier)
            if ev.tier < weakest.tier:
                bucket.remove(weakest)
            else:
                return
        if any(e.source == ev.source and e.signature == ev.signature for e in bucket):
            return
        bucket.append(ev)

    for rel, path, readable in iter_campaign_files(roots, exclude, max_bytes):
        stats["files_seen"] += 1
        for sig in path_sigs:
            if sig.regex.search(rel):
                add(Evidence(sig.instrument, sig.tier, TIER_NAMES[sig.tier],
                             rel, 0, rel, sig.pattern))
        if not readable:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        stats["files_read"] += 1
        stats["bytes_read"] += len(text)

        is_action_log = bool(ACTION_LOG_NAME.search(path.name))
        if is_action_log:
            stats["action_logs"] += 1
            for cmd, line_no in parse_action_log(path, text):
                for sig in cmd_sigs:
                    if sig.regex.search(cmd):
                        add(Evidence(sig.instrument, sig.tier, TIER_NAMES[sig.tier],
                                     rel, line_no, truncate(cmd), sig.pattern))

        if not union.search(text):
            continue
        stats["files_matched"] += 1
        for sig in line_sigs:
            for m in islice(sig.regex.finditer(text), EVIDENCE_CAP):
                line_no = text.count("\n", 0, m.start()) + 1
                start = text.rfind("\n", 0, m.start()) + 1
                end = text.find("\n", m.end())
                snippet = text[start:end if end != -1 else len(text)]
                add(Evidence(sig.instrument, sig.tier, TIER_NAMES[sig.tier],
                             rel, line_no, truncate(snippet), sig.pattern))

    rows = cfg.applicability.get(target_class)
    if rows is None:
        raise SystemExit(f"unknown target_class {target_class!r}; "
                         f"known: {sorted(cfg.applicability)}")

    entries: list[Entry] = []
    for row in rows:
        tid = row["technique_id"]
        tech = cfg.techniques[tid]
        instruments = split_list(row["instruments"])
        if row["applicability"] == "n_a":
            entries.append(Entry(tid, tech["name"], "N_A", instruments))
            continue
        used = [i for i in instruments if found.get(i)]
        entry = Entry(tid, tech["name"], "MISSED", instruments, used_instruments=used)
        if used:
            evs = sorted(
                (e for i in used for e in found[i]),
                key=lambda e: (e.tier, e.source),
            )[:EVIDENCE_CAP]
            entry.status = "USED"
            entry.best_tier = min(e.tier for e in evs)
            entry.evidence = evs
        else:
            dec = declines.get(tid)
            if dec:
                entry.decline_reason = dec["reason"]
                entry.decline_citation = dec.get("citation", "")
                if dec.get("error"):
                    entry.decline_error = dec["error"]
                    entry.status = "MISSED"
                else:
                    entry.status = "DECLINED"
        entries.append(entry)

    instrument_usage = {
        inst: {
            "best_tier": min(e.tier for e in evs),
            "hits": len(evs),
            "first_evidence": asdict(sorted(evs, key=lambda e: e.tier)[0]),
        }
        for inst, evs in sorted(found.items())
    }
    # Every instrument any applicable technique could have used, so a zero is visible.
    candidate_instruments = sorted({
        i for row in rows if row["applicability"] == "applies"
        for i in split_list(row["instruments"])
    })

    return {
        "schema": "coverage-ledger/v1",
        "campaign_id": campaign_id,
        "target_class": target_class,
        "roots": [{"label": lbl, "path": str(p)} for lbl, p in roots],
        "scan_stats": stats,
        "entries": [asdict(e) for e in entries],
        "instrument_usage": instrument_usage,
        "candidate_instruments": candidate_instruments,
        "unused_instruments": [i for i in candidate_instruments if i not in found],
        "summary": summarize(entries),
    }


def summarize(entries: list[Entry]) -> dict[str, int]:
    out = {"USED": 0, "DECLINED": 0, "MISSED": 0, "N_A": 0}
    for e in entries:
        out[e.status] += 1
    return out


# ------------------------------------------------------------------- declines


def load_declines(path: Path, repo_root: Path) -> dict[str, dict[str, str]]:
    """Load decline records and VERIFY each citation against the cited artifact.

    A decline is only honoured when its quoted text is found in the cited file.
    That is what stops a decline from being a free pass: you cannot decline a
    technique by asserting a reason, only by pointing at text that exists.
    """
    if not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in load_tsv(path):
        tid = row["technique_id"]
        rec = {
            "reason": row.get("reason", ""),
            "citation": row.get("citation_path", ""),
            "quote": row.get("citation_quote", ""),
            "error": "",
        }
        cite = (row.get("citation_path") or "").strip()
        quote = (row.get("citation_quote") or "").strip()
        if not cite or not quote:
            rec["error"] = "decline record needs both citation_path and citation_quote"
            out[tid] = rec
            continue
        cite_path = (repo_root / cite) if not Path(cite).is_absolute() else Path(cite)
        if not cite_path.exists():
            rec["error"] = f"cited artifact does not exist: {cite}"
            out[tid] = rec
            continue
        try:
            text = cite_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rec["error"] = f"cited artifact unreadable: {exc}"
            out[tid] = rec
            continue
        needle = " ".join(quote.split()).lower()
        line_no = 0
        for i, line in enumerate(text.splitlines(), 1):
            if needle in " ".join(line.split()).lower():
                line_no = i
                break
        if not line_no:
            rec["error"] = f"quoted text not found in {cite}"
        else:
            rec["citation"] = f"{cite}:{line_no}"
        out[tid] = rec
    return out


# -------------------------------------------------------------------- reports


def render_campaign(led: dict) -> str:
    s = led["summary"]
    lines = [
        f"### {led['campaign_id']}  ·  target class `{led['target_class']}`",
        "",
        f"**{s['USED']} used · {s['DECLINED']} declined · {s['MISSED']} missed** "
        f"({s['N_A']} not applicable). "
        f"Scanned {led['scan_stats']['files_seen']} files, "
        f"read {led['scan_stats']['files_read']}.",
        "",
        "| Technique | Status | Tier | Instrument | Evidence |",
        "|---|---|---|---|---|",
    ]
    for e in led["entries"]:
        if e["status"] == "N_A":
            continue
        if e["status"] == "USED":
            ev = e["evidence"][0]
            tier = f"{ev['tier']} {TIER_NAMES[ev['tier']]}"
            inst = ", ".join(e["used_instruments"])
            detail = f"`{ev['source']}`" + (f":{ev['line']}" if ev["line"] else "")
            detail += f"<br>`{md_cell(ev['text'])}`"
        elif e["status"] == "DECLINED":
            tier = "—"
            inst = "—"
            detail = f"{md_cell(e['decline_reason'])}<br>cited `{e['decline_citation']}`"
        else:
            tier = "—"
            inst = "—"
            detail = e["decline_error"] or "**no evidence, no recorded reason**"
        lines.append(
            f"| `{e['technique_id']}` | {status_badge(e['status'])} | {tier} | "
            f"{inst} | {detail} |")
    if led["unused_instruments"]:
        lines += ["", "Applicable instruments with **zero** evidence in this campaign: "
                  + ", ".join(f"`{i}`" for i in led["unused_instruments"]) + "."]
    return "\n".join(lines)


def status_badge(status: str) -> str:
    return {"USED": "USED", "DECLINED": "DECLINED", "MISSED": "**MISSED**",
            "N_A": "n/a"}[status]


def md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")[:180]


def render_cumulative(ledgers: list[dict]) -> str:
    campaigns = [l["campaign_id"] for l in ledgers]
    instruments = sorted({i for l in ledgers for i in l["candidate_instruments"]})
    lines = [
        "### Cumulative instrument usage",
        "",
        "Blank means the instrument was not applicable to that campaign's target class. "
        "`0` means it was applicable and left no evidence — the drift signal.",
        "",
        "| Instrument | " + " | ".join(campaigns) + " | campaigns used |",
        "|---" * (len(campaigns) + 2) + "|",
    ]
    for inst in instruments:
        cells, used_in = [], 0
        for led in ledgers:
            if inst not in led["candidate_instruments"]:
                cells.append("")
                continue
            usage = led["instrument_usage"].get(inst)
            if usage:
                cells.append(f"t{usage['best_tier']}")
                used_in += 1
            else:
                cells.append("**0**")
        flag = "" if used_in else "  ← never"
        lines.append(f"| `{inst}` | " + " | ".join(cells) + f" | {used_in}{flag} |")

    lines += ["", "### Cumulative technique coverage", "",
              "| Technique | " + " | ".join(campaigns) + " |",
              "|---" * (len(campaigns) + 1) + "|"]
    techs = sorted({e["technique_id"] for l in ledgers for e in l["entries"]})
    for tid in techs:
        cells = []
        for led in ledgers:
            match = next((e for e in led["entries"] if e["technique_id"] == tid), None)
            if match is None or match["status"] == "N_A":
                cells.append("n/a")
            elif match["status"] == "USED":
                cells.append(f"USED t{match['best_tier']}")
            else:
                cells.append(status_badge(match["status"]))
        lines.append(f"| `{tid}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ------------------------------------------------------------------- commands


def resolve_roots(cfg: Config, campaign_id: str, repo_root: Path,
                  explicit_root: Path | None) -> tuple[str, list[tuple[str, Path]], set[str]]:
    if explicit_root is not None:
        return "", [("campaign", explicit_root)], set()
    row = cfg.campaigns.get(campaign_id)
    if row is None:
        raise SystemExit(
            f"campaign {campaign_id!r} not in campaigns.tsv; pass --root and --target-class")
    roots: list[tuple[str, Path]] = []
    croot = repo_root / row["campaign_root"]
    if croot.exists():
        roots.append(("campaign", croot))
    run_id = (row.get("outbox_run_id") or "").strip()
    if run_id:
        needle = f"run_id: {run_id}"
        for outbox in sorted(repo_root.glob("departments/*/outbox")):
            for md in sorted(outbox.glob("*.md")):
                try:
                    head = md.read_text(encoding="utf-8", errors="replace")[:4000]
                except OSError:
                    continue
                if needle in head:
                    roots.append((f"outbox/{outbox.parent.name}", md))
    return row["target_class"], roots, set(split_list(row.get("exclude_dirs", "")))


def cmd_scan(args, cfg: Config) -> int:
    repo_root = Path(args.repo_root).resolve()
    explicit = Path(args.root).resolve() if args.root else None
    tclass, roots, exclude = resolve_roots(cfg, args.campaign, repo_root, explicit)
    target_class = args.target_class or tclass
    if not target_class:
        raise SystemExit("--target-class is required when --root is used")
    if not roots:
        raise SystemExit(f"no artifact roots resolved for {args.campaign}")
    exclude |= TARGET_TREES
    declines_path = (Path(args.declines) if args.declines
                     else RIG_DIR / "declines" / f"{args.campaign}.tsv")
    declines = load_declines(declines_path, repo_root)
    led = scan_campaign(cfg, args.campaign, target_class, roots, exclude,
                        args.max_read_bytes, declines)
    led["declines_file"] = str(declines_path.relative_to(repo_root)
                               if declines_path.is_relative_to(repo_root)
                               else declines_path)
    out = Path(args.out) if args.out else default_state_dir() / f"{args.campaign}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(led, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    s = led["summary"]
    print(f"LEDGER {args.campaign} class={target_class} "
          f"used={s['USED']} declined={s['DECLINED']} missed={s['MISSED']} "
          f"n_a={s['N_A']} -> {out}")
    return 0


def load_ledgers(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        if doc.get("schema") != "coverage-ledger/v1":
            raise SystemExit(f"{p}: not a coverage-ledger/v1 document")
        out.append(doc)
    return out


def cmd_report(args, cfg: Config) -> int:
    ledgers = load_ledgers(args.ledgers)
    parts = [f"## Per-campaign coverage\n"]
    parts += [render_campaign(l) for l in ledgers]
    if len(ledgers) > 1:
        parts.append("## Cumulative view\n")
        parts.append(render_cumulative(ledgers))
    text = "\n\n".join(parts) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"report -> {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_gate(args, cfg: Config) -> int:
    ledgers = load_ledgers(args.ledgers)
    failures: list[str] = []
    for led in ledgers:
        for e in led["entries"]:
            if e["status"] == "MISSED":
                why = e["decline_error"] or "no evidence and no recorded reason"
                failures.append(f"{led['campaign_id']}: {e['technique_id']} MISSED — {why}")
    for f in failures:
        print(f"GATE FAIL {f}")
    print(f"GATE_SUMMARY campaigns={len(ledgers)} missed={len(failures)}")
    if failures:
        print("A campaign cannot be reported closed while any entry is MISSED. "
              "Run the technique, or record a citation-backed decline.")
        return 1
    print("GATE PASS — every applicable technique is USED or citation-backed DECLINED.")
    return 0


def cmd_controls(args, cfg: Config) -> int:
    """Positive control: the extractor must find what is there and miss what is not."""
    fixtures = RIG_DIR / "fixtures"
    expected = load_tsv(fixtures / "expected.tsv")
    total = passed = 0
    cache: dict[tuple[str, str], dict] = {}
    for row in expected:
        key = (row["fixture"], row["target_class"])
        if key not in cache:
            root = fixtures / row["fixture"]
            if not root.exists():
                raise SystemExit(f"missing fixture {root}")
            declines = load_declines(
                fixtures / "declines" / f"{row['fixture']}.tsv", fixtures)
            cache[key] = scan_campaign(
                cfg, row["fixture"], row["target_class"],
                [("campaign", root)], set(TARGET_TREES),
                DEFAULT_MAX_READ_BYTES, declines)
        led = cache[key]
        entry = next((e for e in led["entries"]
                      if e["technique_id"] == row["technique_id"]), None)
        total += 1
        got = entry["status"] if entry else "ABSENT"
        ok = got == row["expected_status"]
        detail = ""
        if ok and row.get("expected_max_tier"):
            want = int(row["expected_max_tier"])
            got_tier = entry.get("best_tier")
            if got_tier is None or got_tier > want:
                ok = False
                detail = f" (tier {got_tier} weaker than required {want})"
        if ok:
            passed += 1
        print(f"{'PASS' if ok else 'FAIL'} {row['fixture']}/{row['technique_id']} "
              f"expected={row['expected_status']} got={got}{detail}")
    failed = total - passed
    print(f"CONTROL_SUMMARY total={total} passed={passed} failed={failed}")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rig", default=str(RIG_DIR), help="rig directory holding the TSVs")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="classify one campaign")
    p.add_argument("campaign")
    p.add_argument("--repo-root", default=".")
    p.add_argument("--root", help="scan this directory instead of campaigns.tsv")
    p.add_argument("--target-class")
    p.add_argument("--declines")
    p.add_argument("--out")
    p.add_argument("--max-read-bytes", type=int, default=DEFAULT_MAX_READ_BYTES)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("report", help="render markdown from ledgers")
    p.add_argument("ledgers", nargs="+")
    p.add_argument("--out")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("gate", help="refuse closure while anything is MISSED")
    p.add_argument("ledgers", nargs="+")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("controls", help="run the positive-control fixture suite")
    p.set_defaults(func=cmd_controls)

    args = ap.parse_args()
    cfg = Config.load(Path(args.rig))
    return args.func(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
