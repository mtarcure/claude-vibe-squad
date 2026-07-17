# Tool Catalog

Reference for specialist `required_tools` / `preferred_tools`. Organized by capability.

> **Quick-reference index only.** The authoritative, citation-gating catalog is [`shared/api-catalog.md`](./api-catalog.md) — `bin/validate-specialists.sh` validates `required_tools` / `preferred_tools` against its `verified: yes` entries. This file groups the same tools by capability for quick lookup; **if the two disagree, `api-catalog.md` wins** and this index must be corrected to match. (github MCP and context7 are `verified: yes` in api-catalog as of 2026-07-12.)

## Web search & research

- `chrono-research-arsenal:arxiv_search` — academic papers and preprints
- `chrono-research-arsenal:xai_search` — web/X/news via xAI Grok
- `chrono-research-arsenal:perplexity_search_web` — general web search
- `firecrawl:scrape` — web page HTML extraction
- `firecrawl:crawl` — web crawl with link following
- `firecrawl:parse` — document parsing (PDF, HTML, etc.)
- `firecrawl:map` — site map discovery

## Documentation & library reference

- `context7:resolve-library-id` — resolve a library name to its context7 ID
- `context7:query-docs` — fetch current, version-specific library/framework docs (claude lane; `plugin:context7:context7`)

## Browser automation (shared Chrome state)

- `playwright:browser_navigate` — page navigation
- `playwright:browser_click`, `browser_fill_form`, `browser_type`, `browser_press_key` — DOM interaction
- `playwright:browser_take_screenshot`, `browser_snapshot` — capture state
- `chrome-devtools:navigate_page` — page navigation
- `chrome-devtools:click`, `evaluate_script`, `fill_form` — DOM interaction
- `chrome-devtools:take_screenshot` — capture state

## Code repository

- `github:pull_request_read` — read PR metadata and diffs
- `github:search_code` — search code across repo
- `github:create_pull_request` — create new PR
- `github:add_comment_to_pending_review` — inline review comments
- `github:list_commits`, `get_commit` — commit history
- `github:list_branches`, `list_pull_requests` — repo overview

## OSINT: infrastructure recon

- `chrono-recon:dns_enumerate_tool` — DNS zone records
- `chrono-recon:whois_lookup_tool` — domain/ASN WHOIS
- `chrono-recon:crt_sh_certificates_tool` — SSL certificate enumeration
- `chrono-recon:wayback_snapshots_tool` — historical web snapshots
- `chrono-recon:github_leaked_secrets_tool` — public GitHub leak search (needs `GH_TOKEN`)

## Cross-model reasoning (as tools)

- `chrono-research-arsenal:grok_reason` — peer-frontier second opinion via Grok
- `chrono-research-arsenal:deepseek_analyze` — long-context analysis via DeepSeek
- `chrono-research-arsenal:deepseek_review_diff` — huge-diff review via DeepSeek

## Content generation: image/video/audio

- `chrono-media-studio:higgsfield__generate_image` — AI image generation
- `chrono-media-studio:higgsfield__generate_video` — AI video generation
- `chrono-media-studio:higgsfield__generate_audio` — AI audio/voiceover
- `chrono-media-studio:higgsfield__generate_3d` — 3D model generation
- `chrono-media-studio:higgsfield__upscale_image` — image enhancement/upscaling
- `chrono-media-studio:higgsfield__upscale_video` — video enhancement/upscaling
- `chrono-media-studio:higgsfield__outpaint_image` — image expansion/uncrop
- `chrono-media-studio:higgsfield__reframe` — video aspect ratio change
- `chrono-media-studio:higgsfield__remove_background` — image cutout/transparency
- `chrono-media-studio:higgsfield__motion_control` — motion transfer/puppeteer
- `chrono-media-studio:higgsfield__virality_predictor` — video engagement/virality analysis
- `chrono-media-studio:higgsfield__create_website` — website generation
- `chrono-media-studio:higgsfield__deploy_website` — website deployment
- `chrono-media-studio:higgsfield__website_db` — website content management
- `chrono-media-studio:higgsfield__deploy_game` — game deployment
- `chrono-media-studio:higgsfield__publish_game` — game publication

## Voice + audio

- `chrono-media-studio:elevenlabs__text_to_speech` — TTS narration
- `chrono-media-studio:elevenlabs__voice_clone` — voice cloning
- `chrono-media-studio:elevenlabs__compose_music` — AI music composition
- `chrono-media-studio:elevenlabs__video_to_music` — music from video
- `chrono-media-studio:elevenlabs__text_to_sound_effects` — SFX generation
- `chrono-media-studio:elevenlabs__create_agent` — conversational agent creation
- `chrono-media-studio:elevenlabs__add_knowledge_base_to_agent` — agent knowledge base

## Knowledge & memory

- `chrono-vault:record` — write a canonical private memory note
- `chrono-vault:recall` — ranked FTS5 recall over canonical notes
- `chrono-vault:get_note` — retrieve a canonical note by stable ID
- `chrono-vault:set_status` — compare-and-swap lifecycle update
- `chrono-vault:record_usage` — record whether recalled memory was useful
- `chrono-vault:health` — validate the private root and index state
- `chrono-vault:vault_search` — human-only legacy Obsidian browsing; not a recall dependency

## Design & frontend

- `figma:*` — Figma design files (via Figma plugin)
- `frontend-design:*` — patterns library and component guidance

## Backend platforms

- `cloudflare:cloudflare-docs` — Cloudflare documentation
- `cloudflare:cloudflare-api` — Cloudflare API access
- `cloudflare:cloudflare-bindings` — Cloudflare Workers bindings
- `firebase:*` — Firebase services (auth, hosting, functions, etc.)

## Code quality & security

- `coderabbit:*` — automated code review
- `security-guidance:*` — security playbooks and risk guidance
