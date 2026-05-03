#!/usr/bin/env python3
"""
upgrade-specialists.py - Inject v1.1 schema sections into all 39 specialist files.

Reads shared/api-catalog.md for tool pre-fill matched by Lead-CLI.
Atomic write via temp+fsync+rename per squad convention.
Idempotent: skips files that already have ## Tools available to me heading.

For each departments/<lead>/specialists/<name>.md:
  1. Read existing content.
  2. If "## Tools available to me" heading is present, skip (already upgraded).
  3. Determine the specialist's Lead and CLI from the path.
  4. Pre-fill MCP / native-flag lists from shared/api-catalog.md verified entries
     for the specialist's Lead-CLI pane.
  5. Inject 4 required v1.1 sections AFTER the existing role description, BEFORE
     any trailing H2 sections we don't recognize.
  6. Leave <FILL: ...> placeholders for human-judgment fields.
  7. Atomic write via tempfile + fsync + rename.

After all 39 files, write report to _state/upgrade-specialists-report-2026-05-02.md.

Run with VAULT_ROOT env override or default ~/Obsidian-Claude-Vibe-Squad.
Optional: --dry-run prints what would be written for one file (path arg) without
disk modification.
"""
import argparse
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
SPECIALISTS_DIR = VAULT / "departments"
API_CATALOG = VAULT / "shared/api-catalog.md"
REPORT_PATH = VAULT / "_state/upgrade-specialists-report-2026-05-02.md"

LEAD_CLI = {
    "coding": "codex",
    "security": "claude",
    "content": "gemini",
    "sysmgmt": "claude",
    "research": "kimi",
}

# Map a Lead to the pane label used in api-catalog Section 9 per-pane matrix.
LEAD_PANE = {
    "coding": "coding pane (codex)",
    "security": "security pane (claude)",
    "content": "content pane (gemini)",
    "sysmgmt": "sysmgmt pane (claude)",
    "research": "research pane (kimi)",
}

# api-catalog H2 sections that contain native CLI features per family.
CLI_SECTION_HEADER = {
    "claude": "## 1. Anthropic / Claude",
    "codex": "## 2. OpenAI / Codex",
    "gemini": "## 3. Google / Gemini",
    "kimi": "## 4. Moonshot / Kimi",
}

# Section 9 header — chrono MCPs squad-wide (per-pane matrix).
CHRONO_MCP_SECTION = "## 9. chrono MCPs squad-wide"

V11_SECTION_MARKER = "## Tools available to me"

# Hardcoded role -> skill mapping (top 3-5 per Lead). Anything not in this map
# falls back to a generic per-Lead set + a <FILL: ...> placeholder so the
# Lead author can supply specialist-specific skills.
LEAD_DEFAULT_SKILLS = {
    "coding": [
        "code-review-loop",
        "review-severity-ladder",
        "verification-before-completion",
        "test-driven-development",
        "systematic-debugging",
    ],
    "security": [
        "agentic-safety-audit",
        "supply-chain-audit",
        "pre-audit-threat-model",
        "cvss-v4-gate",
        "scope-gate",
    ],
    "content": [
        "writing-skills",
        "cite-properly",
        "skill-description-trigger-authoring",
    ],
    "sysmgmt": [
        "kg-vault-health-check",
        "stale-knowledge-purge",
        "harness-baseline-audit",
        "instinct-prune-loop",
    ],
    "research": [
        "find-sources",
        "summarize-findings",
        "research-integrity-gate",
        "cite-properly",
        "evidence-level",
        "source-triangulation",
    ],
}

# Per-specialist override (populated for the well-known Tier-A specialists).
# Falls back to LEAD_DEFAULT_SKILLS otherwise.
SPECIALIST_SKILL_OVERRIDE = {
    "code-reviewer": [
        "code-review-loop",
        "review-severity-ladder",
        "dimensional-analysis-check",
        "diff-aware-semgrep-scan",
        "differential-review",
    ],
    "exploit-developer": [
        "pwntools-exploit-authoring",
        "binary-re-pipeline",
        "fuzzing-campaign-flow",
        "xbow-benchmark-runner",
    ],
    "scout": [
        "recon-chain-orchestrator",
        "nuclei-scan",
        "scope-gate",
        "github-recon",
        "api-surface-mapper",
    ],
    "security-analyst": [
        "security-threat-model",
        "supply-chain-audit",
        "agentic-safety-audit",
        "semgrep-rule-author",
        "findings-filter",
    ],
    "threat-modeler": [
        "security-threat-model",
        "pre-audit-threat-model",
        "agentic-safety-audit",
    ],
    "impact-validator": [
        "cvss-v4-gate",
        "chain-impact-rescore",
        "self-inflicted-detector",
        "program-fit-check",
        "nvd-osv-calibration",
    ],
    "architect": [
        "boundary-design",
        "data-model-contract",
        "c4-model-authoring",
        "interface-ambiguity-check",
    ],
    "backend-engineer": [
        "fastapi-service-boot",
        "axum-tokio-pattern",
        "async-scraper-pipeline",
        "mcp-server-cdp-pattern",
    ],
    "frontend-engineer": [
        "frontend-visual-discipline",
        "tailwind-class-management",
        "react-performance-loop",
        "playwright-session-recorder",
    ],
    "ui-engineer": [
        "frontend-design",
        "design-token-governance",
        "a11y-audit",
        "figma-to-code-fidelity",
    ],
    "test-engineer": [
        "property-based-fuzz-harness",
        "chrono-property-based-strategy",
        "chrono-mutation-campaign",
        "test-shrinkage-loop",
    ],
    "designer": [
        "design-token-governance",
        "a11y-audit",
        "figma-to-code-fidelity",
        "chrono-ui-aesthetic-framework",
    ],
    "technical-writer": [
        "chrono-handoff-authoring",
        "chrono-adr-authoring",
        "chrono-changelog-generator",
        "binary-doc-to-markdown",
    ],
    "ai-engineer": [
        "mcp-tool-design",
        "agent-architecture-pattern",
        "multi-model-routing-discipline",
        "rag-eval-loop",
    ],
    "devops-engineer": [
        "terraform-state-hygiene",
        "k8s-deploy-loop",
        "cc-hooks-ci-discipline",
        "bounty-sandbox-provision",
    ],
    "performance-optimizer": [
        "flamegraph-triage-flow",
        "thread-sweet-spot-profiling",
        "cross-arch-compute-routing",
    ],
    "refactor-cleaner": [
        "ast-rewrite-loop",
        "comby-semantic-patch",
        "dead-code-elimination",
        "import-reorg",
    ],
    "scraping-engineer": [
        "browser-scrape-pipeline",
        "playwright-stealth-config",
        "scrape-state-persistence",
        "data-normalization",
        "bot-evasion-loop",
    ],
    "smart-contract-engineer": [
        "evm-audit-flow",
        "solana-audit-flow",
        "defi-invariant-check",
        "vulnhunter-solana",
        "multi-stance-audit-fanout",
    ],
    "systems-engineer": [
        "compiler-bootstrap-flow",
        "cross-arch-build-discipline",
        "hybrid-threading-tuning",
        "simd-porting-layer",
    ],
    "research": [
        "find-sources",
        "research-integrity-gate",
        "cite-properly",
        "evidence-level",
        "source-triangulation",
        "summarize-findings",
    ],
    "synthesizer": [
        "preserve-outliers",
        "summarize-findings",
        "evidence-level",
    ],
    "large-context-analyst": [
        "layered-analysis-loop",
        "dual-level-retrieval",
        "claim-validation-gate",
        "scope-estimation",
        "cross-file-relationship-synthesis",
    ],
    "memory-curator": [
        "kg-vault-health-check",
        "instinct-prune-loop",
        "brain-trio-amendment-authoring",
        "stale-knowledge-purge",
    ],
    "harness-optimizer": [
        "harness-baseline-audit",
        "leverage-area-identification",
        "reversible-change-protocol",
    ],
    "loop-operator": [
        "loop-checkpoint-protocol",
        "stall-detection",
        "safe-intervention",
    ],
    "prompt-engineer": [
        "prompt-compression",
        "few-shot-curation",
        "prompt-regression-suite",
        "chrono-prompt-lint",
        "adversarial-prompt-review",
    ],
}


def parse_api_catalog(catalog_path: Path) -> dict:
    """Parse shared/api-catalog.md into a structured dict.

    Returns:
        {
            "cli_features": {
                "claude": [{"name": ..., "verified": "yes"}, ...],
                "codex":  [...],
                "gemini": [...],
                "kimi":   [...],
            },
            "chrono_mcps": [
                {"name": "chrono-vault MCP", "purpose": "...",
                 "panes": {"coding pane (codex)": "yes", ...}},
                ...
            ],
        }
    """
    if not catalog_path.exists():
        sys.exit(f"FATAL: {catalog_path} does not exist. Run Task 4 first.")
    text = catalog_path.read_text()
    lines = text.split("\n")

    cli_features = {cli: [] for cli in CLI_SECTION_HEADER}
    chrono_mcps = []

    # Walk the file line by line, tracking which H2 section we're inside.
    current_h2 = None
    current_h3_block = None  # accumulating the H3 entry's lines
    current_h3_name = None

    def flush_h3():
        """Process the just-finished H3 block based on the section it lived in."""
        nonlocal current_h3_block, current_h3_name
        if current_h3_block is None or current_h3_name is None:
            current_h3_block = None
            current_h3_name = None
            return
        block_text = "\n".join(current_h3_block)

        # Section 1-4: native CLI features per family.
        for cli, header in CLI_SECTION_HEADER.items():
            if current_h2 == header:
                # Look for "verified: yes" (NOT yes-as-subcommand or no or
                # needs-research).
                m = re.search(r"^- verified:\s*(\S.*)$", block_text, re.MULTILINE)
                if m and m.group(1).strip() == "yes":
                    cli_features[cli].append({
                        "name": current_h3_name,
                        "verified": "yes",
                    })
                # yes-as-subcommand also counts as verified for citation.
                elif m and m.group(1).strip().startswith("yes-as-subcommand"):
                    cli_features[cli].append({
                        "name": current_h3_name,
                        "verified": "yes-as-subcommand",
                    })
                break

        # Section 9: chrono MCPs squad-wide (per-pane matrix).
        if current_h2 == CHRONO_MCP_SECTION:
            purpose_m = re.search(r"^- purpose:\s*(.+)$", block_text, re.MULTILINE)
            purpose = purpose_m.group(1).strip() if purpose_m else ""
            panes = {}
            # Lines like "  - coding pane (codex): yes - <evidence>" inside
            # the "verified per pane:" sub-list.
            for pane_label in LEAD_PANE.values():
                # Match "  - <pane-label>: <yes|no>" with anything after.
                escaped = re.escape(pane_label)
                pm = re.search(
                    rf"^\s*-\s*{escaped}:\s*(yes|no)\b",
                    block_text,
                    re.MULTILINE,
                )
                if pm:
                    panes[pane_label] = pm.group(1)
            chrono_mcps.append({
                "name": current_h3_name,
                "purpose": purpose,
                "panes": panes,
            })

        current_h3_block = None
        current_h3_name = None

    for line in lines:
        if line.startswith("## "):
            # New H2 - flush any pending H3 first.
            flush_h3()
            current_h2 = line.rstrip()
            continue
        if line.startswith("### "):
            # New H3 - flush previous and start collecting.
            flush_h3()
            current_h3_name = line[4:].strip()
            current_h3_block = []
            continue
        if current_h3_block is not None:
            current_h3_block.append(line)

    # Flush the final H3 at EOF.
    flush_h3()

    return {
        "cli_features": cli_features,
        "chrono_mcps": chrono_mcps,
    }


def select_top_cli_features(cli_features: list, cli: str, limit: int = 6) -> list:
    """Pick the most relevant verified CLI features for the given CLI.

    Heuristic: hand-curated per-CLI ranked list. Falls back to the first N
    verified entries if curated list is empty.
    """
    curated_by_cli = {
        "claude": [
            "claude --effort {low,medium,high,xhigh,max}",
            "claude --model <model>",
            "claude --bare",
            "claude --json-schema",
            "claude -p / --print",
            "claude --append-system-prompt <prompt>",
        ],
        "codex": [
            "codex -m / --model <MODEL>",
            "codex -c model_reasoning_effort=high",
            "codex -s / --sandbox <SANDBOX_MODE> {read-only,workspace-write,danger-full-access}",
            "codex --search",
            "codex exec (alias e)",
            "codex review",
        ],
        "gemini": [
            "gemini -m / --model <model>",
            "gemini --thinking",
            "gemini -p / --prompt <text>",
            "gemini --approval-mode {default,auto_edit,yolo,plan}",
            "gemini -o / --output-format {text,json,stream-json}",
            "gemini --include-directories <dirs...>",
        ],
        "kimi": [
            "kimi -m / --model <text>",
            "kimi --thinking / --no-thinking",
            "kimi -p / --prompt <text> (alias -c / --command)",
            "kimi --print",
            "kimi --max-steps-per-turn <N>",
            "kimi --input-format / --output-format {text,stream-json}",
        ],
    }
    verified_names = {f["name"] for f in cli_features}
    curated = curated_by_cli.get(cli, [])
    selected = [n for n in curated if n in verified_names][:limit]
    if not selected:
        # Fallback: first N verified.
        selected = [f["name"] for f in cli_features[:limit]]
    return selected


def select_chrono_mcps_for_pane(chrono_mcps: list, pane_label: str) -> list:
    """Return chrono-* MCPs verified yes for the given pane."""
    out = []
    for mcp in chrono_mcps:
        if mcp["panes"].get(pane_label) == "yes":
            out.append({"name": mcp["name"], "purpose": mcp["purpose"]})
    return out


def select_skills(specialist_name: str, lead: str) -> list:
    """Return curated skill list for this specialist."""
    if specialist_name in SPECIALIST_SKILL_OVERRIDE:
        return SPECIALIST_SKILL_OVERRIDE[specialist_name]
    return LEAD_DEFAULT_SKILLS.get(lead, [])


def build_v11_sections(
    specialist_name: str,
    lead: str,
    cli: str,
    catalog: dict,
) -> str:
    """Generate the 4 v1.1 sections markdown for a specialist.

    Pre-fills MCPs/CLI features/skills from catalog; leaves <FILL: ...>
    placeholders for human-judgment fields (peer specialist names, escalation
    triggers, role-specific never-do items).
    """
    pane_label = LEAD_PANE[lead]

    chrono_mcps = select_chrono_mcps_for_pane(catalog["chrono_mcps"], pane_label)
    cli_flags = select_top_cli_features(catalog["cli_features"][cli], cli)
    skills = select_skills(specialist_name, lead)

    # Always-true MCPs go first (chrono-vault + sequential-thinking are universal
    # baseline). Anything the catalog confirms for this pane goes below.
    mcp_lines = []
    for mcp in chrono_mcps:
        mcp_lines.append(
            f"- `{mcp['name']}` - {mcp['purpose']}. "
            "Use when: this MCP's purpose matches the task shape."
        )
    if not mcp_lines:
        mcp_lines.append(
            "- <FILL: pane has no chrono-* MCPs verified yet; install per Task 6 "
            "(Hybrid Path A) before citing>"
        )

    cli_lines = [
        f"- `{flag}` - see `shared/api-catalog.md` for verified usage notes."
        for flag in cli_flags
    ]
    if not cli_lines:
        cli_lines.append(
            "- <FILL: no native CLI features pre-filled; consult "
            "`shared/api-catalog.md` Section for this CLI>"
        )

    skill_lines = [f"- `{s}`" for s in skills]
    skill_lines.append(
        "- <FILL: additional skills specific to this specialist's task shape>"
    )

    api_lines = [
        "- `OBSIDIAN_REST_API_KEY` -> chrono-obsidian MCP - "
        "for vault read/write when chrono-obsidian is verified for this pane.",
        "- <FILL: additional API keys this specialist needs (see "
        "`~/.config/shell/secrets.zsh` for available keys)>",
    ]

    sections = "\n".join([
        "",
        "",
        "## Tools available to me",
        "",
        "### MCPs (verified-installed only)",
        *mcp_lines,
        "",
        f"### Native CLI features (verified, my CLI is `{cli}`)",
        *cli_lines,
        "",
        "### Skills (read these on task start)",
        *skill_lines,
        "",
        "### APIs available (via env)",
        *api_lines,
        "",
        "## When to fan out",
        "",
        "- For <FILL: typical task shape A>: dispatch to <FILL: peer specialist for shape A> via Lead's mailbox.",
        "- For <FILL: typical task shape B>: handle solo.",
        "- For <FILL: typical task shape C>: surface to operator (out of my scope).",
        "",
        "## When to escalate",
        "",
        "- If <FILL: what triggers escalation>, stop and write to outbox with `status: needs_human`.",
        "- If task requires capabilities outside my scoped MCPs, surface to Lead before retrying.",
        "- If multi-model verification produces contradictory results past my retry budget, escalate with full evidence trail.",
        "",
        "## What I do NOT do",
        "",
        "- WebFetch is fallback ONLY - use named MCPs first when task shape matches.",
        "- I do NOT cite tools/MCPs/features marked `verified: no` or `needs-research` in `shared/api-catalog.md`.",
        "- I do NOT run live exploits / make production changes / spend money without operator hard-gate approval.",
        "- <FILL: never-do items specific to this role>",
        "",
        "",
    ])
    return sections


def find_injection_point(content: str) -> int:
    """Locate the byte offset where v1.1 sections should be injected.

    Heuristic: scan past frontmatter and the first H1, then look for the FIRST
    H2 (`## `). If found, inject BEFORE that H2 (so the new sections come right
    after the role description paragraph). If no H2 exists at all, append to
    end of file.
    """
    lines = content.split("\n")
    in_frontmatter = False
    seen_h1 = False
    cursor = 0  # byte offset

    for i, line in enumerate(lines):
        # Track byte offset = sum of len(prev_line) + 1 (for \n) per line.
        if line.startswith("---"):
            # Toggle frontmatter only for the first two `---` lines.
            in_frontmatter = not in_frontmatter
            cursor += len(line) + 1
            continue
        if in_frontmatter:
            cursor += len(line) + 1
            continue
        if line.startswith("# ") and not seen_h1:
            seen_h1 = True
            cursor += len(line) + 1
            continue
        if seen_h1 and line.startswith("## "):
            # Inject BEFORE this trailing H2.
            return cursor
        cursor += len(line) + 1

    # No H2 found -> append at EOF.
    return len(content)


def upgrade_specialist(specialist_path: Path, catalog: dict, dry_run: bool = False) -> dict:
    """Read, inject if needed, atomic-write, return result dict."""
    content = specialist_path.read_text()
    if V11_SECTION_MARKER in content:
        return {
            "file": str(specialist_path),
            "status": "already-upgraded",
            "injected": [],
        }

    # departments/<lead>/specialists/<name>.md
    lead = specialist_path.parent.parent.name
    cli = LEAD_CLI.get(lead)
    if cli is None:
        return {
            "file": str(specialist_path),
            "status": "error",
            "error": f"unknown lead `{lead}` (not in LEAD_CLI map)",
        }
    specialist_name = specialist_path.stem

    sections = build_v11_sections(specialist_name, lead, cli, catalog)
    injection_point = find_injection_point(content)
    new_content = content[:injection_point] + sections + content[injection_point:]

    if dry_run:
        return {
            "file": str(specialist_path),
            "status": "dry-run",
            "lead": lead,
            "cli": cli,
            "injected": [
                "Tools available to me",
                "When to fan out",
                "When to escalate",
                "What I do NOT do",
            ],
            "preview": new_content,
            "injection_point": injection_point,
        }

    # Atomic write: tempfile in same dir + fsync + rename.
    tmp_dir = specialist_path.parent
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{specialist_path.stem}.",
        suffix=".md.tmp",
        dir=tmp_dir,
    )
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(new_content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.rename(tmp_path, specialist_path)
    except Exception:
        # Clean up tmp on failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return {
        "file": str(specialist_path),
        "status": "upgraded",
        "lead": lead,
        "cli": cli,
        "injected": [
            "Tools available to me",
            "When to fan out",
            "When to escalate",
            "What I do NOT do",
        ],
    }


def write_report(report: list) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    upgraded = sum(1 for r in report if r["status"] == "upgraded")
    skipped = sum(1 for r in report if r["status"] == "already-upgraded")
    errors = sum(1 for r in report if r["status"] == "error")

    lines = [
        "# upgrade-specialists.py report",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "## Summary",
        "",
        f"- Total files processed: {len(report)}",
        f"- Upgraded (v1.1 sections injected): {upgraded}",
        f"- Skipped (already had v1.1 schema): {skipped}",
        f"- Errors: {errors}",
        "",
        "## Per-file detail",
        "",
    ]
    for entry in report:
        line = f"- `{entry['file']}`: **{entry['status']}**"
        if entry["status"] == "upgraded":
            line += f" - lead={entry.get('lead')} cli={entry.get('cli')}"
            line += f" - sections injected: {', '.join(entry.get('injected', []))}"
        elif entry["status"] == "error":
            line += f" - error: {entry.get('error')}"
        lines.append(line)

    lines.append("")
    lines.append("## Placeholders left for human authors")
    lines.append("")
    lines.append("Each upgraded file contains `<FILL: ...>` markers. The Lead "
                 "author for each specialist must replace these with role-specific:")
    lines.append("- typical task shapes (A / B / C) and peer-specialist names for fan-out")
    lines.append("- conditions that trigger escalation to operator")
    lines.append("- never-do items specific to the role")
    lines.append("- additional API keys the specialist actually needs")
    lines.append("- additional skills beyond the curated default set")
    lines.append("")

    body = "\n".join(lines) + "\n"

    # Atomic write of the report itself.
    fd, tmp_path = tempfile.mkstemp(
        prefix=".upgrade-specialists-report.",
        suffix=".md.tmp",
        dir=REPORT_PATH.parent,
    )
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(body)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.rename(tmp_path, REPORT_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        metavar="SPECIALIST_PATH",
        help="Preview the injection for one specialist file without writing. "
             "Pass an absolute path to a specialists/*.md file.",
    )
    args = parser.parse_args(argv)

    catalog = parse_api_catalog(API_CATALOG)

    if args.dry_run:
        target = Path(args.dry_run).resolve()
        if not target.exists():
            print(f"ERROR: {target} does not exist", file=sys.stderr)
            return 2
        result = upgrade_specialist(target, catalog, dry_run=True)
        print(f"=== DRY RUN: {target} ===")
        print(f"status: {result['status']}")
        if result["status"] == "dry-run":
            print(f"lead: {result['lead']}")
            print(f"cli: {result['cli']}")
            print(f"injection_point: byte offset {result['injection_point']}")
            print(f"injected sections: {result['injected']}")
            print()
            print("--- WOULD WRITE (full content) ---")
            print(result["preview"])
        elif result["status"] == "already-upgraded":
            print("File already contains '## Tools available to me' - no changes would be made.")
        return 0

    report = []
    for lead in sorted(LEAD_CLI.keys()):
        spec_dir = SPECIALISTS_DIR / lead / "specialists"
        if not spec_dir.exists():
            print(f"WARN: {spec_dir} does not exist; skipping", file=sys.stderr)
            continue
        for spec_file in sorted(spec_dir.glob("*.md")):
            try:
                result = upgrade_specialist(spec_file, catalog)
                report.append(result)
                print(f"{result['status']}: {spec_file}")
            except Exception as e:
                report.append({
                    "file": str(spec_file),
                    "status": "error",
                    "error": str(e),
                })
                print(f"ERROR: {spec_file}: {e}", file=sys.stderr)

    write_report(report)

    upgraded = sum(1 for r in report if r["status"] == "upgraded")
    skipped = sum(1 for r in report if r["status"] == "already-upgraded")
    errors = sum(1 for r in report if r["status"] == "error")
    print()
    print(f"Report written to {REPORT_PATH}")
    print(f"Upgraded: {upgraded}, Skipped: {skipped}, Errors: {errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
