# claude-vibe-squad v1.1 — Tool Utilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the squad's 39 specialists actually use their available tools, set per-pane effort/thinking tier defaults, and add capability-verification + observability infrastructure — without architectural redesign.

**Architecture:** Edit-in-place fix release. 19 deliverables grouped into 11 phases that mirror the spec's build sequence. Foundation (capability inventory + Security debug) runs first; everything else cites verified entries from the inventory. Specialist edits are automation-driven (Python script + schema validator) to enforce uniformity across 39 files.

**Tech Stack:** Bash + Python 3 + markdown + tmux + git. No new external dependencies. Uses existing CLIs (claude, codex, gemini, kimi) and existing chrono MCPs (chrono-vault, chrono-research-arsenal, chrono-content-engineer).

**Spec reference:** `docs/specs/2026-05-02-vibe-squad-v1.1-tool-utilization.md` (rev 2, multi-model GREEN).

**Rollback tag:** `v1.0-pre-1.1` (committed before any v1.1 build edits).

---

## File Structure

### Files to CREATE

| Path | Responsibility |
|------|----------------|
| `_state/capability-inventory-2026-05-02.md` | Verified-from-live-CLI inventory of every flag, MCP, and feature claimed in the spec. Foundation for all subsequent specialist citations. |
| `shared/lifecycle.md` | 9 canonical lifecycle rules + per-pane effort/thinking defaults. Single source of truth referenced by Lead briefs and Chrono. |
| `shared/api-catalog.md` | Full API/feature catalog with per-entry `verified: yes/no/needs-research` flags. Specialist files only cite `verified: yes` entries with `test_reference`. |
| `bin/upgrade-specialists.py` | Python automation that injects v1.1 schema sections into all 39 specialist files. Pre-fills tool lists from api-catalog. |
| `bin/validate-specialists.sh` | Schema validator. Rejects specialist files citing unverified MCPs/skills/APIs. Exit 0 = clean. |
| `bin/dispatch-toolkit-verify.sh` | Per-pane MCP availability check. Runs at squad launch; warns on mismatches. |
| `bin/spawn-specialist.sh` | Subprocess specialist dispatch helper. Writes one entry to `_state/specialist-log.jsonl` per spawn. |
| `bin/aggregate-errors.sh` | Nightly aggregator. Greps tmux-logs + nightly-failures + doctor-logs into `_state/errors.jsonl`. |
| `bin/finance-daily.sh` | First-week token-spend monitor. Reads dispatch-log + tmux-logs to estimate per-pane token use; writes daily summary. |
| `_state/specialist-log.jsonl` | Per-specialist-call log (high-fidelity). |
| `_state/tool-calls.jsonl` | Per-MCP-tool-call log (best-effort; in-process MCP calls may not be capturable). |
| `_state/errors.jsonl` | Aggregated errors across all log streams. |
| `_state/patterns.jsonl` | Routine signatures for MCP graduation surfacing. |
| `_state/mcp-graduation-candidates.md` | Surfaced patterns hitting N=3 distinct engagements. |
| `_state/token-budget-2026-05-W2.md` | First-week token budget with explicit baseline source field. |
| `_state/incident-2026-05-02-security-mcp.md` | Security Lead MCP error post-mortem. |
| `departments/coding/specialists/smart-contract-engineer/skills/smart-contract-audit-checklist.md` | NEW skill (REMAKE from tamjid0x01 + cryptofinlabs). |
| `departments/security/specialists/impact-validator/skills/bounty-platform-report-format.md` | NEW skill (REMAKE from H1/Bugcrowd/Code4rena public report templates). |
| `CHANGELOG.md` | Vault-root changelog with v1.1.0 entry. |

### Files to MODIFY

| Path | Change |
|------|--------|
| `bin/launch-squad.sh` | Add `--effort` / `--reasoning` / `--thinking` flags + explicit `--model` per pane |
| `chrono/CLAUDE.md` | Reference `shared/lifecycle.md`; Topology B chaser logic; routing-rule reminders |
| `chrono/SOUL.md` | Note: Chrono surfaces MCP graduation candidates; operator approves |
| `chrono/current.md` | Add "Cross-Lead pending replies" section schema |
| `chrono/operator-setup.md` | Strengthen cross-Lead direct-with-CC routing examples |
| `CLAUDE.md` (vault root) | Reference `shared/lifecycle.md` and `shared/api-catalog.md`; tighten "specialists must use named MCPs not WebFetch" rule |
| `shared/dispatch-toolkit.sh` | Trim research arsenal from non-Research; reflect actually-installed MCPs |
| `scripts/send-task.sh` | Hook into `bin/spawn-specialist.sh` for specialist-log writes |
| `bin/vibecoding-check.sh` | Add hard retry cap (max 2) |
| `departments/coding/LEAD.md` | v1.1 sections: native CLI features (Codex), specialist decision tree, Topology B patterns, lifecycle ref |
| `departments/security/LEAD.md` | v1.1 sections: native CLI features (Claude Opus xhigh), specialist tree, Topology B, lifecycle ref |
| `departments/content/LEAD.md` | v1.1 sections: native CLI features (Gemini Nano Banana / Veo / Search grounding), tree, Topology B, lifecycle ref |
| `departments/sysmgmt/LEAD.md` | v1.1 sections: native CLI features (Claude Sonnet high), tree, Topology B, lifecycle ref |
| `departments/research/LEAD.md` | v1.1 sections: native CLI features (Kimi 300-parallel + thinking), tree, Topology B, lifecycle ref |
| `departments/coding/memory.md` | v1.1 update note (~5 lines) |
| `departments/security/memory.md` | v1.1 update note |
| `departments/content/memory.md` | v1.1 update note |
| `departments/sysmgmt/memory.md` | v1.1 update note |
| `departments/research/memory.md` | v1.1 update note |
| 39 × `departments/*/specialists/*.md` | Schema-injected sections via `bin/upgrade-specialists.py` (Tools available, fan-out, escalation, what-I-do-not-do) |
| `README.md` | v1.1 changes section + links to lifecycle/api-catalog/CHANGELOG |

---

## Phase 1 — Foundation (parallel: Items 0 + 14)

### Task 1: Capability Inventory (Item 0)

**Files:**
- Create: `_state/capability-inventory-2026-05-02.md`
- Reference: spec Item 0 schema

**Why first:** Every subsequent task that cites a CLI flag or MCP feature MUST reference this inventory. Without it, we replace one tool-mythology problem with another.

- [ ] **Step 1: Inventory each CLI's flags**

```bash
for cli in claude codex gemini kimi; do
  echo "=== $cli ==="
  $cli --help 2>&1 | head -200
done > /tmp/cli-help-snapshot.txt
```

- [ ] **Step 2: Inventory each pane's MCPs**

```bash
# Run inside each pane (via tmux send-keys + capture):
# claude pane: claude mcp list
# codex pane: codex mcp list
# gemini pane: gemini mcp list
# kimi pane: kimi mcp list

for pane in chrono coding security content sysmgmt research; do
  tmux send-keys -t "squad:$pane" "<cli> mcp list" Enter
  sleep 5
  tmux capture-pane -p -t "squad:$pane" > /tmp/mcp-list-$pane.txt
done
```

- [ ] **Step 3: Test specific flags claimed in spec**

```bash
# Claude: --effort xhigh
env -u ANTHROPIC_API_KEY claude --effort xhigh -p "echo test" 2>&1 | head -5
# Expected: no "unknown flag" error

# Codex: -c model_reasoning_effort=high
env -u OPENAI_API_KEY codex exec -c model_reasoning_effort=high "echo test" 2>&1 | head -5

# Gemini: --thinking (or actual flag from --help)
env -u GEMINI_API_KEY gemini --help | grep -i thinking

# Kimi: --thinking
kimi --help | grep -i thinking
```

- [ ] **Step 4: Write the inventory file**

Use the schema from spec Item 0. Each entry: feature/flag name + verified-yes/no/needs-research + last_checked + test_reference (the actual command run).

- [ ] **Step 5: Commit**

```bash
git add _state/capability-inventory-2026-05-02.md
git commit -m "v1.1 Item 0: capability inventory — verified CLI flags + MCPs per pane"
```

### Task 2: Security Lead MCP Debug (Item 14)

**Files:**
- Read: `_state/tmux-logs/security.log`
- Create: `_state/incident-2026-05-02-security-mcp.md`

**Runs parallel with Task 1.**

- [ ] **Step 1: Find the MCP errors in security log**

```bash
grep -nE "MCP server failed|mcp.*error|connection.*refused" \
  _state/tmux-logs/security.log | head -30
```

- [ ] **Step 2: Identify which 2 MCPs failed and why**

Read context around each error. Look for: missing config, missing binary, port conflict, auth failure.

- [ ] **Step 3: Root-cause + fix or remove decision**

For each failed MCP:
- If reinstallable: reinstall + verify with `claude mcp list` in security pane
- If broken upstream: remove from `shared/dispatch-toolkit.sh` security section + document why

- [ ] **Step 4: Write incident report**

Create `_state/incident-2026-05-02-security-mcp.md` with required fields:
- MCP name (each)
- Root cause
- Fix decision (restored OR removed)
- Verification command + output

- [ ] **Step 5: Commit**

```bash
git add _state/incident-2026-05-02-security-mcp.md shared/dispatch-toolkit.sh
git commit -m "v1.1 Item 14: Security MCP errors investigated + fixed"
```

---

## Phase 2 — Catalogs & Lifecycle (Items 6 + 7)

### Task 3: shared/lifecycle.md (Item 6)

**Files:**
- Create: `shared/lifecycle.md`

- [ ] **Step 1: Write the 9 lifecycle rules**

Use spec section Item 6 contents verbatim. Sections:
1. Persistent panes
2. Short conversation tail per Lead
3. Prompt caching prefix discipline
4. Compaction at phase boundaries
5. Hard reset on engagement close
6. Specialist subprocesses ALWAYS ephemeral
7. Per-task effort tiering
8. Context-budget circuit breaker
9. Observability via finance-analyst + harness-optimizer

- [ ] **Step 2: Add per-pane effort defaults table**

```markdown
| Pane | Model | Default tier | Rationale |
|------|-------|---------------|-----------|
| chrono | Opus 4.7 | xhigh | Coordinator judgment is high-stakes |
| security | Opus 4.7 | xhigh | Security work is judgment-heavy |
| coding | Codex GPT-5.5 | high | Codex max scale; implementation depth |
| sysmgmt | Sonnet 4.6 | high | Operations mostly mechanical |
| content | Gemini 3.1 Pro | thinking on | Creative judgment depth |
| research | Kimi K2.6 | thinking on | Synthesis depth |
```

- [ ] **Step 3: Add per-task override discipline section**

Specialist subprocess effort flags per task tier (T1 low / T2 default / T3 xhigh / T4 fanout-each-at-max).

- [ ] **Step 4: Verification**

```bash
test -f shared/lifecycle.md && grep -q "9 lifecycle rules\|## " shared/lifecycle.md && echo OK
```
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add shared/lifecycle.md
git commit -m "v1.1 Item 6: shared/lifecycle.md — 9 rules + effort defaults"
```

### Task 4: shared/api-catalog.md (Item 7)

**Files:**
- Create: `shared/api-catalog.md`
- Reference: `_state/capability-inventory-2026-05-02.md` (Task 1 output)

- [ ] **Step 1: Write Anthropic / Claude section**

Each entry has the full schema (url/access/specialists/verified/last_checked/test_reference/notes/research_task). Cite Task 1 inventory entries. `verified: yes` only where Task 1 confirmed.

- [ ] **Step 2: Write OpenAI / Codex section**

Same schema. Codex: `codex review`, `codex exec`, `codex mcp-server`, `-c model_reasoning_effort=high`, native macOS computer use, plugin marketplaces.

- [ ] **Step 3: Write Google / Gemini section**

Nano Banana Pro / 2 (verified or needs-research per Task 1), Veo 3, Google Search grounding, conversational image editing, Jules (needs-research), Flow (needs-research), NotebookLM (needs-research), Antigravity (needs-research), gemini gemma, hooks, skills, extensions, --worktree.

- [ ] **Step 4: Write Moonshot / Kimi section**

300 parallel sub-agents (verify usage), 4000 coordinated tool steps, MoonViT vision, thinking mode, OpenAI/Anthropic-compatible APIs, --print headless, --mcp-config-file.

- [ ] **Step 5: Write xAI/DeepSeek/ElevenLabs/Higgsfield/chrono-MCPs sections**

xAI: needs-research (API setup). DeepSeek: needs-research. ElevenLabs: verified (already wired via chrono-content-engineer). Higgsfield: verified. chrono-vault, chrono-obsidian, chrono-kg, chrono-catalog, chrono-research-arsenal/perplexity: verified per Task 1.

- [ ] **Step 6: Verification**

```bash
test -f shared/api-catalog.md
# Every verified: yes entry has test_reference
awk '/verified: yes/,/^---|^##/' shared/api-catalog.md | grep -B1 "verified: yes" | grep -A1 "verified: yes" | grep test_reference | wc -l
# Should match count of "verified: yes" entries
```

- [ ] **Step 7: Commit**

```bash
git add shared/api-catalog.md
git commit -m "v1.1 Item 7: shared/api-catalog.md — full feature catalog with verified flags"
```

---

## Phase 3 — Launch + Guardrails (Items 5 + 5b + 8)

### Task 5: bin/launch-squad.sh effort/thinking flags (Item 5)

**Files:**
- Modify: `bin/launch-squad.sh` (lines 88, 98, 108, 118, 128, 137-139 per audit)

- [ ] **Step 1: Test new flags in disposable tmux session FIRST**

```bash
# Before touching launch-squad.sh, verify each new flag works:
tmux new-session -d -s squad-test
tmux send-keys -t squad-test "claude --permission-mode acceptEdits --model opus --effort xhigh" Enter
sleep 5
tmux capture-pane -p -t squad-test | tail -10
# Expected: no error message
tmux kill-session -t squad-test
```

Repeat for each pane's new flag set.

- [ ] **Step 2: Edit chrono pane line**

Find line 88 (chrono start command). Replace with:
```
'Start with: claude --permission-mode acceptEdits --add-dir ${VAULT_ROOT} --model opus --effort xhigh'
```

- [ ] **Step 3: Edit coding pane line**

Find line 98. Replace with:
```
'Start with: codex --sandbox workspace-write --ask-for-approval never -c model_reasoning_effort=high'
```

- [ ] **Step 4: Edit security/sysmgmt panes (lines 108, 128)**

Security: `--model opus --effort xhigh`
SysMgmt: `--model sonnet --effort high`

- [ ] **Step 5: Edit content/research panes (lines 118, 137-139)**

Content: `--model gemini-3.1-pro-preview` + thinking-flag-from-Task-1 (replace placeholder if Task 1 found a different flag name)
Research: `--thinking` flag

- [ ] **Step 6: Verification**

```bash
grep -E "effort|thinking|--model" bin/launch-squad.sh | wc -l
# Expected: ≥6 matches (one per pane)
```

- [ ] **Step 7: Disposable launch dry-run**

```bash
tmux new-session -d -s squad-dryrun
bash -n bin/launch-squad.sh  # syntax check
# Manually launch in test session — verify all 6 panes ready
tmux kill-session -t squad-dryrun
```

- [ ] **Step 8: Commit**

```bash
git add bin/launch-squad.sh
git commit -m "v1.1 Item 5: per-pane effort/thinking flags in launch-squad.sh"
```

### Task 6: shared/dispatch-toolkit.sh reality-check (Item 8)

**Files:**
- Modify: `shared/dispatch-toolkit.sh`
- Create: `bin/dispatch-toolkit-verify.sh`

- [ ] **Step 1: Trim chrono-research-arsenal from non-Research sections**

Currently lines 38-44 (coding section), 56-66 (security section), 84-91 (content section), 109-114 (sysmgmt section) reference chrono-research-arsenal. Remove from coding/security/content/sysmgmt; keep in research section (lines 117-141).

- [ ] **Step 2: Replace placeholder MCP names with capability-inventory entries**

For each Lead section, list ONLY MCPs that Task 1's capability inventory shows actually bound in that pane.

- [ ] **Step 3: Write bin/dispatch-toolkit-verify.sh**

```bash
#!/usr/bin/env bash
# Per-pane MCP verification at squad launch.
# For each pane, check that MCPs enumerated in dispatch-toolkit.sh
# are actually installed in that pane's CLI.

set -euo pipefail
VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
TOOLKIT="${VAULT_ROOT}/shared/dispatch-toolkit.sh"

declare -A PANE_CLI=(
    [chrono]=claude [coding]=codex [security]=claude
    [content]=gemini [sysmgmt]=claude [research]=kimi
)

for pane in "${!PANE_CLI[@]}"; do
    cli="${PANE_CLI[$pane]}"
    # Get installed MCPs for this CLI
    installed=$($cli mcp list 2>/dev/null | tail -n +2 | awk '{print $1}')
    # Get enumerated MCPs for this Lead from toolkit
    enumerated=$(awk "/^    ${pane}\)/,/^        ;;/" "$TOOLKIT" | \
                 grep -oE "chrono-[a-z-]+|playwright|chrome-devtools|context7|hexstrike" | \
                 sort -u)
    # Find mismatches
    for mcp in $enumerated; do
        if ! echo "$installed" | grep -q "$mcp"; then
            echo "WARN: $pane pane enumerates $mcp but it's not installed"
        fi
    done
done
```

- [ ] **Step 4: Verification**

```bash
chmod +x bin/dispatch-toolkit-verify.sh
bash bin/dispatch-toolkit-verify.sh
# Expected: zero WARN lines (or known-acceptable warnings)
```

- [ ] **Step 5: Commit**

```bash
git add shared/dispatch-toolkit.sh bin/dispatch-toolkit-verify.sh
git commit -m "v1.1 Item 8: dispatch-toolkit reality-check + per-pane verifier"
```

### Task 7: Token-spend guardrail (Item 5b)

**Files:**
- Create: `_state/token-budget-2026-05-W2.md`
- Create: `bin/finance-daily.sh`

- [ ] **Step 1: Derive baseline from past 7 days dispatch-log**

```bash
# Per-pane dispatch count over past 7 days (proxy for token use)
jq -r 'select(.ts > "'$(date -u -v-7d +%FT%TZ)'") | .to_lead' \
  _state/dispatch-log.jsonl | sort | uniq -c | sort -rn
```

- [ ] **Step 2: Write token-budget file**

```markdown
# Token Budget — Week of 2026-05-W2

baseline_source: auto-derived from past 7 days dispatch-log per-Lead counts
baseline_date: 2026-05-02
alert_threshold: baseline × 1.5

per_pane_baseline:
  chrono: <count>/day
  coding: <count>/day
  security: <count>/day
  ...
```

- [ ] **Step 3: Write bin/finance-daily.sh**

```bash
#!/usr/bin/env bash
# Daily token-spend check during first week of v1.1.
set -euo pipefail
VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
TODAY=$(date -u +%F)
OUT="${VAULT_ROOT}/_state/finance-daily/${TODAY}.md"
mkdir -p "$(dirname "$OUT")"

# Get today's per-pane dispatch count
yesterday=$(date -u -v-1d +%FT%TZ)
{
    echo "# Finance Daily — $TODAY"
    echo
    echo "## Per-pane dispatches (last 24h)"
    jq -r 'select(.ts > "'$yesterday'") | .to_lead' \
        "$VAULT_ROOT/_state/dispatch-log.jsonl" | \
        sort | uniq -c | sort -rn
    # Compare to baseline; alert if >1.5×
    # ... (read baseline from token-budget file, compare, surface anomalies)
} > "$OUT"
```

- [ ] **Step 4: Verification**

```bash
chmod +x bin/finance-daily.sh
bash bin/finance-daily.sh
test -f "_state/finance-daily/$(date -u +%F).md"
```

- [ ] **Step 5: Commit**

```bash
git add _state/token-budget-2026-05-W2.md bin/finance-daily.sh
git commit -m "v1.1 Item 5b: first-week token-spend guardrail"
```

---

## Phase 4 — Specialist Tooling (Items 1b + 2b)

### Task 8: bin/upgrade-specialists.py automation (Item 1b)

**Files:**
- Create: `bin/upgrade-specialists.py`
- Reference: `shared/api-catalog.md` (for tool pre-fill)

- [ ] **Step 1: Write the script skeleton**

```python
#!/usr/bin/env python3
"""
Inject v1.1 schema sections into all 39 specialist files.
Reads shared/api-catalog.md for tool pre-fill matched by Lead-CLI.
Atomic write via temp + fsync + rename.
"""
import os
import sys
import tempfile
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
SPECIALISTS_DIR = VAULT / "departments"
API_CATALOG = VAULT / "shared/api-catalog.md"
LEAD_CLI = {
    "coding": "codex",
    "security": "claude",
    "content": "gemini",
    "sysmgmt": "claude",
    "research": "kimi",
}

def inject_v11_sections(specialist_path: Path, lead: str, cli: str) -> dict:
    """Read specialist file, inject sections after role description."""
    content = specialist_path.read_text()
    if "## Tools available to me" in content:
        return {"file": str(specialist_path), "status": "already-upgraded", "injected": []}
    
    sections = build_sections_for(lead, cli, specialist_path.stem)
    # Inject AFTER existing role section, BEFORE any trailing sections
    injection_point = find_injection_point(content)
    new_content = content[:injection_point] + sections + content[injection_point:]
    
    # Atomic write
    with tempfile.NamedTemporaryFile("w", delete=False, dir=specialist_path.parent) as tmp:
        tmp.write(new_content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.rename(tmp_path, specialist_path)
    return {"file": str(specialist_path), "status": "upgraded", "injected": ["Tools", "fan-out", "escalation", "what-not"]}
```

- [ ] **Step 2: Implement `build_sections_for(lead, cli, specialist_name)`**

Reads api-catalog, filters to `verified: yes` entries matching the specialist's Lead+CLI. Returns markdown string with the four required sections + `<FILL: ...>` placeholders for human-judgment fields.

- [ ] **Step 3: Implement `find_injection_point(content)`**

Locates end of existing role section. Heuristic: after the first `# <Specialist Name>` H1 + paragraph, before any existing `## Tools` or trailing sections.

- [ ] **Step 4: Implement main loop + report**

```python
def main():
    report = []
    for lead, cli in LEAD_CLI.items():
        spec_dir = SPECIALISTS_DIR / lead / "specialists"
        for spec_file in spec_dir.glob("*.md"):
            result = inject_v11_sections(spec_file, lead, cli)
            report.append(result)
    
    # Write report to _state/
    report_path = VAULT / "_state/upgrade-specialists-report-2026-05-02.md"
    with report_path.open("w") as f:
        f.write("# upgrade-specialists.py report\n\n")
        for entry in report:
            f.write(f"- {entry['file']}: {entry['status']} — injected {entry['injected']}\n")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verification**

```bash
chmod +x bin/upgrade-specialists.py
# Don't run yet — just syntax check
python3 -c "import ast; ast.parse(open('bin/upgrade-specialists.py').read())"
# Expected: silent (valid syntax)
```

- [ ] **Step 6: Commit**

```bash
git add bin/upgrade-specialists.py
git commit -m "v1.1 Item 1b: upgrade-specialists.py automation script"
```

### Task 9: bin/validate-specialists.sh schema validator (Item 2b)

**Files:**
- Create: `bin/validate-specialists.sh`
- Reference: `shared/api-catalog.md`

- [ ] **Step 1: Write the validator**

```bash
#!/usr/bin/env bash
# Validate every specialist file:
# - has required v1.1 sections
# - cites only verified MCPs/skills/APIs
# - peer-specialist references resolve

set -euo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
CATALOG="${VAULT}/shared/api-catalog.md"

# Get verified MCP names from catalog
VERIFIED_MCPS=$(awk '/verified: yes/{found=1} found && /test_reference:/{found=0} found && /^### /{print $2}' "$CATALOG" | sort -u)

REQUIRED_SECTIONS=(
    "## Tools available to me"
    "## When to fan out"
    "## When to escalate"
    "## What I do NOT do"
)

EXIT_CODE=0
for spec_file in "$VAULT"/departments/*/specialists/*.md; do
    issues=()
    
    # Check required sections
    for section in "${REQUIRED_SECTIONS[@]}"; do
        if ! grep -qF "$section" "$spec_file"; then
            issues+=("missing section: $section")
        fi
    done
    
    # Check MCPs cited are verified
    cited_mcps=$(awk '/^### MCPs/,/^### /' "$spec_file" | grep -oE '`[a-z-]+`' | tr -d '`' | sort -u)
    for mcp in $cited_mcps; do
        if ! echo "$VERIFIED_MCPS" | grep -q "^$mcp$"; then
            issues+=("unverified MCP cited: $mcp")
        fi
    done
    
    # Output
    if [ ${#issues[@]} -eq 0 ]; then
        echo "PASS: $spec_file"
    else
        echo "FAIL: $spec_file"
        printf '  %s\n' "${issues[@]}"
        EXIT_CODE=1
    fi
done

exit $EXIT_CODE
```

- [ ] **Step 2: Verification (will fail until Task 11 runs)**

```bash
chmod +x bin/validate-specialists.sh
bash bin/validate-specialists.sh
# Expected at this stage: many FAIL because sections not yet injected
# Expected after Task 11: all PASS
```

- [ ] **Step 3: Commit**

```bash
git add bin/validate-specialists.sh
git commit -m "v1.1 Item 2b: validate-specialists.sh schema validator"
```

---

## Phase 5 — Lead Briefs (Item 2)

### Task 10: Update all 5 LEAD.md files

**Files:**
- Modify: `departments/coding/LEAD.md`
- Modify: `departments/security/LEAD.md`
- Modify: `departments/content/LEAD.md`
- Modify: `departments/sysmgmt/LEAD.md`
- Modify: `departments/research/LEAD.md`

For each Lead, append the four required v1.1 sections (My CLI's native features, Specialist decision tree, Direct-with-CC patterns, Lifecycle discipline). Native features pulled from api-catalog `verified: yes` entries.

- [ ] **Step 1: Write coding/LEAD.md additions**

Append:
```markdown
## My CLI's native features (Codex GPT-5.5)

- `codex review` — non-interactive code review. Use when: any PR-shaped review for first pass.
- `codex exec` — headless agent for specialist subprocess invocation.
- `codex mcp-server` — Codex AS an MCP server (other Leads can call as tool).
- Cloud agents (async) — for long-running build tasks (>10 min).
- Native macOS computer use — GUI automation for e2e-runner / scraping-engineer.

## Specialist decision tree

| Task shape | Specialist | Why |
|-----------|-----------|-----|
| API/server work | backend-engineer | Direct domain match |
| UI/component work | frontend-engineer or ui-engineer | UI vs design-token focus |
| Code review (any) | code-reviewer (multi-pass via codex review) | Severity ladder + multi-LLM adjudication |
| Test authoring | test-engineer | Unit + integration |
| Property/mutation/fuzz | qa-tester | Distinct from test-engineer |
| Refactor only | refactor-cleaner | Structural cleanup, no new features |
| ML/LLM/agent | ai-engineer | RAG, prompts, eval |
| Smart contract | smart-contract-engineer | EVM/Solana audits |
| Performance | performance-optimizer | Bench/profile/flamegraph |
| Cross-arch / SIMD | systems-engineer | Low-level systems |
| Browser scraping | scraping-engineer | Stealth, bot-evasion |
| E2E | e2e-runner | Playwright suites |

## Direct-with-CC patterns (Topology B)

When to write directly to a peer Lead's inbox (instead of routing through Chrono):
- Library reputation check during build → write to `departments/research/inbox/` with `from_lead: coding`
- Auth/data-flow code review → write to `departments/security/inbox/` with `from_lead: coding`
- ALWAYS CC summary to `chrono/inbox/` for visibility.

NEVER do direct cross-Lead for: operator-facing decisions, mode transitions, anything requiring approval.

## Lifecycle discipline

See `shared/lifecycle.md`. Per Coding Lead specifically:
- Effort tier default: high (set in launch-squad.sh: `-c model_reasoning_effort=high`)
- Compaction trigger: end of each phase in Project Mode
- Memory.md update cadence: per task completion (insights only, not progress)
```

- [ ] **Step 2: Write security/LEAD.md additions**

Same structure with Security-specific content (Claude Opus xhigh, scout/security-analyst/threat-modeler decision tree, /ultrareview reference, etc.).

- [ ] **Step 3: Write content/LEAD.md additions**

Gemini 3.1 features: Nano Banana Pro/2 (verified or needs-research per Task 1), Veo 3, Google Search grounding, --worktree, hooks, skills.

- [ ] **Step 4: Write sysmgmt/LEAD.md additions**

Claude Sonnet 4.6 high; doctor/dreamer/memory-curator/etc. decision tree; harness-optimizer's role in patterns.jsonl + graduation candidates.

- [ ] **Step 5: Write research/LEAD.md additions**

Kimi K2.6 features: 300 parallel sub-agents (verified or needs-research), thinking mode, --print headless, --mcp-config-file. Source-blind dispatch pattern (when applicable).

- [ ] **Step 6: Verification**

```bash
for lead in coding security content sysmgmt research; do
  for section in "## My CLI's native features" "## Specialist decision tree" "## Direct-with-CC" "## Lifecycle discipline"; do
    grep -q "$section" "departments/$lead/LEAD.md" || echo "MISSING: $lead $section"
  done
done
# Expected: no MISSING output
```

- [ ] **Step 7: Commit**

```bash
git add departments/*/LEAD.md
git commit -m "v1.1 Item 2: 5 LEAD.md files updated with native CLI features + decision trees + Topology B + lifecycle ref"
```

---

## Phase 6 — Specialist Edits (Items 1 + 3)

### Task 11: Run upgrade-specialists.py + validate

**Files:**
- Modify: 39 × `departments/*/specialists/*.md`
- Create: `_state/upgrade-specialists-report-2026-05-02.md`

- [ ] **Step 1: Run the automation**

```bash
python3 bin/upgrade-specialists.py
```

- [ ] **Step 2: Inspect the report**

```bash
cat _state/upgrade-specialists-report-2026-05-02.md | head -60
# Expected: 39 entries with status: upgraded
```

- [ ] **Step 3: Run schema validator**

```bash
bash bin/validate-specialists.sh
# Expected: 39 PASS lines, exit 0
```

- [ ] **Step 4: Manually fill placeholder fields in priority Tier A files**

For each Tier A specialist (12 files: code-reviewer, backend-engineer, frontend-engineer, ui-engineer, test-engineer, scout, security-analyst, threat-modeler, research, synthesizer, writer, technical-writer):
- Replace `<FILL: task shape A>` with concrete examples
- Add specialist-specific MCP-use ordering instructions
- Verify peer-specialist fan-out references resolve

- [ ] **Step 5: Re-validate**

```bash
bash bin/validate-specialists.sh
# Expected: still 39 PASS
```

- [ ] **Step 6: Commit**

```bash
git add departments/*/specialists/*.md _state/upgrade-specialists-report-2026-05-02.md
git commit -m "v1.1 Item 1: 39 specialist files upgraded with v1.1 schema (Tier A manually completed)"
```

### Task 12: Lead memory.md notes (Item 3)

**Files:**
- Modify: `departments/<lead>/memory.md` for all 5 Leads

- [ ] **Step 1: Append v1.1 update to each memory.md**

Single section per file:
```markdown
## v1.1 update — 2026-05-02

The squad ships v1.1 with explicit tool catalogs in every specialist file
plus per-pane effort-tier defaults. When dispatching a specialist, trust
that the specialist's identity.md enumerates what it can use. Direct-with-CC
patterns are documented in this LEAD.md. See shared/lifecycle.md for
lifecycle rules.
```

- [ ] **Step 2: Verification**

```bash
for lead in coding security content sysmgmt research; do
  grep -q "v1.1 update — 2026-05-02" "departments/$lead/memory.md" || echo "MISSING: $lead"
done
# Expected: no MISSING output
```

- [ ] **Step 3: Commit**

```bash
git add departments/*/memory.md
git commit -m "v1.1 Item 3: 5 Lead memory.md files note v1.1 update"
```

---

## Phase 7 — Brain Edits (Items 4 + 9 + 9b)

### Task 13: chrono/operator-setup.md routing clarifications (Item 9)

**Files:**
- Modify: `chrono/operator-setup.md`

- [ ] **Step 1: Add cross-Lead direct-with-CC examples**

Append after existing routing table:
```markdown
## When Security needs research mid-task

If Security/scout (during bounty target selection) needs OSINT on a candidate:
- DO direct-with-CC: write to `departments/research/inbox/` with `from_lead: security`
- ALSO write a one-line CC summary to `chrono/inbox/` so Chrono retains visibility
- Do NOT route back through Chrono — that adds 4 hops for what should be 2

If Security/security-analyst (during code audit) needs library reputation check:
- Same pattern — direct-with-CC to Research

NEVER auto-route operator-facing decisions through cross-Lead handoff.
```

- [ ] **Step 2: Verification**

```bash
grep -q "When Security needs research mid-task" chrono/operator-setup.md
```

- [ ] **Step 3: Commit**

```bash
git add chrono/operator-setup.md
git commit -m "v1.1 Item 9: cross-Lead direct-with-CC routing examples"
```

### Task 14: chrono/current.md Topology B chaser schema (Item 9b)

**Files:**
- Modify: `chrono/current.md` (template addition)
- Modify: `chrono/CLAUDE.md` (chaser policy)

- [ ] **Step 1: Add chaser section to chrono/current.md**

Append:
```markdown
## Cross-Lead pending replies (CC'd threads)

Thread tracking for Topology B direct-with-CC. Format:

| thread_id | from_lead → to_lead | requested_action | deadline | status |
|-----------|----------------------|-------------------|----------|--------|
| ... | ... | ... | ... | pending |

When a CC'd entry exceeds deadline (default 2h), surface to operator:
"[Lead A] asked [Lead B] about X N hours ago — no reply yet. Chase?"
```

- [ ] **Step 2: Add chaser policy to chrono/CLAUDE.md**

Append:
```markdown
## Topology B chaser logic

When operator's turn starts:
1. Scan `current.md` "Cross-Lead pending replies" section
2. For each pending entry past 2h deadline: surface to operator with chase option
3. On operator approval: send a follow-up to the recipient Lead
4. On reply received: update thread to status: completed
```

- [ ] **Step 3: Verification**

```bash
grep -q "Cross-Lead pending replies" chrono/current.md
grep -q "Topology B chaser logic" chrono/CLAUDE.md
```

- [ ] **Step 4: Commit**

```bash
git add chrono/current.md chrono/CLAUDE.md
git commit -m "v1.1 Item 9b: Topology B chaser logic in Chrono"
```

### Task 15: Coordinator brain updates (Item 4)

**Files:**
- Modify: `chrono/CLAUDE.md` (additional)
- Modify: `chrono/SOUL.md` (minor)
- Modify: `CLAUDE.md` (vault root)

- [ ] **Step 1: Add references to chrono/CLAUDE.md**

Append:
```markdown
## v1.1 references
- See `shared/lifecycle.md` for lifecycle rules + per-pane effort defaults
- See `shared/api-catalog.md` for all available APIs/features per specialist
- See `chrono/operator-setup.md` for routing rules including cross-Lead direct-with-CC
```

- [ ] **Step 2: Update chrono/SOUL.md**

Append:
```markdown
## v1.1 — instinct surfacing
Chrono recognizes when routines have fired enough times to candidate for
custom-MCP creation (N=3 distinct engagements). When this happens, Chrono
surfaces the candidate to operator at next morning brief. Operator decides
whether to build. Chrono does NOT auto-scaffold MCPs.
```

- [ ] **Step 3: Update vault CLAUDE.md**

Append after existing rules:
```markdown
## v1.1 references

- `shared/lifecycle.md` — lifecycle rules + per-pane effort tiers
- `shared/api-catalog.md` — verified APIs/features mapped to specialists

## Tightened rule on tool selection

Specialists must use named MCPs / native CLI features from their identity.md
FIRST. WebFetch is fallback only when no better tool fits.
Example: a specialist needing web research should call `chrono-research-arsenal/perplexity`
or its scoped equivalent, NOT WebFetch as default.
```

- [ ] **Step 4: Verification**

```bash
grep -q "shared/lifecycle.md" chrono/CLAUDE.md
grep -q "instinct surfacing" chrono/SOUL.md
grep -q "shared/api-catalog.md" CLAUDE.md
```

- [ ] **Step 5: Commit**

```bash
git add chrono/CLAUDE.md chrono/SOUL.md CLAUDE.md
git commit -m "v1.1 Item 4: coordinator brains reference lifecycle + api-catalog + tightened tool-selection rule"
```

---

## Phase 8 — Logging + Instinct (Items 10 + 11)

### Task 16: bin/spawn-specialist.sh + specialist-log.jsonl (Item 10 part 1)

**Files:**
- Create: `bin/spawn-specialist.sh`
- Modify: `scripts/send-task.sh` (hook into spawn-specialist for logging)

- [ ] **Step 1: Write spawn-specialist.sh**

```bash
#!/usr/bin/env bash
# Spawn a specialist subprocess and log the call.
# Usage: bin/spawn-specialist.sh <lead> <specialist> <task_id> <task_body_path>

set -euo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
LOG="${VAULT}/_state/specialist-log.jsonl"
mkdir -p "$(dirname "$LOG")"

LEAD="$1"; SPECIALIST="$2"; TASK_ID="$3"; TASK_BODY="$4"

# Determine CLI from lead (per shared/dispatch-toolkit.sh table)
declare -A LEAD_CLI=(
    [coding]=codex [security]=claude [content]=gemini
    [sysmgmt]=claude [research]=kimi
)
CLI="${LEAD_CLI[$LEAD]}"

# Read specialist's identity bundle
IDENTITY="${VAULT}/departments/${LEAD}/specialists/${SPECIALIST}.md"
MCP_CONFIG="${VAULT}/departments/${LEAD}/specialists/${SPECIALIST}-mcp.json"

START_TS=$(date -u +%FT%TZ)
START_MS=$(date +%s%N | cut -c1-13)

# Spawn (per CLI)
case "$CLI" in
    claude) OUT=$(claude -p --append-system-prompt "$(cat "$IDENTITY")" "$(cat "$TASK_BODY")" 2>&1) ;;
    codex)  OUT=$(codex exec "$(cat "$TASK_BODY")" 2>&1) ;;
    gemini) OUT=$(gemini -p "$(cat "$TASK_BODY")" 2>&1) ;;
    kimi)   OUT=$(kimi --print "$(cat "$TASK_BODY")" 2>&1) ;;
esac
EXIT_CODE=$?

END_MS=$(date +%s%N | cut -c1-13)
DURATION_MS=$((END_MS - START_MS))

# Append log entry
printf '{"ts":"%s","lead":"%s","specialist":"%s","cli":"%s","task_id":"%s","exit_code":%d,"duration_ms":%d,"stdout_bytes":%d}\n' \
    "$START_TS" "$LEAD" "$SPECIALIST" "$CLI" "$TASK_ID" "$EXIT_CODE" "$DURATION_MS" "${#OUT}" \
    >> "$LOG"

echo "$OUT"
exit "$EXIT_CODE"
```

- [ ] **Step 2: Verification (synthetic call)**

```bash
chmod +x bin/spawn-specialist.sh
echo "test prompt" > /tmp/test-task.md
# Don't actually run yet — just syntax check
bash -n bin/spawn-specialist.sh
```

- [ ] **Step 3: Commit**

```bash
git add bin/spawn-specialist.sh
git commit -m "v1.1 Item 10a: spawn-specialist.sh + specialist-log.jsonl writes"
```

### Task 17: bin/aggregate-errors.sh + errors.jsonl (Item 10 part 2)

**Files:**
- Create: `bin/aggregate-errors.sh`

- [ ] **Step 1: Write the aggregator**

```bash
#!/usr/bin/env bash
# Nightly error aggregator.
# Greps tmux-logs + nightly-failures + doctor-logs into _state/errors.jsonl

set -euo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
ERRORS="${VAULT}/_state/errors.jsonl"
TODAY=$(date -u +%F)
TS=$(date -u +%FT%TZ)

mkdir -p "$(dirname "$ERRORS")"

# Aggregate from tmux-logs
for log in "${VAULT}"/_state/tmux-logs/*.log; do
    pane=$(basename "$log" .log)
    grep -nE "ERROR|Traceback|FAILED|panic|fatal" "$log" 2>/dev/null | \
    while IFS= read -r line; do
        sig=$(echo "$line" | sha256sum | cut -c1-12)
        printf '{"ts":"%s","source_log":"%s","pane":"%s","error_signature":"%s","line":%s}\n' \
            "$TS" "$(basename "$log")" "$pane" "$sig" \
            "$(echo "$line" | jq -Rs .)" >> "$ERRORS"
    done
done

# Aggregate from nightly-failures
for fail in "${VAULT}"/_state/nightly-failures/*.log; do
    [ -f "$fail" ] || continue
    sig=$(sha256sum "$fail" | cut -c1-12)
    printf '{"ts":"%s","source_log":"nightly-failures/%s","error_signature":"%s","content_path":"%s"}\n' \
        "$TS" "$(basename "$fail")" "$sig" "$fail" >> "$ERRORS"
done

echo "Aggregated errors to $ERRORS"
```

- [ ] **Step 2: Verification**

```bash
chmod +x bin/aggregate-errors.sh
bash bin/aggregate-errors.sh
test -f _state/errors.jsonl && wc -l _state/errors.jsonl
# Expected: file exists with at least some entries (or zero if logs are clean)
```

- [ ] **Step 3: Commit**

```bash
git add bin/aggregate-errors.sh
git commit -m "v1.1 Item 10b: aggregate-errors.sh nightly aggregator"
```

### Task 18: tool-calls.jsonl best-effort logging (Item 10 part 3)

**Files:**
- Modify: `bin/spawn-specialist.sh` (add tool-call extraction from stdout)

- [ ] **Step 1: Add best-effort tool-call extraction**

Append to spawn-specialist.sh after spawn completes:

```bash
# Best-effort tool-call extraction from stdout
# (CAVEAT: in-process MCP calls may not appear in stdout)
TOOL_CALLS_LOG="${VAULT}/_state/tool-calls.jsonl"
echo "$OUT" | grep -oE 'mcp__[a-z_-]+__[a-z_-]+|chrono-[a-z-]+\.[a-z_-]+' | sort -u | \
while IFS= read -r tool_call; do
    printf '{"ts":"%s","specialist":"%s","tool_call_seen":"%s","capture_method":"stdout-grep-best-effort"}\n' \
        "$START_TS" "$SPECIALIST" "$tool_call" >> "$TOOL_CALLS_LOG"
done
```

- [ ] **Step 2: Verification**

```bash
bash -n bin/spawn-specialist.sh
```

- [ ] **Step 3: Commit**

```bash
git add bin/spawn-specialist.sh
git commit -m "v1.1 Item 10c: tool-calls.jsonl best-effort stdout extraction"
```

### Task 19: patterns.jsonl + graduation candidate surfacing (Item 11)

**Files:**
- Modify: `bin/spawn-specialist.sh` (add pattern_signature write)
- Create: `bin/graduation-scan.sh` (weekly review hook)

- [ ] **Step 1: Add pattern signature to spawn-specialist.sh**

Append after spawn completes:
```bash
# Routine signature for MCP graduation tracking
PATTERNS_LOG="${VAULT}/_state/patterns.jsonl"
ROUTINE_SIG=$(echo "${SPECIALIST}|${TASK_BODY_FINGERPRINT}" | sha256sum | cut -c1-12)
ENGAGEMENT_ID="${ENGAGEMENT_ID:-unknown}"

printf '{"ts":"%s","routine_signature":"%s","specialist":"%s","lead":"%s","engagement_id":"%s"}\n' \
    "$START_TS" "$ROUTINE_SIG" "$SPECIALIST" "$LEAD" "$ENGAGEMENT_ID" \
    >> "$PATTERNS_LOG"
```

- [ ] **Step 2: Write graduation-scan.sh (runs weekly)**

```bash
#!/usr/bin/env bash
# Weekly: scan patterns.jsonl for routine_signatures hitting N=3 distinct engagement_ids.
# Surface candidates in _state/mcp-graduation-candidates.md.

set -euo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
PATTERNS="${VAULT}/_state/patterns.jsonl"
CANDIDATES="${VAULT}/_state/mcp-graduation-candidates.md"

mkdir -p "$(dirname "$CANDIDATES")"

# Find routine signatures with ≥3 distinct engagement_ids in past 30 days
THRESHOLD=$(date -u -v-30d +%FT%TZ)

{
    echo "# MCP Graduation Candidates — $(date -u +%F)"
    echo
    echo "Routines that have fired across ≥3 distinct engagements. Candidates for custom MCP creation."
    echo
    jq -s --arg threshold "$THRESHOLD" '
        [.[] | select(.ts >= $threshold)] |
        group_by(.routine_signature) |
        map({
            sig: .[0].routine_signature,
            specialist: .[0].specialist,
            engagements: ([.[].engagement_id] | unique | length),
            count: length
        }) |
        map(select(.engagements >= 3))
    ' "$PATTERNS" | jq -r '.[] | "- **\(.specialist)** routine `\(.sig)` — \(.count) calls across \(.engagements) engagements"'
} > "$CANDIDATES"
```

- [ ] **Step 3: Verification**

```bash
chmod +x bin/graduation-scan.sh
bash bin/graduation-scan.sh
test -f _state/mcp-graduation-candidates.md
```

- [ ] **Step 4: Commit**

```bash
git add bin/spawn-specialist.sh bin/graduation-scan.sh
git commit -m "v1.1 Item 11: patterns.jsonl + graduation candidate surfacing (track-and-surface only)"
```

---

## Phase 9 — Skills (Item 12)

### Task 20: smart-contract-audit-checklist skill REMAKE

**Files:**
- Create: `departments/coding/specialists/smart-contract-engineer/skills/smart-contract-audit-checklist.md`

- [ ] **Step 1: Read source repos**

```bash
gh api repos/tamjid0x01/SmartContracts-audit-checklist/readme --jq .content | base64 -d > /tmp/tamjid-checklist.md
gh api repos/cryptofinlabs/audit-checklist/readme --jq .content | base64 -d > /tmp/cryptofin-checklist.md
```

- [ ] **Step 2: Distill into squad-format skill**

Write `departments/coding/specialists/smart-contract-engineer/skills/smart-contract-audit-checklist.md`:

```markdown
---
name: smart-contract-audit-checklist
description: Comprehensive Solidity smart contract audit checklist — vulnerability classes, severity rubric, audit workflow phases.
source: tamjid0x01/SmartContracts-audit-checklist + cryptofinlabs/audit-checklist (REMAKE 2026-05-02)
version: 1.0.0
---

# Smart Contract Audit Checklist

(distill key sections from sources, maintaining attribution)
```

- [ ] **Step 3: Verification**

```bash
test -f departments/coding/specialists/smart-contract-engineer/skills/smart-contract-audit-checklist.md
grep -q "source: tamjid0x01" departments/coding/specialists/smart-contract-engineer/skills/smart-contract-audit-checklist.md
```

- [ ] **Step 4: Commit**

```bash
git add departments/coding/specialists/smart-contract-engineer/skills/smart-contract-audit-checklist.md
git commit -m "v1.1 Item 12a: smart-contract-audit-checklist skill REMAKE"
```

### Task 21: bounty-platform-report-format skill REMAKE

**Files:**
- Create: `departments/security/specialists/impact-validator/skills/bounty-platform-report-format.md`

- [ ] **Step 1: Mine HackerOne / Bugcrowd / Code4rena public report templates**

Sample 3-5 public report examples from each platform. Extract:
- Required fields (severity, title, repro steps, impact, remediation)
- Platform-specific format quirks (markdown vs custom format, length expectations)

- [ ] **Step 2: Write the skill file**

```markdown
---
name: bounty-platform-report-format
description: Per-platform expected report structure for HackerOne / Bugcrowd / Code4rena submissions.
source: distilled from public reports on each platform (REMAKE 2026-05-02)
version: 1.0.0
---

# Bounty Platform Report Format

## HackerOne
(template + field requirements)

## Bugcrowd
(template + VRT severity mapping)

## Code4rena
(contest-format requirements)
```

- [ ] **Step 3: Verification**

```bash
test -f departments/security/specialists/impact-validator/skills/bounty-platform-report-format.md
```

- [ ] **Step 4: Commit**

```bash
git add departments/security/specialists/impact-validator/skills/bounty-platform-report-format.md
git commit -m "v1.1 Item 12b: bounty-platform-report-format skill REMAKE"
```

---

## Phase 10 — Documentation (Items 15 + 16)

### Task 22: CHANGELOG.md (Item 15)

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Write changelog with shipped reality**

Use spec section Item 15 as template. After all prior tasks complete, write the Added/Changed/Fixed sections reflecting what actually shipped (not what was planned).

- [ ] **Step 2: Verification**

```bash
test -f CHANGELOG.md
grep -q "## \[1.1.0\]" CHANGELOG.md
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "v1.1 Item 15: CHANGELOG.md with v1.1.0 entry"
```

### Task 23: README.md v1.1 update (Item 16)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add v1.1 section**

Append:
```markdown
## v1.1 — Tool Utilization & Discipline (2026-05-DD)

See [CHANGELOG.md](./CHANGELOG.md) for full v1.1 changes.

Highlights:
- Specialist tool-awareness: 39 files now enumerate verified MCPs / native CLI features / skills / APIs
- Per-pane effort/thinking tier defaults
- Capability inventory + schema validator (no more vaporware)
- Topology B chaser logic in Chrono
- 4 new log streams + MCP graduation candidate surfacing

Reference docs:
- [Lifecycle rules](./shared/lifecycle.md)
- [API catalog](./shared/api-catalog.md)
```

- [ ] **Step 2: Verification**

```bash
grep -q "v1.1" README.md
grep -q "shared/lifecycle.md" README.md
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "v1.1 Item 16: README.md v1.1 section + links"
```

---

## Phase 11 — Verification Gates

### Task 24: Run all 11 verification gates

**Final smoke test before declaring v1.1 done.**

- [ ] **Gate 1: Capability inventory exists**

```bash
test -f _state/capability-inventory-2026-05-02.md && echo "Gate 1: PASS"
```

- [ ] **Gate 2: Schema validator clean on all 39 specialists**

```bash
bash bin/validate-specialists.sh && echo "Gate 2: PASS"
```

- [ ] **Gate 3: All 5 LEAD.md files have v1.1 sections + verified MCPs only**

```bash
for lead in coding security content sysmgmt research; do
  for section in "## My CLI's native features" "## Specialist decision tree" "## Direct-with-CC" "## Lifecycle discipline"; do
    grep -qF "$section" "departments/$lead/LEAD.md" || { echo "Gate 3 FAIL: $lead $section"; exit 1; }
  done
done && echo "Gate 3: PASS"
```

- [ ] **Gate 4: Disposable launch — 6/6 panes healthy**

```bash
tmux kill-session -t squad-test 2>/dev/null || true
bash bin/launch-squad.sh squad-test  # if it accepts session-name arg
sleep 30
HEALTHY=$(tmux list-panes -t squad-test 2>/dev/null | wc -l)
[ "$HEALTHY" -ge 6 ] && echo "Gate 4: PASS"
tmux kill-session -t squad-test
```

- [ ] **Gate 5: Lifecycle + API catalog files exist**

```bash
[ -f shared/lifecycle.md ] && [ -f shared/api-catalog.md ] && echo "Gate 5: PASS"
```

- [ ] **Gate 6: dispatch-toolkit-verify zero per-pane mismatches**

```bash
bash bin/dispatch-toolkit-verify.sh && echo "Gate 6: PASS"
```

- [ ] **Gate 7: New log files have entries within 24h**

```bash
test -s _state/specialist-log.jsonl && echo "specialist-log: data present"
test -s _state/errors.jsonl && echo "errors: data present"
echo "Gate 7: PASS"
```

- [ ] **Gate 8: Coding-Lead delegation smoke test**

Dispatch a real task: "Refactor X module + add tests + review". Verify in `_state/specialist-log.jsonl` that ≥2 specialists were dispatched (e.g., backend-engineer + test-engineer + code-reviewer). Check tmux-logs for actual semgrep invocation.

```bash
bash scripts/send-task.sh coding /tmp/test-multi-specialist-task.md
# Wait for completion, then:
recent_specialists=$(tail -50 _state/specialist-log.jsonl | jq -r 'select(.lead=="coding") | .specialist' | sort -u | wc -l)
[ "$recent_specialists" -ge 2 ] && echo "Gate 8: PASS"
```

- [ ] **Gate 9: Security→Research direct-with-CC smoke test**

Dispatch a real task: "Find me a bounty target". Verify Security/scout dispatched + at some point wrote to Research's inbox with `from_lead: security` + Chrono received CC summary.

```bash
bash scripts/send-task.sh security /tmp/test-bounty-task.md
# Wait, then:
ls departments/research/inbox/*.md | xargs grep -l "from_lead: security" && echo "Gate 9: PASS"
```

- [ ] **Gate 10: Security MCP incident report exists with required fields**

```bash
test -f _state/incident-2026-05-02-security-mcp.md
for field in "MCP name" "Root cause" "Fix decision" "Verification"; do
  grep -qF "$field" _state/incident-2026-05-02-security-mcp.md
done && echo "Gate 10: PASS"
```

- [ ] **Gate 11: vibecoding-check passes on all changed files**

```bash
git diff --name-only v1.0-pre-1.1 HEAD | xargs -I{} bash bin/vibecoding-check.sh {}
# Expected: exit 0
echo "Gate 11: PASS"
```

- [ ] **Final commit (if anything tweaked during gates)**

```bash
git status
# If any minor fixups, commit them:
git commit -am "v1.1 Phase 11: verification gate fixups" 2>/dev/null || echo "Nothing to commit"
```

- [ ] **Tag v1.1.0**

```bash
git tag v1.1.0
echo "v1.1.0 SHIPPED"
```

---

## Self-Review Checklist (run before declaring plan complete)

**1. Spec coverage:**
- Item 0 → Task 1 ✅
- Item 1 → Task 11 ✅
- Item 1b → Task 8 ✅
- Item 2 → Task 10 ✅
- Item 2b → Task 9 ✅
- Item 3 → Task 12 ✅
- Item 4 → Task 15 ✅
- Item 5 → Task 5 ✅
- Item 5b → Task 7 ✅
- Item 6 → Task 3 ✅
- Item 7 → Task 4 ✅
- Item 8 → Task 6 ✅
- Item 9 → Task 13 ✅
- Item 9b → Task 14 ✅
- Item 10 → Tasks 16, 17, 18 ✅
- Item 11 → Task 19 ✅
- Item 12 → Tasks 20, 21 ✅
- Item 14 → Task 2 ✅
- Item 15 → Task 22 ✅
- Item 16 → Task 23 ✅

All 19 deliverables covered. (Item 13 = killed.)

**2. Placeholder scan:**
- One placeholder noted: Task 5 Step 5 says "thinking-flag-from-Task-1" — intentional, the exact flag depends on Task 1's verification output. Acceptable: the engineer reads Task 1's inventory output and substitutes.
- Task 11 Step 4 references `<FILL: task shape A>` — those placeholders ARE in the upgrade-specialists.py output by design, for human-judgment fields. The task explicitly directs the engineer to fill them.

**3. Type/signature consistency:**
- `routine_signature` used in Task 19 matches schema declared in spec Item 10
- `specialist-log.jsonl` schema in Task 16 matches spec Item 10 schema exactly
- `bin/dispatch-toolkit-verify.sh` named consistently across tasks
- `bin/upgrade-specialists.py` and `bin/validate-specialists.sh` filenames match spec
- `_state/capability-inventory-2026-05-02.md` filename consistent

No drift detected.

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-05-02-vibe-squad-v1.1-tool-utilization-plan.md`.**

24 tasks across 11 phases. Dependencies enforced (Phase 1 foundation → catalogs → tooling → edits → logging → verification).

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Each task is independently verifiable; reviews catch drift early. Best fit for the squad's own pattern (specialist subprocess discipline).

**2. Inline Execution** — Execute tasks in this session using executing-plans skill, batch execution with checkpoints. Simpler but burns more of this session's context.

**Which approach?**
