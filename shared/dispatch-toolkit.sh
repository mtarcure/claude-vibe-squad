#!/bin/bash
# dispatch-toolkit.sh — emit the per-Lead specialist + MCP roster as a
# markdown snippet that send-task.sh prepends to every dispatched task.
#
# This implements the rule from chrono memory:
#   "every brief must enumerate chrono MCPs; voices default to WebFetch when
#    brief omits them."
#
# Without this, dispatched Leads default to whatever's first in their head
# (usually WebFetch). With this, every Lead sees the full toolkit on every
# dispatch and can pick the right tool.
#
# Usage:  bash shared/dispatch-toolkit.sh <lead-name>

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

**MCPs you should prefer over generic WebFetch / Bash:**
- `chrono-vault` — KG read/write for project memory
- `chrono-research-arsenal` — Perplexity / Brave / Serper / Apify (multi-source web research)
- Native Bash for git, npm, cargo, docker, etc.

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

**MCPs you should prefer over generic WebFetch / Bash:**
- `chrono-research-arsenal` — Perplexity (synthesis), Brave/Serper (raw search) — for OSINT, vendor research
- `playwright` (CDP) — attach to operator's persistent Chrome at port 9222 for bounty platform navigation. Tabs already 2FA'd: HackerOne, Bugcrowd, Intigriti, HackenProof, Code4rena
- `chrono-vault` — KG read/write for finding/program memory

**Bounty platform context:**
- `HACKERONE_API_TOKEN` available in env for direct REST API queries
- 4 other platforms (Bugcrowd, Intigriti, HackenProof, Code4rena) are browser-only; use Playwright CDP attach
- Operator's allowed platforms ONLY: HackerOne, Bugcrowd, Intigriti, HackenProof, Code4rena. Do NOT suggest Cantina, Immunefi, Sherlock, YesWeHack.

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

**MCPs you should prefer over generic WebFetch / Bash:**
- `chrono-content-engineer` — ElevenLabs Scribe (transcription), text-to-speech, image generation, music composition
- `chrono-research-arsenal` — for fact-finding, citation hunting
- `chrono-vault` — brand-voice memory, prior content recall

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

**MCPs you should prefer:**
- `chrono-vault` — for any state read/write
- `chrono-obsidian` — direct vault REST API
- Native Bash for `pmset`, `df`, `launchctl`, etc.

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

**MCPs you should prefer over generic WebFetch / Bash:**
- `chrono-research-arsenal` — **PRIMARY for web research.** Perplexity for synthesis, Brave/Serper for raw search, Apify for scraping. ALWAYS prefer over WebFetch.
- `chrono-vault` — KG for cross-domain pattern recall
- `chrono-obsidian` — vault navigation for prior research

**WebFetch is a fallback ONLY** — use it when chrono-research-arsenal can't reach a specific URL or for quick single-page reads. Never as your primary research tool.

**NOT YOUR DOMAIN:** Bounty target selection (that's Security `scout`). Vulnerability discovery (that's Security `security-analyst`). Implementation work (that's Coding's specialists).

**Required:** Dispatch to at least one specialist. For OSINT / multi-source: `research`. For synthesis: `synthesizer`. For long docs: `large-context-analyst`.
EOF
        ;;
    *)
        echo ""  # unknown lead, no toolkit injection
        ;;
esac
