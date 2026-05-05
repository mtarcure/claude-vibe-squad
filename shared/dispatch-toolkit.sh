#!/bin/bash
# dispatch-toolkit.sh — emit the per-namespace specialist + MCP roster as a
# markdown snippet that send-task.sh prepends to every dispatched task.
#
# This implements the rule from chrono memory:
#   "every brief must enumerate chrono MCPs; voices default to WebFetch when
#    brief omits them."
#
# Without this, dispatched model lanes default to whatever is first in their
# context (usually WebFetch). With this, every lane sees the right toolkit on
# every dispatch and can pick the right tool.
#
# Per-pane MCP enumeration is sourced from:
#   _state/capability-inventory-2026-05-02.md (verified per-pane install state)
#   _state/incident-2026-05-03-claude-mcp-tilde.md (post-fix Claude MCP set)
#   gemini mcp list -d (post-Hybrid-Path-A install on 2026-05-03)
#
# `chrono-research-arsenal` is intentionally listed ONLY in the research section.
# The research namespace owns multi-source web research; other namespaces route research
# through Research, not directly. Eliminates the "every lane reaches for
# perplexity" tool-collision noise.
#
# Usage:  bash shared/dispatch-toolkit.sh <source-namespace>

set -euo pipefail

LEAD="${1:-}"
case "${LEAD}" in
    coding)
        cat <<'EOF'

## Tools available for this task

**Specialists you should dispatch (don't do their work yourself — fan out):**
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

**MCPs verified installed in this pane (codex CLI per capability-inventory-2026-05-02):**
- `chrono-vault` — KG read/write for project memory
- `chrono-kg` — KG namespace direct access
- `chrono-obsidian` — Obsidian vault REST API
- `chrono-catalog` — capability/MCP catalog queries
- `chrono-content-engineer` — only when generating content artifacts (rare for coding)
- `sequential-thinking` — multi-step reasoning helper
- Native Bash for git, npm, cargo, docker, etc.

**Routing reminder:** for OSINT / vendor research / library exploration, ask Chrono for a research-namespace dispatch — that namespace owns `chrono-research-arsenal` (Perplexity / Brave / Serper / Apify). Don't reach for WebFetch yourself; route the research task.

**Required:** Dispatch to at least one specialist before drafting your own response. If none of the above fits, surface to operator instead of inventing a freeform answer.
EOF
        ;;
    security)
        cat <<'EOF'

## Tools available for this task

**Specialists you should dispatch (don't do their work yourself — fan out):**
- `scout` · bounty target selection, program reconnaissance, scope analysis, platform intel
- `security-analyst` · SAST, supply-chain audits, code review for security
- `threat-modeler` · STRIDE, attack-tree, risk ranking
- `exploit-developer` · PoC construction, payload crafting, sandbox-safe reproduction
- `impact-validator` · CVSS v4 scoring, sanity check on findings, dedup vs CVE/known-issue DBs
- `privacy-steward` · PII / data-flow concerns, GDPR/CCPA review

**MCPs verified installed in this pane (claude CLI, post-2026-05-03 tilde fix):**
- `chrono-vault` — KG read/write for finding/program memory
- `chrono-kg` — KG namespace direct access
- `chrono-obsidian` — Obsidian vault REST API
- `chrono-catalog` — capability/MCP catalog queries
- `playwright` (CDP) — attach to operator's persistent Chrome at port 9222 for bounty platform navigation. Tabs already 2FA'd: HackerOne, Bugcrowd, Intigriti, HackenProof, Code4rena
- `chrome-devtools` — DOM-level CDP attach for read-only inspection
- `context7` — library/API documentation lookup
- `sequential-thinking` — multi-step reasoning helper

**Bounty platform context:**
- `HACKERONE_API_TOKEN` available in env for direct REST API queries
- 4 other platforms (Bugcrowd, Intigriti, HackenProof, Code4rena) are browser-only; use Playwright CDP attach
- Operator's allowed platforms ONLY: HackerOne, Bugcrowd, Intigriti, HackenProof, Code4rena. Do NOT suggest Cantina, Immunefi, Sherlock, YesWeHack.

**Routing reminder:** for OSINT / vendor research that doesn't fit `scout`'s platform-intel scope, ask Chrono for a research-namespace dispatch — that namespace owns `chrono-research-arsenal` (Perplexity for synthesis, Brave/Serper for raw search). Don't WebFetch directly.

**Required:** Dispatch to at least one specialist before drafting your own response. For "find a bounty" tasks, that's `scout`. For "audit this code" tasks, that's `security-analyst`. For "model the threats here" tasks, that's `threat-modeler`.
EOF
        ;;
    content)
        cat <<'EOF'

## Tools available for this task

**Specialists you should dispatch:**
- `writer` · prose drafting, brand-voice content
- `technical-writer` · changelogs, ADRs, post-spec handoffs
- `editor` · pass for clarity, length, voice
- `designer` · design tokens, Figma fidelity, a11y
- `brand-voice` · operator voice consistency check
- `video-editor` · video trim/edit/captions

**MCPs verified installed in this pane (gemini CLI, post-Hybrid-Path-A install 2026-05-03):**
- `chrono-content-engineer` — ElevenLabs Scribe (transcription), text-to-speech, image generation, music composition
- `chrono-vault` — brand-voice memory, prior content recall
- `chrono-kg` — KG namespace direct access
- `chrono-obsidian` — direct vault REST API for content output
- `chrono-catalog` — capability/MCP catalog queries
- `sequential-thinking` — multi-step reasoning helper
- `stitch` (gemini extension) — Figma/UI-design generation; natural-language commands inside the gemini session

**Native Gemini grounding:** `gemini-3.1-pro-preview` carries Google Search grounding implicitly — use it for fact-finding / citation hunting in-session. (No `chrono-research-arsenal` on the gemini pane by design — Hybrid Path A relies on native grounding for content-pane research.)

**Routing reminder:** for deeper multi-source synthesis beyond a quick grounded check, hand off to research namespace.

**Required:** Dispatch to at least one specialist. For drafts, that's `writer` or `technical-writer`. For final pass, `editor`. For visuals, `designer` + `chrono-content-engineer`.
EOF
        ;;
    sysmgmt)
        cat <<'EOF'

## Tools available for this task

**Specialists you should dispatch:**
- `doctor` · system health checks, CLI auth, MCP reachability
- `dreamer` · KG synthesis, pattern observation
- `archiver` · cold-storage policies, run lifecycle
- `memory-curator` · KG hygiene, contradiction detection, stale-knowledge purge
- `knowledge-librarian` · vault organization, link integrity
- `harness-optimizer` · audit the squad's own configuration
- `finance-analyst` · subscription cost tracking
- `personal-ops` · operator's daily routines + reminders
- `loop-operator` · long-running iteration with checkpoints + stall detection

**MCPs verified installed in this pane (claude CLI, post-2026-05-03 tilde fix):**
- `chrono-vault` — for any state read/write
- `chrono-kg` — KG namespace direct access
- `chrono-obsidian` — direct vault REST API
- `chrono-catalog` — capability/MCP catalog queries
- `context7` — library/API documentation lookup
- `sequential-thinking` — multi-step reasoning helper
- Native Bash for `pmset`, `df`, `launchctl`, etc.

**Routing reminder:** for any external research (CLI changelogs, vendor docs, frontier-tool freshness checks), hand off to research namespace — they own `chrono-research-arsenal`.

**Required:** Dispatch to at least one specialist before drafting your own response. For system health: `doctor`. For KG operations: `memory-curator` or `knowledge-librarian`. For squad configuration audits: `harness-optimizer`.
EOF
        ;;
    research)
        cat <<'EOF'

## Tools available for this task

**Specialists you should dispatch:**
- `research` · deep investigation, multi-source synthesis, claim validation
- `synthesizer` · aggregate parallel findings, preserve outliers
- `large-context-analyst` · 1M-2M context full-codebase / multi-doc analysis
- `scraper` · structured data extraction from web pages
- `learner` · study plans, drills, spaced repetition, reading ladders
- `data-extraction-engineer` · PDF parsing, table extraction, dataset wrangling

**MCPs verified installed in this pane (kimi CLI per capability-inventory-2026-05-02):**
- `chrono-research-arsenal` — **PRIMARY for web research.** Perplexity for synthesis, Brave/Serper for raw search, Apify for scraping. ALWAYS prefer over WebFetch.
- `chrono-vault` — KG for cross-domain pattern recall
- `chrono-kg` — KG namespace direct access
- `chrono-obsidian` — vault navigation for prior research
- `chrono-catalog` — capability/MCP catalog queries
- `chrono-content-engineer` — only when research output needs media artifacts
- `sequential-thinking` — multi-step reasoning helper

**This namespace is the squad's web-research home.** Other namespaces route research tasks here; you own `chrono-research-arsenal`.

**WebFetch is a fallback ONLY** — use it when chrono-research-arsenal can't reach a specific URL or for quick single-page reads. Never as your primary research tool.

**NOT YOUR DOMAIN:** Bounty target selection (that's Security `scout`). Vulnerability discovery (that's Security `security-analyst`). Implementation work (that's Coding's specialists).

**Required:** Dispatch to at least one specialist. For OSINT / multi-source: `research`. For synthesis: `synthesizer`. For long docs: `large-context-analyst`.
EOF
        ;;
    *)
        echo ""  # unknown namespace, no toolkit injection
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
