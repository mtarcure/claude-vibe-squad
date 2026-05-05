# Capability Manifest: chrono-research-tools

Status: draft, optional-enhanced runtime, required for Research Mode quality when configured
Owner: research namespace
Canonical current surface: `shared/api-catalog.md`, `chrono-research-arsenal MCP`
Old plugin source: old `research` plugin wrappers plus current `chrono-research-arsenal`.

## Role Contract

`chrono-research-tools` is the shared research provider surface: web/news/X/search, source discovery, arXiv, GitHub/source lookup, crawler/extraction integrations, and provider routing.

## Preserved Current Behavior

- Research uses named MCP/tooling before fallback.
- Public docs distinguish required core from optional provider-enhanced tools.
- Paid/cost-bearing providers need approval or explicit setup.

## Old Plugin Capabilities To Preserve

From old research plugin:

- `web_search`
- `web_fetch`
- `grep_sources`
- `kg_recall`
- `smart_research`
- `get_playbook`
- `consult_peer`

## Required Tools

- At least one web/source search path.
- Specific URL/page read path.
- Source citation/provenance path.
- Local source grep path.

## Optional Tools

- Perplexity, Brave, Apify, Serper, xAI/Grok.
- Firecrawl/deep crawl.
- ArXiv/GitHub/Reddit/HN routes.

## MCPs

- `chrono-research-arsenal`
- `chrono-kg`
- `chrono-catalog`

## Skills

- `find-sources`
- `cite-properly`
- `source-triangulation`
- `research-integrity-gate`

## Adaptive Operating Mode

Prefer primary/source-specific search, cite every claim, gracefully degrade when optional engines are missing, and report missing provider/auth rather than pretending coverage.

## Output Contract

- `providers_available`
- `providers_used`
- `sources`
- `missing_tools`
- `cost_approval_required`

## KG And Memory Behavior

- Record provider failures and useful source paths.
- Do not store paid API keys or private results publicly.

## Safety Boundaries

- No paid crawls without approval.
- No fabricated citations.
- No ToS-violating scraping.

## Live Dispatch Proof

Research live proof must use at least one configured provider or report structured missing-provider status with fallback.

## Public/Private Disposition

Public: provider docs and optional setup. Private: keys, paid account state, private source packs.

## Cleanup Disposition

Do not remove research provider docs/wrappers until Research Mode proof covers source discovery and fallback behavior.
