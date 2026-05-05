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
# `chrono-research-arsenal` is a research-lane wrapper. Current live tools are
# `arxiv_search` and `xai_search`; Perplexity/Brave/Serper/Apify are future
# routes until the catalog verifies them. Other namespaces route external
# research through the research namespace instead of inventing tool names.
#
# Usage:  bash shared/dispatch-toolkit.sh <compatibility-namespace> <to-model>

set -euo pipefail

NAMESPACE="${1:-}"
TO_MODEL="${2:-unknown}"

cat <<EOF

## Dispatch Context

- Source mailbox namespace: \`${NAMESPACE}\`
- Executing model lane: \`${TO_MODEL}\`

EOF

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

**Routing reminder:** for OSINT / vendor research / library exploration, ask Chrono for a research-namespace dispatch. The live `chrono-research-arsenal` wrapper currently exposes `arxiv_search` and `xai_search`; do not ask for Perplexity/Brave/Serper/Apify tool names until `shared/api-catalog.md` verifies them.

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

**Bounty platform context:**
- `HACKERONE_API_TOKEN` available in env for direct REST API queries
- 4 other platforms (Bugcrowd, Intigriti, HackenProof, Code4rena) are browser-only; use Playwright CDP attach
- Operator's allowed platforms ONLY: HackerOne, Bugcrowd, Intigriti, HackenProof, Code4rena. Do NOT suggest Cantina, Immunefi, Sherlock, YesWeHack.

**Routing reminder:** for OSINT / vendor research that doesn't fit `scout`'s platform-intel scope, ask Chrono for a research-namespace dispatch. The live research wrapper currently exposes `arxiv_search` and `xai_search`; do not ask for unverified Perplexity/Brave/Serper/Apify tool names.

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

**Native Gemini grounding:** `gemini-3.1-pro-preview` carries Google Search grounding implicitly — use it for fact-finding / citation hunting in-session. (No `chrono-research-arsenal` on the gemini pane by design — Hybrid Path A relies on native grounding for content-pane research.)

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

**Live research MCP tools:** `arxiv_search` and `xai_search`. Perplexity, Brave, Serper, and Apify are not wired in the current wrapper. If a task asks for an unlisted tool, report `capability_gap` and use the task-approved fallback or model-native search.

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

GPT/Codex lane is expected to have repo shell commands, file edits, tests, `chrono-vault`, `chrono-kg`, `chrono-obsidian`, `chrono-catalog`, `chrono-content-engineer` when relevant, and `sequential-thinking`.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    claude)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Claude lane is expected to have `chrono-vault`, `chrono-kg`, `chrono-obsidian`, `chrono-catalog`, and local shell where allowed by the task. Context7 and sequential thinking are optional conveniences only when the live Claude runtime exposes them. Use Playwright/CDP only when the packet explicitly allows browser work.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    gemini)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Gemini lane is expected to have native Gemini grounding, `chrono-content-engineer`, `chrono-vault`, `chrono-kg`, `chrono-obsidian`, `chrono-catalog`, `sequential-thinking`, and media/design tools when the packet allows them. `chrono-content-engineer` currently exposes wrapper tools such as `generate_image`, `generate_video`, and `generate_audio`; ElevenLabs/Higgsfield child tool names are not available in this lane unless the live schema exposes them.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    kimi)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Kimi lane is expected to have `chrono-research-arsenal`, `chrono-vault`, `chrono-kg`, `chrono-obsidian`, `chrono-catalog`, `chrono-content-engineer` when relevant, and `sequential-thinking`. The current research wrapper exposes `arxiv_search` and `xai_search`; Perplexity/Brave/Serper/Apify tool names are not wired until verified in the catalog.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
esac

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
operator review. An auto-snapshot was taken before this task was dispatched —
the tree is recoverable regardless, but the constraint still applies.
NODELETE
