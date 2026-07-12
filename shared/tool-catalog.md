# Tool Catalog

Reference for specialist `required_tools` / `preferred_tools`. Organized by capability.

## Web search & research

- `chrono-research-arsenal:arxiv_search` — academic papers and preprints
- `chrono-research-arsenal:xai_search` — web/X/news via xAI Grok
- `chrono-research-arsenal:perplexity_search_web` — general web search
- `firecrawl:scrape` — web page HTML extraction
- `firecrawl:crawl` — web crawl with link following
- `firecrawl:parse` — document parsing (PDF, HTML, etc.)
- `firecrawl:map` — site map discovery

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

- `chrono-recon:dns_enumerate` — DNS zone records
- `chrono-recon:whois_lookup` — domain/ASN WHOIS
- `chrono-recon:crt_sh_certificates` — SSL certificate enumeration
- `chrono-recon:wayback_snapshots` — historical web snapshots
- `chrono-recon:github_leaked_secrets` — public GitHub leak search

## Cross-model reasoning (as tools)

- `chrono-research-arsenal:grok_reason` — peer-frontier second opinion via Grok
- `chrono-research-arsenal:deepseek_analyze` — long-context analysis via DeepSeek
- `chrono-research-arsenal:deepseek_review_diff` — huge-diff review via DeepSeek

## Content generation: image/video/audio

- `chrono-content-engineer:higgsfield__generate_image` — AI image generation
- `chrono-content-engineer:higgsfield__generate_video` — AI video generation
- `chrono-content-engineer:higgsfield__generate_audio` — AI audio/voiceover
- `chrono-content-engineer:higgsfield__generate_3d` — 3D model generation
- `chrono-content-engineer:higgsfield__upscale_image` — image enhancement/upscaling
- `chrono-content-engineer:higgsfield__upscale_video` — video enhancement/upscaling
- `chrono-content-engineer:higgsfield__outpaint_image` — image expansion/uncrop
- `chrono-content-engineer:higgsfield__reframe` — video aspect ratio change
- `chrono-content-engineer:higgsfield__remove_background` — image cutout/transparency
- `chrono-content-engineer:higgsfield__motion_control` — motion transfer/puppeteer
- `chrono-content-engineer:higgsfield__virality_predictor` — video engagement/virality analysis
- `chrono-content-engineer:higgsfield__create_website` — website generation
- `chrono-content-engineer:higgsfield__deploy_website` — website deployment
- `chrono-content-engineer:higgsfield__website_db` — website content management
- `chrono-content-engineer:higgsfield__deploy_game` — game deployment
- `chrono-content-engineer:higgsfield__publish_game` — game publication

## Voice + audio

- `chrono-content-engineer:elevenlabs__text_to_speech` — TTS narration
- `chrono-content-engineer:elevenlabs__voice_clone` — voice cloning
- `chrono-content-engineer:elevenlabs__compose_music` — AI music composition
- `chrono-content-engineer:elevenlabs__video_to_music` — music from video
- `chrono-content-engineer:elevenlabs__text_to_sound_effects` — SFX generation
- `chrono-content-engineer:elevenlabs__create_agent` — conversational agent creation
- `chrono-content-engineer:elevenlabs__add_knowledge_base_to_agent` — agent knowledge base

## Knowledge & memory

- `chrono-vault:read_specialist` — read specialist definitions
- `chrono-vault:write_specialist` — update specialist state
- `chrono-vault:kg_query` — knowledge graph queries
- `chrono-vault:obsidian_search` — Obsidian vault search

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
