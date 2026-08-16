# Tool Catalog

Reference for specialist `required_tools` / `preferred_tools`. Organized by capability.

> **Quick-reference index only.** The authoritative, citation-gating catalog is [`shared/api-catalog.md`](./api-catalog.md) — `bin/validate-specialists.sh` validates `required_tools` / `preferred_tools` against its `verified: yes` entries. This file groups the same tools by capability for quick lookup; **if the two disagree, `api-catalog.md` wins** and this index must be corrected to match. (github MCP and context7 are `verified: yes` in api-catalog as of 2026-07-12.)

## Web search & research

- `chrono-research-arsenal:arxiv_search` — academic papers and preprints
- `chrono-research-arsenal:xai_search` — web/X/news via xAI Grok
- `chrono-research-arsenal:perplexity_search` — canonical budgeted cited-web search; fresh worker receipt pending
- `firecrawl:scrape` — web page HTML extraction
- `firecrawl:crawl` — web crawl with link following
- `firecrawl:parse` — document parsing (PDF, HTML, etc.)
- `firecrawl:map` — site map discovery
- `chrono-research-arsenal:firecrawl_scrape` — provider-proven all-lane governed scrape wrapper; metered key required
- `chrono-research-arsenal:firecrawl_crawl` — partial bounded crawl wrapper; unit-tested but no live provider receipt
- `chrono-research-arsenal:firecrawl_parse` — partial explicit-byte parser; unit-tested but no live provider receipt

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

- `chrono-research-arsenal:xai_search` — verified Grok-backed web/X/news route; the stale `grok_reason` token is not live

## Content generation: image/video/audio

- `chrono-media-studio:generate_image` — verified governed image wrapper
- `chrono-media-studio:generate_video` — verified governed video wrapper
- `chrono-media-studio:generate_audio` — verified governed audio wrapper
- `higgsfield__generate_image` — **not live directly**; use the governed wrapper
- `higgsfield__generate_video` — **not live directly**; use the governed wrapper
- `higgsfield__generate_audio` — **not live directly**; use the governed wrapper
- `higgsfield__models_explore` — Claude-child schema observed; semantic liveness remains unproven
- `higgsfield__generate_3d` — Claude-child schema observed; paid action and semantic liveness remain gated
- `higgsfield__upscale_image` — Claude-child schema observed; paid action and semantic liveness remain gated
- `higgsfield__upscale_video` — Claude-child schema observed; paid action and semantic liveness remain gated
- `higgsfield__outpaint_image` — Claude-child schema observed; paid action and semantic liveness remain gated
- `higgsfield__reframe` — Claude-child schema observed; paid action and semantic liveness remain gated
- `higgsfield__remove_background` — Claude-child schema observed; paid action and semantic liveness remain gated
- `higgsfield__motion_control` — Claude-child schema observed; paid action and semantic liveness remain gated
- `higgsfield__virality_predictor` — Claude-child schema observed; preview/create behavior remains unproven
- Website/game deployment child names previously listed here had no typed registry declaration and are not claimed as tools.

## Voice + audio

- `elevenlabs:{text_to_speech,voice_clone,speech_to_speech,text_to_sound_effects,compose_music,video_to_music,upload_music_for_inpainting,create_agent,add_knowledge_base_to_agent}` — canonical Claude sibling-MCP operations; available-gated/unproven pending role-scoped credential and semantic receipts

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

- `cloudflare:*` — catalog-absent in the current squad lane surface; do not cite as live
- `firebase:*` — partial: MCP/config observed, but login, active project, and deploy path remain unverified

## Code quality & security

- `coderabbit:*` — catalog-absent; design-backlog only
- `security-guidance:*` — security playbooks and risk guidance

## Binary and firmware analysis

- `radare2` — verified local static inspection/disassembly (`6.1.4`)
- `gdb` — installed (`17.1`) and verified only for offline binary parsing; target execution is not live on this host
- `ghidra`, `binwalk`, `qemu` — genuinely absent; keep dependent routes at `needs_tool`
