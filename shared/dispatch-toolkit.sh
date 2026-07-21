#!/bin/bash
# dispatch-toolkit.sh — emit source-namespace context and executing model-lane
# tool expectations as a markdown snippet that send-task.sh appends to every
# dispatched task.
#
# This implements the rule from chrono memory:
#   "every brief must enumerate chrono MCPs; voices default to WebFetch when
#    brief omits them."
#
# Without this, dispatched model lanes default to whatever is first in their
# context. With this, every lane sees the source namespace roster, the expected
# model-lane surface, and the rule to verify live tool availability before use.
#
# Per-pane MCP enumeration is sourced from:
#   _state/capability-inventory-2026-05-02.md (verified per-pane install state)
#   _state/incident-2026-05-03-claude-mcp-tilde.md (post-fix Claude MCP set)
#   gemini mcp list -d (post-Hybrid-Path-A install on 2026-05-03)
#
# Provider availability changes over time, so the status block below is rendered
# from the canonical skill/tool registry on every dispatch.
#
# Usage:  bash shared/dispatch-toolkit.sh <compatibility-namespace> <to-model>

set -euo pipefail

NAMESPACE="${1:-}"
TO_MODEL="${2:-unknown}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL_REGISTRY="${REPO_ROOT}/shared/registries/skill-tool-registry.tsv"

emit_registry_research_guidance() {
    python3 - "$TOOL_REGISTRY" <<'PYEOF'
import csv
import sys
from pathlib import Path

registry = Path(sys.argv[1])
wanted = ("Brave Search", "Apify", "Serper")
with registry.open(encoding="utf-8", newline="") as handle:
    rows = {row["name"]: row for row in csv.DictReader(handle, delimiter="\t")}
missing = [name for name in wanted if name not in rows]
if missing:
    raise SystemExit(f"dispatch registry guidance missing rows: {', '.join(missing)}")
rendered = "; ".join(
    f"`{name}` ({rows[name]['lanes']} · {rows[name]['verified_state']} · {rows[name]['cost_tier']})"
    for name in wanted
)
print("## Registry-derived research add-ons\n")
print(rendered + ".")
print("\nRegistry `yes` records availability, not permission to spend. Apply the row's invocation constraints and any task budget/authorization gate before use.")
PYEOF
}

cat <<EOF

## Dispatch Context

- Source mailbox namespace: \`${NAMESPACE}\`
- Executing model lane: \`${TO_MODEL}\`

EOF

emit_registry_research_guidance

case "${NAMESPACE}" in
    coding)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `backend-engineer` · APIs, async pipelines, server-side
- `frontend-engineer` · React/Vue/Svelte, Tailwind, perf
- `ui-engineer` · component design, design-token alignment
- `code-reviewer` · spec compliance, severity ladder, adversarial review
- `test-engineer` · unit + integration test design
- `qa-tester` · property-based tests, mutation campaigns, fuzz harnesses
- `devops-engineer` · Docker, K8s, Terraform, CI/CD
- `performance-optimizer` · benchmark, profile, flamegraph triage
- `refactor-cleaner` · AST rewrites, dead-code elimination
- `ai-engineer` · LLM applications, RAG, agent tools
- `smart-contract-engineer` · EVM/Solana audits
- `scraping-engineer` · browser-based extraction, stealth
- `systems-engineer` · cross-arch builds, NUMA/SIMD
- `e2e-runner` · Playwright suites, visual diffs, flaky-test hunting

**Routing reminder:** for OSINT / vendor research / library exploration, ask Chrono for a research-namespace dispatch. Use only tools supported by the registry-derived status block and verified in the current runtime.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless the packet explicitly asks for cross-lane review or parallel work.
EOF
        ;;
    security)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `scout` · bounty target selection, program reconnaissance, scope analysis, platform intel
- `security-analyst` · SAST, supply-chain audits, code review for security
- `threat-modeler` · STRIDE, attack-tree, risk ranking
- `exploit-developer` · PoC construction, payload crafting, sandbox-safe reproduction
- `impact-validator` · CVSS v4 scoring, sanity check on findings, dedup vs CVE/known-issue DBs
- `privacy-steward` · PII / data-flow concerns, GDPR/CCPA review

**Bounty program context:**
- A bounty-program API token may be available in env for direct REST API queries on API-enabled programs
- Other authorized programs are browser-only; attach via the persistent CDP Chrome (see `shared/lifecycle.md`)
- Only engage programs the operator has explicitly authorized; do not suggest programs outside that authorized set

**Routing reminder:** for OSINT / vendor research that doesn't fit `scout`'s platform-intel scope, ask Chrono for a research-namespace dispatch. Use only tools supported by the registry-derived status block and verified in the current runtime.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    content)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `writer` · prose drafting, brand-voice content
- `technical-writer` · changelogs, ADRs, post-spec handoffs
- `editor` · pass for clarity, length, voice
- `designer` · design tokens, Figma fidelity, a11y
- `brand-voice` · operator voice consistency check
- `video-editor` · video trim/edit/captions

**Research tools:** `gemini-3.1-pro-preview` carries native Google Search grounding. For other research tools, use the registry-derived status block and verify the current runtime.

**Routing reminder:** for deeper multi-source synthesis beyond a quick grounded check, hand off to research namespace.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    sysmgmt)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `doctor` · system health checks, CLI auth, MCP reachability
- `dreamer` · KG synthesis, pattern observation
- `archiver` · cold-storage policies, run lifecycle
- `memory-curator` · KG hygiene, contradiction detection, stale-knowledge purge
- `knowledge-librarian` · vault organization, link integrity
- `harness-optimizer` · audit the squad's own configuration
- `finance-analyst` · subscription cost tracking
- `personal-ops` · operator's daily routines + reminders
- `loop-operator` · long-running iteration with checkpoints + stall detection

**Routing reminder:** for any external research (CLI changelogs, vendor docs, frontier-tool freshness checks), hand off to research namespace — they own `chrono-research-arsenal`.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    research)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `research` · deep investigation, multi-source synthesis, claim validation
- `synthesizer` · aggregate parallel findings, preserve outliers
- `large-context-analyst` · 1M-2M context full-codebase / multi-doc analysis
- `scraper` · structured data extraction from web pages
- `learner` · study plans, drills, spaced repetition, reading ladders
- `data-extraction-engineer` · PDF parsing, table extraction, dataset wrangling

**This namespace is the squad's web-research home.** Other namespaces route research tasks here; you own the live `chrono-research-arsenal` wrapper.

**Research capability rule:** use the registry-derived status block, then verify the current runtime with a live probe. Treat absence from the callable runtime schema as an availability error, declare `capability_gap`, and use the approved fallback.

**NOT YOUR DOMAIN:** Bounty target selection (that's security namespace `scout`). Vulnerability discovery (that's security namespace `security-analyst`). Implementation work (that's coding namespace specialists).

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    *)
        echo ""  # unknown namespace, no toolkit injection
        ;;
esac

case "${TO_MODEL}" in
    gpt-codex)
        cat <<'EOF'

## Expected Model Lane Tool Surface

GPT/Codex lane is expected to have repo shell commands, file edits, tests, `chrono-research-arsenal`, `chrono-vault`, `chrono-kg`, `chrono-obsidian`, `chrono-media-studio` when relevant, and `sequential-thinking`.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    claude)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Claude lane is expected to have `chrono-research-arsenal`, `chrono-vault`, `chrono-kg`, `chrono-obsidian`, and local shell where allowed by the task. Context7 and sequential thinking are optional conveniences only when the live Claude runtime exposes them. Use Playwright/CDP only when the packet explicitly allows browser work.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    gemini)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Gemini lane is expected to have native Gemini grounding, `chrono-research-arsenal`, `chrono-media-studio`, `chrono-vault`, `chrono-kg`, `chrono-obsidian`, `sequential-thinking`, and media/design tools when the packet allows them. `chrono-media-studio` currently exposes wrapper tools such as `generate_image`, `generate_video`, and `generate_audio`; ElevenLabs/Higgsfield child tool names are not available in this lane unless the live schema exposes them.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    kimi)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Kimi lane is expected to have `chrono-research-arsenal`, `chrono-vault`, `chrono-kg`, `chrono-obsidian`, `chrono-media-studio` when relevant, and `sequential-thinking`. Use the registry-derived status block for research add-ons and verify the current runtime before invocation.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
esac

# ── completion contract: lanes emit BOTH return_artifact AND outbox envelope ──
# Appended to every dispatched brief. bin/outbox-watcher.sh + registry_reconciler
# key on departments/<ns>/outbox/<id>-response.md; without it finished work sits
# in-flight until Chrono hand-reconciles. This is the primary path; the
# reconciler's work-done-no-envelope flag is only the backstop.

cat <<'COMPLETION_EOF'

---

## Completion contract — write BOTH outputs when you finish

On finishing this task you MUST write TWO files:

1. **Your work** → the `return_artifact` path in the packet frontmatter.
2. **The outbox completion envelope** → `departments/<compatibility_namespace>/outbox/<id>-response.md`, where `<id>` is this packet's `id` and `<compatibility_namespace>` is the department mailbox this packet was read from (`departments/<X>/inbox/<id>.md` → use `<X>`; authoritative even when the packet omits a `compatibility_namespace` field). The live `bin/outbox-watcher.sh` keys on this envelope to auto-reconcile the registry and surface your result to Chrono. Without it, finished work sits `in-flight` until it is hand-reconciled.

The envelope is markdown — this frontmatter, then a short summary body (its first paragraph is surfaced as the summary):

```
---
id: <id>-response
in_response_to: <id>
from: <lane>          # gpt-codex | claude | gemini | kimi
to: chrono
type: RESULT
status: complete      # complete | needs_review | blocked
return_artifact: <the return_artifact path>
---

<one-paragraph summary of the outcome.>
```

- `status` must be `complete`, `needs_review`, or `blocked` (the reconciler canonicalizes `completed`→`complete`). Use `needs_review` when the packet sets `mandatory_review: true`; use `blocked` if you could not finish.
- The reconciler matches on the `<id>-response.md` filename and reads `status` plus the summary body; the remaining fields are provenance.
- **Panel / fan-out MEMBERS do NOT write an envelope** — only the panel coordinator writes the single outbox envelope for the parent task.
COMPLETION_EOF

# ── SPEC 1.5 ITEM 4: hard no-delete rule ─────────────────────────────────────
# Appended to every dispatched brief regardless of namespace.
# Prevents destructive ops by dispatched agents without operator approval.

cat <<'NODELETE'

---

<!-- spec-1.5-no-delete-rule: do not remove this block -->
## Hard constraint: no file deletion

You may NOT delete existing files in your write scope or working directory
without an explicit operator-approved instruction in this task's frontmatter.

**What counts as a destructive op (requires operator approval):**
- `rm`, `unlink`, or `os.remove` on any tracked or untracked file
- Overwriting a file wholesale where diff would show net loss of lines
- Moving a file out of the repo tree (equivalent to deletion)
- Running `git clean -f` or `git checkout -- .`

**If your task appears to require deletion:**
1. Do NOT delete. Pause.
2. Write to your outbox with `status: needs_human`
3. Include: which files, why deletion seems required, proposed alternative
4. Wait for operator approval before proceeding.

This constraint fires even if files look like drafts, temp files, or
prior-run artifacts. The operator decides what's ephemeral.

Violation of this rule is treated as a task failure requiring immediate
operator review. This constraint applies regardless of repository state or
available recovery mechanisms.
NODELETE
