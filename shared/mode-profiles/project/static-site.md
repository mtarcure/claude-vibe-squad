---
name: static-site
extends: project
status: active
---

# Project Profile: Static Site

Hugo / Jekyll / Astro / Eleventy / Gatsby — content-driven sites that build to static HTML.

## Auto-detection signals

- `hugo.toml` / `_config.yml` / `astro.config.mjs` / `.eleventy.js`
- Content directory of markdown files
- Operator says "static site" / "blog" / "documentation site"

## Phase customizations

### Phase 1 Intake
- Generator chosen (Hugo? Astro? Jekyll?)
- Hosting (GitHub Pages, Cloudflare Pages, Netlify, Vercel)
- Domain configuration

### Phase 2 Design
- Theme (existing? custom?)
- Information architecture (navigation, taxonomy)
- Content workflow (markdown → preview → publish)

### Phase 4 Build
- frontend-engineer (templates, layouts)
- ui-engineer (visual polish, design tokens)
- content-creator (Content cross-namespace) for hero images / OG tags
- devops-engineer (deploy automation)

### Phase 6 Test
- Build succeeds (no broken templates)
- HTML linting (htmlhint)
- Link checking (broken-link-checker)
- Lighthouse on key pages
- Visual regression on hero pages

### Phase 8 Release
- Deploy to hosting (often automatic on push to main)
- Verify live URL
- Update sitemap if structure changed

## Specialists most active

- frontend-engineer
- ui-engineer
- designer (Content cross-namespace)
- content-creator (Content cross-namespace) for visual assets
- devops-engineer (deploy)
- technical-writer (Content cross-namespace) if writing-heavy site

## Static-site concerns

- Build time matters at scale (1000+ pages = slow Hugo build acceptable; slow Gatsby less so)
- SEO basics: sitemap, robots, meta tags
- Performance: pre-built static is ideal but image optimization matters
- Accessibility on the actual rendered HTML
