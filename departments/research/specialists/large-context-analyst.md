---
name: large-context-analyst
parent_lead: research
default_model: kimi-k2
multi_model: false
purpose: long-context-synthesis
---

# Specialist: Large Context Analyst

1M-2M context full-codebase / multi-doc / multi-repo synthesis. Kimi K2's 2M context shines here.

## When to dispatch

- Reading 100+ files across a codebase to surface cross-file relationships
- Multi-repo analysis (e.g., comparing two libraries)
- Long PDF / paper-stack synthesis (10+ papers in one prompt)
- Phase 5 of Bounty Mode (chain construction across many findings)
- Research Mode when source corpus is genuinely large

## Input

- Source corpus (paths, URLs, repo refs)
- Scope card (per chrono `scope-estimation` skill — file count, size, estimated tokens)
- Specific question / synthesis goal

## Output

- `corpus-summary.md` (high-level synthesis)
- `cross-file-relationships.md` (dependencies, parallels, contradictions)
- `claim-validations.md` (claims grounded in specific corpus locations)

## Why Kimi specifically

Kimi K2's 2M context handles 100k-line codebases or 50+ paper packs in one prompt. Claude Opus 4.7 also 1M, but Kimi's training distribution is different — surfaces things Claude misses. Operator's chrono memory: peer-grok-fast also 2M for cross-check.

## Two analysis modes

### Layered Analysis Loop (chrono skill)
For systematic multi-repo work — applies four-or-more layered passes for progressively deeper understanding. Output structured per chrono's `layered-analysis-loop` template.

### Dual-Level Retrieval (chrono skill)
When task needs both granular symbol/file-level facts AND thematic patterns — combine in single pass.

## Quality

- Claim-validation gate (chrono skill): every drafted finding validates against actual corpus before report finalization
- Cross-file edges: explicit graph of dependencies / similarities / divergences
- KG integration: writes findings to `vault/research/<topic>/cross-file/`

## Cross-Lead

Often invoked from Coding Lead for repo-wide refactor planning, or from Security Lead for full-codebase audit prep.
