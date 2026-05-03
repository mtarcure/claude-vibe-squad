---
spec: claude-vibe-squad v1.1 — Tool Utilization & Discipline Fixes
date: 2026-05-02
author: Chrono (Claude Opus 4.7) + Matt (operator)
reviewers: Codex GPT-5.5, Gemini 3.1
status: approved-for-build
revision: 2 (post-multi-model review; depwire killed, 4 items added, 4 items modified)
prior_version: v1.0 (initial squad bring-up, 2026-04 → 2026-05-02)
target_version: v1.1.0
---

# claude-vibe-squad v1.1 — Tool Utilization & Discipline Fixes

## Overview

The squad is operational at v1.0: 6 tmux panes, 5 Department Leads, 39 specialists, mailbox protocol, and ~3000 lines of supporting Python+shell. **It runs.** What it doesn't do well yet is *fully use the tools available to it*.

v1.1 is a **fix release, not a redesign.** It addresses three categories of gap:

1. **Tool-awareness gap** — specialist `identity.md` files don't enumerate the MCPs / native CLI features / APIs / skills available to them. When dispatched, specialists default to `WebFetch` because that's the most prominent tool in their context.
2. **Effort-tier gap** — `bin/launch-squad.sh` sets zero effort/thinking flags. Codex panes run on `effort=none`. Gemini and Kimi panes have thinking-mode OFF. Claude panes use whatever the model defaults to. This wastes the entire premise of buying max-tier subscriptions.
3. **Self-improvement gap** — the squad has logging but no pattern tracker, no MCP-graduation criterion, no weekly review routine. It can't notice "this routine fired N times across engagements" without manual review.

v1.1 ships a fix for each. **No new architecture, no new modes, no new mailbox protocol, no v2 redesign.** Where this spec sees something missing in v1.0 that is genuinely architectural, it is flagged as out-of-scope.

## Multi-model review summary (2026-05-02)

This spec was reviewed by Codex GPT-5.5 and Gemini 3.1 (writer-family ≠ reviewer-family). Both returned **YELLOW LIGHT** with high-overlap concerns. Operator's policy: **no v1.2 deferrals** — items either ship in v1.1 or are killed entirely.

**Net effect of the review:**
- ❌ **1 item killed:** Optional `depwire` MCP install (was already optional; adds tools to a system whose problem is enumeration accuracy, not tool count)
- ➕ **4 items added** (per reviewer feedback): capability inventory (Item 0), specialist-pass automation script (Item 1b), schema validator (Item 2b), Topology B chaser logic (Item 9b), token-spend guardrail (Item 5b)
- 🔧 **4 items modified:** Item 7 api-catalog gets `verified` flag per entry; Item 10 logging gets best-effort caveats; Item 11 graduation loop simplified to track-and-surface (no auto-scaffold); rollback plan strengthened
- 🔧 **Stronger verification gates** per reviewer specifics

**Result: 19 deliverables.** Larger than the original 16 but coherent — nothing deferred, nothing pending.

## What v1.1 is NOT

To be loud about this, since the brainstorm drifted into v2 territory more than once before reaching this spec:

- ❌ Not a v2 architecture redesign
- ❌ Not adding new modes (Maintenance, Incident, etc.)
- ❌ Not adopting DAG/topological dispatch for mode phases
- ❌ Not migrating from tmux send-keys to hook-based message delivery
- ❌ Not building a new operator dashboard (existing `bin/dashboard.sh` + `bin/morning-brief.sh` + `bin/where-are-we.sh` stay)
- ❌ Not expanding the roster to 57 specialists
- ❌ Not building 8 custom routine MCPs (the graduation loop simplification means no MCPs get auto-built; only candidates surface for operator approval)
- ❌ Not optimizing terminal UX (split-pane refinement, etc.)
- ❌ Not migrating from filesystem mailbox to SQLite

## Problem statement (the actual reported issues)

From operator's recent live-use of the squad:

1. *"The system didn't misroute bounty work — it just didn't use the research system properly."* Security Lead picked up a bounty target task but didn't dispatch to Research for OSINT, didn't fan out to its own scout/security-analyst specialists, and produced a thinner answer than the squad is capable of.
2. *"When work went to coding it didn't seem to use many tools etc."* Coding Lead processed a task using basic Bash + WebFetch, despite having access to 14 specialists, semgrep MCP, context7 MCP, chrome-devtools MCP, and `codex review` native subcommand.
3. *"Some MCPs in dispatch-toolkit.sh aren't actually installed."* `shared/dispatch-toolkit.sh` enumerates `chrono-research-arsenal/{perplexity, brave, serper, apify}` and other MCPs — but only Perplexity is actually bound. Doc is partially vaporware.
4. *"Security Lead hit an error."* Two MCP servers failed in security/sysmgmt panes; root cause never investigated.
5. *"Models aren't on proper thinking — Claude and Codex should be on xhigh."* Verified: zero effort/thinking flags set in `bin/launch-squad.sh`.

These are tool-utilization and instrumentation problems, not architecture problems.

## Architecture (unchanged from v1.0)

| Component | Status |
|-----------|--------|
| 6 tmux panes (chrono + 5 Leads) | unchanged |
| Filesystem mailbox | unchanged |
| `tmux send-keys` nudge via `fswatch` daemons | unchanged (hook-based delivery deferred) |
| Specialist subprocess pattern | unchanged |
| Per-CLI subscription auth (env-drop pattern) | unchanged |
| Multi-model verification (writer ≠ reviewer family) | unchanged |
| 5 modes (Project, Bounty, Freelance, Research, Browse) | unchanged |
| Topology B (direct-with-CC) | unchanged; chaser logic added in this spec |
| 4-tier model assignment | unchanged |
| 39 specialist files | unchanged (no roster expansion) |

## Deliverables — 19 items

### Item 0 — Capability Inventory (NEW, MUST RUN FIRST)

**Reason added:** Codex caught that the spec made many CLI/flag/feature claims that may be wrong. If 20% of identity-file MCP/feature references are vaporware, we replace one tool-mythology problem with another. v1.1 must verify before it specifies.

**Target:** new file `_state/capability-inventory-2026-05-02.md`

**Process:**
1. Run `--help` for each CLI: `claude --help`, `codex --help`, `gemini --help`, `kimi --help`. Save output snippets verbatim.
2. Run `mcp list` for each CLI in its actual pane: `claude mcp list` (in chrono pane), `codex mcp list` (in coding pane), `gemini mcp list` (in content pane), `kimi mcp list` (in research pane). Save lists.
3. Test the specific flags claimed in this spec — `claude --effort xhigh`, `codex -c model_reasoning_effort=high`, `gemini --thinking` (or whatever the actual flag is), `kimi --thinking`. Verify each accepts without error.
4. Record installed local skills: `find ~/.claude/plugins/cache -path "*/skills/*" -name "SKILL.md"` summary.

**Output schema** (`_state/capability-inventory-2026-05-02.md`):

```markdown
# Capability Inventory — 2026-05-02

## Per-CLI verified flags
### claude
- `--effort {low,medium,high,xhigh,max}` ✅ verified
- `--model {opus,sonnet,haiku}` ✅ verified
- `--mcp-config <path...>` ✅ verified
- `--ultrareview` ❓ verified-as-slash-command-not-flag
- ...

### codex
- `-c model_reasoning_effort={none,low,medium,high}` ✅ verified
- `codex review` ✅ verified-subcommand
- ...

### gemini
- `--thinking` ❓ NEEDS-VERIFICATION (run live)
- ...

### kimi
- `--print` ✅ verified
- `--thinking` / `--no-thinking` ✅ verified
- ...

## Per-pane MCPs verified bound at launch
### chrono pane
- chrono-vault ✅
- chrono-research-arsenal/perplexity ✅
- chrono-content-engineer ✅
...

### coding pane
- (semgrep, context7, chrome-devtools, etc.)

(continue for all 6 panes)

## Local skill catalog
331 unique skills across 40+ plugins — see `find` snippet output

## Features claimed in spec but UNVERIFIED
- Anthropic /ultrareview CLI behavior (verify)
- Gemini Nano Banana Pro / 2 access via gemini CLI (verify)
- Gemini Imagen / Veo flags (verify or replace with API calls)
- Kimi 300 parallel sub-agents native (verify usage)
- Jules / Flow / NotebookLM / Antigravity (Google ecosystem — needs research)
- xAI Grok-X integration (needs API setup)
- DeepSeek V4 access (needs API setup)
```

**Verification gate:** file exists; every feature cited in `shared/api-catalog.md` and specialist files corresponds to either a `✅ verified` or `❓ NEEDS-VERIFICATION` entry here.

### Item 1 — Specialist tool-awareness pass (39 files)

**Target:** every `departments/<lead>/specialists/<name>.md`

**Change:** add structured sections to each specialist's identity bundle. Constraint: specialist files may only cite MCPs/features marked `verified: yes` in `shared/api-catalog.md`. Unverified items can be referenced as "available pending verification" with a tag.

Required sections:

```markdown
## Tools available to me

### MCPs (verified-installed only)
- `<mcp-name>` — <one-line purpose>. Use when: <condition>.

### Native CLI features (verified)
- `<feature-or-flag>` — <one-line purpose>. Use when: <condition>.

### Skills (read these on task start)
- `<skill-name>` (from `<source>`)

### APIs available (via env)
- `<API_KEY_NAME>` → `<service>` — <when to use>

## When to fan out

- For <task shape A>: dispatch to <peer specialist> via Lead's mailbox.
- For <task shape B>: handle solo.
- For <task shape C>: surface to operator (out of my scope).

## When to escalate

- If <condition>, stop and write to outbox with status: needs_human.

## What I do NOT do

- WebFetch is fallback only — use named MCPs first when task shape matches.
- ...
```

**Specialist priority order:**
- Tier A — high-frequency (~12 files): `coding/{code-reviewer, backend-engineer, frontend-engineer, ui-engineer, test-engineer}`, `security/{scout, security-analyst, threat-modeler}`, `research/{research, synthesizer}`, `content/{writer, technical-writer}`
- Tier B — moderate (~17 files)
- Tier C — low-frequency (~10 files)

**Verification gate:** schema-validator script (Item 2b) returns clean for all 39 files.

### Item 1b — `bin/upgrade-specialists.py` automation script (NEW)

**Reason added:** Gemini caught that 39 manual file edits = recipe for inconsistency. Script-driven schema injection enforces uniform structure.

**Target:** new file `bin/upgrade-specialists.py`

**Behavior:**
1. Reads each existing specialist file's frontmatter
2. Identifies which Lead it belongs to + its CLI family
3. Injects the required v1.1 sections (Tools available, When to fan out, When to escalate, What I do NOT do) AFTER the existing role description, BEFORE any existing trailing sections
4. Pre-fills tool/feature lists from `shared/api-catalog.md` matched by specialist's Lead-CLI
5. Leaves placeholders `<FILL: task shape A>` for human-judgment fields the operator/Lead-author should complete
6. Writes back atomically (temp + fsync + rename)
7. Produces `_state/upgrade-specialists-report-2026-05-02.md` listing: file modified, sections injected, placeholders left, conflicts flagged

**Verification gate:**
- Script runs to completion with exit 0
- All 39 files pass schema validator (Item 2b)
- Report file exists with per-file detail

### Item 2 — Lead briefs updated (5 files)

**Target:** `departments/<lead>/LEAD.md` for each of: coding, security, content, sysmgmt, research

**Change:** add four new sections per Lead:

```markdown
## My CLI's native features

(Lead-specific. Per Capability Inventory verified entries only.)

## Specialist decision tree

| Task shape | Specialist | Why |
|-----------|-----------|-----|
| ... | ... | ... |

## Direct-with-CC patterns (Topology B)

When to write directly to a peer Lead's inbox (instead of routing through Chrono):
- <use case>: write to `departments/<peer>/inbox/`, CC summary to `chrono/inbox/`

NEVER do direct cross-Lead for: operator-facing decisions, mode transitions, anything requiring approval.

## Lifecycle discipline

See `shared/lifecycle.md`. Per this Lead:
- Effort tier default: `<low|high|xhigh>` (set in launch-squad.sh)
- Compaction trigger: <condition>
- Memory.md update cadence: <when>
```

Per-Lead native CLI feature highlights are populated from Item 0 capability inventory — only `verified: yes` entries appear.

### Item 2b — Specialist schema validator (NEW)

**Reason added:** Codex caught that grep-for-headings is weak. Schema validator enforces accuracy.

**Target:** new file `bin/validate-specialists.sh` (or .py)

**Behavior:**
1. For each `departments/*/specialists/*.md`:
   - Verify required sections present (Tools available to me, When to fan out, When to escalate, What I do NOT do)
   - Parse the MCP names listed under "MCPs"; verify each appears as `verified: yes` in `shared/api-catalog.md`
   - Parse skill names listed under "Skills"; verify each exists in local skill catalog
   - Parse API names listed under "APIs available"; verify each env var exists in `~/.config/shell/secrets.zsh` shape (don't print values, just exists check)
   - Parse "When to fan out" peer-specialist references; verify each path exists
2. Output JSON: `{file, status: pass|fail, issues: [...]}`
3. Exit 0 if all pass; exit 1 if any fails

**Verification gate:** script runs returning exit 0 for all 39 files.

### Item 3 — Lead memory.md notes (5 files)

**Target:** `departments/<lead>/memory.md`

**Change:** append v1.1 durable insight per Lead. Single section ~5 lines.

**Verification gate:** grep each `memory.md` for "v1.1 update — 2026-05-02".

### Item 4 — Coordinator brain (chrono/CLAUDE.md + chrono/SOUL.md + vault CLAUDE.md)

**Targets:**
- `chrono/CLAUDE.md` — coordinator runtime rules
- `chrono/SOUL.md` — coordinator identity (minor edit)
- `CLAUDE.md` (vault root) — system-wide hard rules

**Changes:**

#### `chrono/CLAUDE.md`
- Add reference to `shared/lifecycle.md`
- Add explicit Topology B policy + reference to chaser logic (Item 9b)
- Add note: "Routing rule for 'research' or 'scout' verbs — check the noun before dispatching"
- Add per-pane effort-tier table reference

#### `chrono/SOUL.md`
- Note: Chrono recognizes when routines have fired enough to candidate for MCP-ification (track-and-surface only — Chrono surfaces, operator decides)

#### `CLAUDE.md` (vault root)
- Add reference to `shared/lifecycle.md`
- Reference `shared/api-catalog.md`
- Tighten "specialists must use named MCPs not WebFetch" rule with explicit example

**Verification gate:** grep each file for explicit references to `shared/lifecycle.md` and `shared/api-catalog.md`.

### Item 5 — bin/launch-squad.sh effort/thinking flags per pane

**Target:** `bin/launch-squad.sh`

**Change:** update per-pane start commands per CLI's verified scale (Item 0 confirms exact flag names):

```bash
# chrono pane
'Start with: claude --permission-mode acceptEdits --add-dir VAULT --model opus --effort xhigh'

# coding pane
'Start with: codex --sandbox workspace-write --ask-for-approval never -c model_reasoning_effort=high'

# security pane
'Start with: claude --permission-mode bypassPermissions --add-dir VAULT --model opus --effort xhigh'

# content pane (verify exact thinking-mode flag from Item 0 inventory)
'Start with: gemini --yolo --include-directories VAULT --model gemini-3.1-pro-preview [thinking-flag-from-inventory]'

# sysmgmt pane
'Start with: claude --permission-mode bypassPermissions --add-dir VAULT --model sonnet --effort high'

# research pane
'Start with: kimi --yolo --add-dir VAULT --thinking'
```

**Pre-deployment test (per reviewer concern):** changes deployed to disposable tmux session first; verify each pane launches without error before committing to default `bin/launch-squad.sh`.

**Verification gate:**
- `grep -E "effort|thinking|--model" bin/launch-squad.sh` returns matches in every pane stanza
- Disposable launch returns 6/6 panes healthy at squad-start

### Item 5b — Token-spend guardrail (NEW)

**Reason added:** Codex caught that `xhigh` defaults could cause spend surprises. First-week monitoring cap.

**Target:** extension to `finance-analyst` specialist (existing) + new `_state/token-budget-2026-05-W2.md`

**Change:**
- **Baseline source** (per Codex re-review): auto-derived from past 7 days of `_state/dispatch-log.jsonl` per-Lead token estimates. If insufficient history (<7 days), operator-entered values from week 0 squad operation, recorded in `_state/token-budget-2026-05-W2.md` with timestamp + source.
- Set first-week soft cap = baseline × 1.0; alert threshold = baseline × 1.5
- `finance-analyst` runs daily during first week (instead of weekly normal cadence)
- If any pane crosses 1.5× baseline, surface in next morning brief: *"Pane X spending Y% above baseline; review effort-tier setting."*
- After first week passes without surprise: revert to weekly cadence

**Verification gate:** budget doc exists at week launch with explicit baseline source field populated; finance-analyst writes daily summaries to `_state/finance-daily/2026-05-W2-{date}.md` for first 7 days.

### Item 6 — `shared/lifecycle.md` (NEW)

**Target:** new file at `shared/lifecycle.md`

**Contents:** the 9 lifecycle rules + per-pane effort defaults. Single canonical doc. (Content unchanged from prior spec draft — see appendix below or the brainstorm record.)

**Verification gate:** file exists; chrono/CLAUDE.md and vault CLAUDE.md reference it.

### Item 7 — `shared/api-catalog.md` (NEW, with `verified` flag per entry)

**Reason modified:** Codex/Gemini caught that broad ecosystem catalog risks new vaporware. Per-entry `verified` flag fixes this without dropping breadth (operator wants the full catalog).

**Target:** new file at `shared/api-catalog.md`

**Schema:**

```markdown
## Anthropic / Claude

### Claude Design (web app)
- url: claude.ai/design
- access: Pro/Max/Team/Enterprise
- specialists: designer (Content), ui-engineer (Coding)
- verified: yes / no / needs-research
- last_checked: 2026-05-02
- test_reference: <command or doc path that proves this works — required when verified: yes>
- notes: <usage notes>
- research_task: <if needs-research, who/what/when to investigate>
```

Every entry has `verified: yes | no | needs-research`. **Every `verified: yes` entry MUST have a `test_reference` field** (per Codex re-review): a runnable command or doc citation that proves the feature works. Validator (Item 2b) rejects `verified: yes` entries lacking `test_reference`. Specialist files (Item 1) may only cite `verified: yes` entries.

**Within-v1.1 research tasks** (NOT deferred to v1.2):
- Jules / Flow / NotebookLM / Antigravity (Google ecosystem) — `harness-optimizer` task to investigate during v1.1 build window
- xAI / Grok-X integration — `harness-optimizer` task to set up API + verify endpoints
- DeepSeek V4 — `harness-optimizer` task to verify API access + add to T1/T2 fanout pool

These run AS PART OF v1.1 build, not as v1.2 work. Each produces a sub-task report; if verified, entry flips from `needs-research` to `yes`; if not viable, flips to `no`.

**Verification gate:** file exists; every `verified: yes` entry has a verifiable test referenced; no `needs-research` entry blocks specialist-file authoring (specialists ignore them).

### Item 8 — `shared/dispatch-toolkit.sh` reality-check

**Target:** `shared/dispatch-toolkit.sh`

**Change:**
- Trim `chrono-research-arsenal` from coding/security/content/sysmgmt sections (keep only in Research)
- Replace placeholder MCP enumeration with actually-installed MCPs (sourced from Item 0 inventory, per pane)
- Add launch-time pre-flight: `bin/dispatch-toolkit-verify.sh` runs at squad launch; warns if any MCP enumerated for a pane isn't actually installed in that pane's CLI
- Per Codex: dispatch-toolkit-verify.sh checks **per pane**, not globally

**Verification gate:**
- `grep "chrono-research-arsenal" shared/dispatch-toolkit.sh` returns matches ONLY in research section
- `bash bin/dispatch-toolkit-verify.sh` reports zero per-pane mismatches at squad launch

### Item 9 — `chrono/operator-setup.md` routing-rule clarifications

**Target:** `chrono/operator-setup.md`

**Change:** strengthen routing disambiguation table with worked examples for cross-Lead direct-with-CC patterns. Specifically the failure mode that prompted this spec (*"Security needed Research mid-task and didn't dispatch"*).

### Item 9b — Topology B chaser logic (NEW)

**Reason added:** Gemini caught that Topology B introduces "whispering" risk — Lead-to-Lead direct comms without Chrono tracking pending replies.

**Target:** edits to `chrono/CLAUDE.md` + `chrono/current.md` schema

**Change:**
- Chrono's `current.md` gains a "Cross-Lead pending replies" section that tracks CC'd threads (when Lead A messages Lead B and CCs Chrono, Chrono logs a pending entry with thread_id, owner, deadline)
- Chrono scans cross-Lead pending entries at start of every operator turn alongside its own outboxes
- If a pending cross-Lead reply exceeds soft-deadline (2 hours default), Chrono surfaces: *"Coding asked Research about X 2h ago — no reply yet. Want me to chase?"*

**Verification gate:** Chrono's current.md template includes the pending-replies section; when test cross-Lead message fires (Item 14 smoke test), entry appears in Chrono's tracker within 30s.

### Item 10 — Four log streams + weekly review routine

**Reason modified:** reviewer concern about MCP-protocol-level logging being incomplete. Best-effort caveats added; logs still ship in v1.1 since tracking dispatches/specialists/errors/patterns is independently valuable.

**Targets:**

#### `_state/specialist-log.jsonl` (full reliability)
Schema: `{ts, lead, specialist, model, effort, mcp_set_hash, allowed_tools, task_id, exit_code, duration_ms, stdout_bytes}`
Write source: subprocess-spawn helper (new helper script or inline in send-task.sh)

#### `_state/tool-calls.jsonl` (BEST-EFFORT, see caveats)
Schema: `{ts, lead_or_specialist, mcp, tool, args_summary, success, duration_ms, error_msg}`
Write source: shell-helper-wrapped MCP calls + chrono-vault writes captured. **CAVEAT:** in-process MCP calls within the CLI itself may not be captured in v1.1 (depends on each CLI's hook/event surface). Logged completeness is partial; entries that DO appear are accurate.

#### `_state/errors.jsonl` (full reliability via aggregation)
Schema: `{ts, source_log, error_signature, lead, specialist, count_in_period}`
Write source: nightly aggregator from tmux-logs, nightly-failures, doctor-logs.

#### `_state/patterns.jsonl` (best-effort completeness, full per-entry accuracy)
Schema: `{ts, routine_signature, specialist, lead, mode, engagement_id}`
Write source: subprocess-spawn helper. **CAVEAT:** routine_signature is hash of dispatch-call shape (specialist + verified-tool-bag); in-process tool-call data missing per above caveat doesn't pollute the signature.

#### Weekly review routine (extends existing weekly-briefs)
`harness-optimizer` runs Sunday — produces `_state/weekly-briefs/<date>.md` with:
- Top 10 most-dispatched specialists (from specialist-log)
- Most-failed routines (from errors)
- MCP graduation candidates (Item 11)
- Anomaly flags

**Verification gate:**
- Each new log file has ≥ 1 entry within 24h of v1.1 launch
- Weekly brief on first Sunday post-launch shows non-empty content

### Item 11 — Pattern tracker → MCP graduation candidate surfacing (SIMPLIFIED)

**Reason modified:** both reviewers flagged auto-scaffold-on-graduation as v2 work. Simplified to track-and-surface only.

**Target:** logic in `harness-optimizer` weekly review (Item 10)

**Change:**
- When a routine_signature hits N=3 distinct engagement_ids, harness-optimizer writes entry to `_state/mcp-graduation-candidates.md`
- Surfaces in next morning brief: *"Pattern X has fired 3 times across [engagements A, B, C]. Candidate for custom MCP. Approve?"*
- **No automatic scaffold.** Operator manually decides + manually triggers MCP creation if approved (potentially via dispatching Coding Lead's `ai-engineer` + skill-creator skills).
- chrono-vault gets entry recording the surfaced candidate (whether approved or rejected, for instinct trail)

**Verification gate:** graduation-candidates.md exists (may be empty for weeks); harness-optimizer.md specialist file documents the surfacing flow; first real graduation may not happen until weeks/months in — that's expected.

### Item 12 — Two skill REMAKEs

**Reason kept:** these ARE real missing skills the squad will use. Reviewer "scope drift" concern noted but operator confirmed the skills are needed.

#### `smart-contract-audit-checklist`
- **Source:** tamjid0x01/SmartContracts-audit-checklist (789 ⭐) + cryptofinlabs/audit-checklist (367 ⭐)
- **Target:** `departments/coding/specialists/smart-contract-engineer/skills/smart-contract-audit-checklist.md`
- **Process:** REMAKE per existing policy (don't fork). Read both repos' checklists, distill into squad-format markdown skill (~200 lines). Frontmatter cites sources.
- **Verification gate:** new skill exists; smart-contract-engineer.md cites it in skills section.

#### `bounty-platform-report-format`
- **Source:** mine HackerOne / Bugcrowd / Code4rena public report templates
- **Target:** `departments/security/specialists/impact-validator/skills/bounty-platform-report-format.md`
- **Process:** REMAKE — extract per-platform expected report structure.
- **Verification gate:** new skill exists; impact-validator and bounty-report-humanization skills reference it.

### Item 13 — KILLED

`depwire` MCP install REMOVED entirely. Adding tools to a system whose problem is enumeration accuracy doesn't fix the root issue. Reviewer concern + operator approval.

### Item 14 — Investigate Security Lead MCP errors (RUNS PARALLEL WITH ITEM 0)

**Target:** the actual MCP failures from prior runs

**Action:**
1. `tmux pipe-pane` logs at `_state/tmux-logs/security.log` — grep for "MCP server failed" or similar
2. Identify which 2 MCPs failed and why
3. **Acceptance criteria** (per Codex feedback): identify exact MCP names, root cause, fix/decision (remove from catalogs OR restore), and document
4. Document in `_state/incident-2026-05-02-security-mcp.md`

**Verification gate:**
- All MCPs in security pane bound at startup with zero warnings
- `claude mcp list` in security pane returns the expected set
- Incident report exists with the four required fields

### Item 15 — `CHANGELOG.md` (NEW)

**Target:** new `CHANGELOG.md` at vault root

**Contents:** documents only ACTUAL shipped behavior (per Codex — write last, after build).

```markdown
# claude-vibe-squad — Changelog

## [1.1.0] - 2026-05-DD — Tool Utilization & Discipline

### Added
- Capability inventory at `_state/capability-inventory-2026-05-02.md`
- Specialist tool-awareness pass: every specialist file enumerates verified MCPs / native CLI features / skills / APIs / fan-out patterns
- `bin/upgrade-specialists.py` automation script for schema injection
- `bin/validate-specialists.sh` schema validator
- Per-pane effort/thinking tier defaults in `bin/launch-squad.sh`
- `shared/lifecycle.md` — 9 canonical rules + effort defaults
- `shared/api-catalog.md` — full API/feature catalog with per-entry verified flag
- Topology B chaser logic in Chrono's pending-replies tracker
- First-week token-spend guardrail (finance-analyst daily mode)
- Four new log streams (specialist-log full; tool-calls best-effort; errors; patterns)
- Weekly log review routine; MCP graduation candidate surfacing at N=3
- Two new skills: smart-contract-audit-checklist, bounty-platform-report-format

### Changed
- chrono/CLAUDE.md references shared/lifecycle.md and Topology B chaser
- chrono/operator-setup.md strengthens cross-Lead routing examples
- shared/dispatch-toolkit.sh reflects actually-installed MCPs (no vaporware)
- 5 LEAD.md and 5 memory.md files updated

### Fixed
- Specialists no longer default to WebFetch when identity catalogs alternatives
- Coding Lead now dispatches via specialist roster instead of solo-handling
- Effort flags explicit per pane
- Security Lead MCP errors investigated and resolved (see _state/incident-2026-05-02-security-mcp.md)

### Removed
- N/A (no v1.0 features removed)

## [1.0.0] - initial squad
Initial squad bring-up.
```

**Verification gate:** file exists; entry mentions every Item 1-16 deliverable that actually shipped.

### Item 16 — `README.md` v1.1 update

**Target:** `README.md` at vault root

**Change:**
- Add v1.1 section linking CHANGELOG
- Update tool/feature catalog summary
- Add links to `shared/lifecycle.md` and `shared/api-catalog.md`

**Verification gate:** README mentions v1.1 + links resolve.

## Build sequence (revised per reviewer feedback)

| Step | Item | Dependency / rationale |
|------|------|--------------------------|
| 1a | Item 0 — Capability inventory | FIRST — everything that cites flags/MCPs depends on this |
| 1b | Item 14 — Security MCP debug | Parallel with 1a — independent |
| 2 | Item 7 — `shared/api-catalog.md` | After Item 0 (cites verified entries) |
| 2b | Run within-v1.1 research tasks (Jules/Flow/NotebookLM/Antigravity/xAI/DeepSeek) | Flips `needs-research` entries to verified yes/no in api-catalog |
| 3 | Item 6 — `shared/lifecycle.md` | Parallel with 2 |
| 4 | Item 5 — `bin/launch-squad.sh` flags | After Item 0 (uses verified flags); test in disposable session before commit |
| 5 | Item 8 — `shared/dispatch-toolkit.sh` reality-check | After Item 0 + Item 7 |
| 6 | Item 1b — `bin/upgrade-specialists.py` | After Item 7 (script reads catalog for pre-fill) |
| 7 | Item 2 — Lead briefs (5 files) | After Items 6 + 7 |
| 8 | Item 1 — Specialist tool-awareness pass via Item 1b | After Item 2 |
| 9 | Item 2b — Schema validator | After Item 1 (validates result) |
| 10 | Item 3 — Lead memory.md notes | After Item 2 |
| 11 | Item 9 — `chrono/operator-setup.md` clarifications | Parallel |
| 12 | Item 9b — Topology B chaser logic | Parallel with 11 |
| 13 | Item 4 — Coordinator brain updates | After Items 6 + 7 + 9b |
| 14 | Item 12 — Two skill REMAKEs | Parallel |
| 15 | Item 10 — Four log streams (with caveats) | After core fixes; instrumentation |
| 16 | Item 11 — Pattern tracker logic | After Item 10 |
| 17 | Item 5b — Token-spend guardrail | After Item 5 launch |
| 18 | Item 15 — `CHANGELOG.md` | LAST — documents shipped reality |
| 19 | Item 16 — `README.md` update | After 18 |

**Realistic timeline:** ~3-4 days if dispatched as Project Mode work to operational squad. Item 1 (39 specialist files) is the bulk; Item 1b automation reduces this dramatically.

## Verification gates — STRENGTHENED per reviewer feedback

A v1.1 build is **done** when ALL of these pass:

1. ✅ `_state/capability-inventory-2026-05-02.md` exists with verified entries
2. ✅ Schema validator (Item 2b) returns clean on all 39 specialist files (proves accurate content, not just headings)
3. ✅ All 5 LEAD.md files have v1.1 sections AND only cite verified MCPs/features per Item 0 inventory
4. ✅ Disposable tmux launch shows 6/6 panes healthy with new effort/thinking flags (proves launch correctness)
5. ✅ `[ -f shared/lifecycle.md ] && [ -f shared/api-catalog.md ]` returns 0 exit
6. ✅ `bash bin/dispatch-toolkit-verify.sh` reports zero PER-PANE mismatches (not just global)
7. ✅ `_state/specialist-log.jsonl` shows multi-entry traffic within 24h of squad use; `_state/errors.jsonl` aggregator runs nightly successfully
8. ✅ **Coding-Lead delegation smoke test** (per Codex): operator dispatches a task requiring backend + test + reviewer; verify Coding Lead dispatches at least 2 specialists from `_state/specialist-log.jsonl` AND specialists actually call named MCPs (semgrep evidence in tmux-logs, not just final-text claim of usage)
9. ✅ **Security→Research direct-with-CC smoke test** (per Codex): operator dispatches bounty target task; verify mailbox artifacts: `departments/security/inbox/<task>.md` AND `departments/research/inbox/<task>.md` with `from_lead: security` AND `chrono/inbox/<cc-summary>.md` AND final synthesis in `departments/security/outbox/`
10. ✅ Security MCP incident report exists with all four required fields (Item 14)
11. ✅ vibecoding-check passes on all changed files: `bash bin/vibecoding-check.sh` returns exit 0 over the changed file list

## Rollback plan — STRENGTHENED per reviewer feedback

v1.1 changes are nearly all additive (new sections, new files). If something breaks:

| Failure mode | Rollback (preserves _state, mailboxes, operator edits) |
|---------------|---------------------------------------------------------|
| Pane fails to launch with new effort flags | `git restore --source=v1.0-pre-1.1 -- bin/launch-squad.sh` (file-scoped, preserves rest) |
| Specialist dispatch breaks | `git restore --source=v1.0-pre-1.1 -- departments/<lead>/specialists/<file>.md` (per-file scoped) |
| New log writes spam disk | Stop writers (`bin/specialist-log-stop.sh`); existing logs untouched |
| Pattern tracker writes garbage | Disable tracker; existing weekly briefs unaffected |
| Compaction at phase boundaries breaks Lead state | Disable compaction trigger; Leads accumulate context as in v1.0 |

**Critical:** rollback uses `git restore --source=<tag> -- <files>`, NEVER `git checkout` over working tree. `_state/` (mailboxes, dispatch logs, runs) is excluded from version control or explicitly preserved. Operator's in-progress mailbox state always survives rollback.

Git tag at start: `git tag v1.0-pre-1.1` before any v1.1 edits.

## Within-v1.1 research backlog (opportunistic — does NOT block ship)

**Per Codex re-review constraint:** these features are claimed in `shared/api-catalog.md` but need verification before specialist-file citation. They run **opportunistically** during the v1.1 build window. **They do NOT block v1.1 ship gates.** If a research task hasn't completed by the time the 11 verification gates pass, v1.1 ships with that entry still flagged `needs-research`. The catalog absorbs research-backlog progress as a continuous background activity.

`harness-optimizer` runs each as a sub-task during v1.1 build:

- **Jules** (Google coding agent) — what is it, how does it integrate with squad, can we use it from Content Lead?
- **Flow** (Google video tool) — capabilities for content-creator
- **NotebookLM** — research/large-context-analyst integration paths
- **Antigravity** (Google IDE-agent) — alt CLI for Coding? Or peer tool?
- **xAI Grok-X** — API setup, integration via secrets.zsh; usage paths for scout (breach surveillance) + content-creator (X trends)
- **DeepSeek V4** — API setup; addition to T1/T2 fanout pool
- **Anthropic /ultrareview** — verify command behavior in Claude Code CLI
- **Gemini Nano Banana / Veo / Imagen** — verify access paths via gemini CLI

Each produces a sub-report at `_state/research-{topic}-2026-05-02.md`. Catalog entries flip from `needs-research` to verified yes/no based on findings. None of these block v1.1 specialist authoring (specialists ignore `needs-research` entries until verified).

## References / prior art

- **Codex GPT-5.5 review (2026-05-02)** — caught: vaporware risk in unverified flag/feature claims, Item 11 over-engineering, scope creep in api-catalog breadth, Gates 1-6 weak, rollback ambiguity, token-spend surprise risk
- **Gemini 3.1 review (2026-05-02)** — caught: Topology B whispering risk (Chrono blind to peer comms), 39-file manual edit inconsistency risk (now automated via 1b), MCP-protocol logging blind spot (now caveat-noted), schema validation needed
- **Trail of Bits skills** ([github.com/trailofbits/skills](https://github.com/trailofbits/skills)) — already partially mined into local catalog
- **Smart-contract checklists** — [tamjid0x01](https://github.com/tamjid0x01/SmartContracts-audit-checklist) + [cryptofinlabs](https://github.com/cryptofinlabs/audit-checklist)
- **HexStrike AI** ([github.com/0x4m4/hexstrike-ai](https://github.com/0x4m4/hexstrike-ai)) — does NOT bundle binaries; supplements Colima rather than replaces
- **Anthropic Claude Design** — web tool for designer specialist
- **Awesome ecosystem catalogs** — awesome-claude-code, awesome-codex-cli, awesome-gemini-cli, awesome-kimi-cli, awesome-mcp-servers, antigravity-awesome-skills (1,400+ cross-CLI)

## Acknowledgments

- **Operator (Matt)** — caught v2 redesign drift multiple times; pulled spec back to fix-not-rebuild scope; insisted "no v1.2 deferrals" forcing this revision to ship coherently in one cycle
- **Codex GPT-5.5** — verified-capability-inventory recommendation; per-pane MCP verification; rollback scoping; Coding Lead delegation smoke test design
- **Gemini 3.1** — automation-vs-manual specialist pass; Topology B chaser; MCP-protocol-logging caveat realism

---

*Spec status: approved-for-build (revision 2, post-multi-model review). Build sequence ordered with capability inventory as foundational step. Verification gates strengthened. Rollback plan scoped to file-level restores. v1.1.0 target version.*
