# Content Engineer Department

Specialists organized by media type and production function. Each owns one deliverable form.

## Specialists

- **copywriter** — short-form and long-form text content (marketing copy, blogs, ads, product descriptions)
- **voice-narrator** — text-to-speech narration and voice production
- **music-composer** — original music composition and video-to-music transformation
- **sound-designer** — sound effects, audio design, and sonic branding
- **video-director** — video generation and orchestration with motion control
- **video-editor** — post-production, reframing, upscaling, and compositing
- **image-designer** — image generation, editing, and visual design
- **web-builder** — website generation, design systems, and deployment
- **game-designer** — browser game development and publication
- **voice-agent-builder** — conversational AI agents and knowledge base setup

## Integration Points

Content-engineer specialists primarily use:
- `chrono-content-engineer` MCP suite (Higgsfield, ElevenLabs, etc.)
- `figma` plugin for design systems
- `firebase` for backend/hosting
- `chrono-vault` for knowledge and project context

## Preserved guidance (migrated from deprecated content/ specialists)

*These guardrails came from `content-creator`, `designer`, and `media-producer` — deleted 2026-07-12 during content-engineer consolidation. All specialists in this department inherit them.*

**Cost discipline (from content-creator):** Do not create unnecessary variants. Prefer one clear draft plus a small number of targeted alternatives. "Decisions over options" — the operator wants direction, not paralysis. Show one strong choice + brief alternatives, not 5 equal contenders.

**Provenance requirement (from media-producer):** Every generated asset must log its provenance: prompt used, provider route (Higgsfield/ElevenLabs/etc), cost or credit note, source references, and rejection/approval status. Write to `generation-log.md` under the project's `write_scope`.

**Cost gate (from media-producer):** Never spend credits on paid providers without explicit operator approval per dispatch. Providers marked `verified: no` or `needs-research` in `shared/api-catalog.md` MUST NOT be treated as live. Surface to operator before generation.

**Likeness / voice cloning gate (from media-producer):** If a request may depict a real person, clone a real voice, mimic copyrighted characters, or use protected brand marks, stop and dispatch to Security/`privacy-steward` before generation. Never generate without operator hard-gate approval.

**Design-system awareness (from designer):** For UI work, respect design tokens (JSON/YAML), enforce a11y (color contrast, focus states, semantic HTML, ARIA), and hand off to `coding/ui-engineer` with proper Figma layer naming + accessibility annotations + edge cases (loading/error/empty states). Do NOT introduce design-system breaking changes without operator approval.

**Cross-namespace coordination:** For surrounding copy/narration/captions, dispatch to `editor` or `brand-voice`. For structural layout / UI, dispatch to `coding/ui-engineer`. For distribution strategy, dispatch to `social-strategist`. Content-engineer produces the deliverable; the strategic layer is handled by Chrono + these adjacent specialists.

