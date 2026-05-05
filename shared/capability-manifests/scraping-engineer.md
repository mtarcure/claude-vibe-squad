# Capability Manifest: scraping-engineer

Status: draft, preserve before cleanup
Owner: coding namespace
Canonical current specialist: `departments/coding/specialists/scraping-engineer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-scraping-engineer/0.1.0/`

## Role Contract

`scraping-engineer` owns browser-based extraction, public HTTP scraping, anti-bot-aware ingestion, binary document conversion, state checkpoints, and extraction logs. It ingests data only; backend handles ETL and AI handles RAG/indexing.

## Preserved Current Behavior

- Checks target authorization, ToS, robots, rate limits, and API availability.
- Uses the operator's running Chrome/CDP session when browser state is needed.
- Stops at CAPTCHA/aggressive bot-detection boundaries unless operator approves a pivot.
- Hands extracted data to backend or AI specialists.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `playwright_scrape`
- `firecrawl_api`
- `trafilatura_extract`
- `ocrmypdf_process`
- `yt_dlp_fetch`
- `mitmproxy_replay`
- `beautiful_soup_parse`
- `html_to_markdown`
- `rate_limit_wrap`
- `captcha_solve_stub`
- `markitdown_convert`

Old shared tools:

- `docker_run`, `docker_compose_up`
- `gh_api`
- `http_get`, `httpx_probe`
- `npm_install`, `pnpm_install`

Preservation rule: cleanup may consolidate wrappers, but the role must retain extraction paths for browser pages, hidden APIs/XHR, clean article text, binary docs, video/audio metadata, and rate-limited polite scraping.

## Required Tools

- Browser automation through Playwright or browser-use/CDP attach.
- HTTP fetch/probe path.
- HTML parsing path, preferably BeautifulSoup/lxml.
- Clean text extraction path, preferably Trafilatura.
- Markdown/binary conversion path, preferably MarkItDown.
- Rate-limit/state persistence path.

## Optional Tools

- Firecrawl API, graceful-degrade when key missing.
- OCRmyPDF for scanned PDFs.
- yt-dlp for video/audio sources.
- mitmproxy flow replay.
- CAPTCHA detector stub. Automated CAPTCHA solving is not a default shipped feature.

## MCPs

- `chrono-kg`: recall target attempts and record extraction findings.
- `chrono-catalog`: skill/tool discovery.
- `chrono-vault` / `chrono-obsidian`: artifact references and scrape logs.
- `chrono-research-arsenal`: research fallback for source/API discovery where available.
- `sequential-thinking`: target strategy and escalation decisions.

## Skills

Current or old skills to keep represented:

- `browser-scrape-pipeline`
- `playwright-stealth-config`
- `scrape-state-persistence`
- `data-normalization`
- `bot-evasion-loop`
- `tos-compliance-check`
- `rate-limit-respect`

## Adaptive Operating Mode

Check for an API first, verify authorization and rate limits, choose simple HTTP when possible, escalate to browser/CDP only when needed, convert/clean extracted data, checkpoint long runs, record the dataset location and integrity hash, then hand off ETL or RAG work.

## Output Contract

Expected return shape:

- `extracted_data.location`
- `format`
- `schema_summary`
- `integrity_hash`
- `api_found`
- `api_spec`
- `escalation_level`
- `kg_finding_id`
- `suggested_next_stage`

## KG And Memory Behavior

- Recall prior attempts for the target before scraping.
- Record attempt with target, authorization notes, rate limit policy, tool path, and state checkpoint.
- Record finding with data location, schema summary, and integrity hash.
- Never store credentials, cookies, or tokens in outputs.

## Safety Boundaries

- No destructive actions, write operations, or side-effecting form submissions.
- No Terms of Service violations without explicit operator decision.
- No paid proxy/crawl provider use without approval.
- No credential/session storage in repo, logs, or scrape outputs.
- No fresh browser spawn for session-sensitive work when lifecycle requires CDP attach.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a data extraction task to coding namespace.
2. coding namespace dispatches `scraping-engineer`.
3. Specialist uses catalog and KG recall.
4. Specialist probes a harmless local/sample target, uses browser or HTTP extraction, and records rate-limit/state behavior.
5. Outbox includes extracted artifact path or structured missing-tool disposition.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship prompts, skills, setup checks, and sample scrapes. Private sessions, cookies, platform account state, target-specific raw data, and operator browser artifacts stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-scraping-engineer` assets until current specialist, catalog, and live dispatch proof cover each required extraction path or mark it optional/deprecated.
