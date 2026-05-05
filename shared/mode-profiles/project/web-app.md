---
name: web-app
extends: project
status: active
---

# Project Profile: Web App

For Next.js / React / Vue / Svelte web applications. Covers frontend, backend, deploy.

## Auto-detection signals

- `package.json` with React/Vue/Svelte deps
- `next.config.js`, `vite.config.ts`, etc.
- Operator says "let's build a web app" / "Next.js project"

## Phase customizations

### Phase 1 Intake
- Test command: usually `npm test` or `pnpm test`
- Build: `npm run build`
- Deploy target: Vercel / Cloudflare / Netlify / fly.io / self-hosted

### Phase 2 Design
- Architect + designer (Content cross-namespace) for UI work
- Decide: app router vs pages, server components vs client, state management

### Phase 4 Build
- frontend-engineer (primary)
- ui-engineer (design-token / a11y enforcement)
- backend-engineer (API routes)
- devops-engineer (deploy config)

### Phase 6 Test
- vitest / jest (unit)
- Playwright (e2e — required for any user-facing flow)
- Visual regression (Playwright screenshots)
- Accessibility (axe-core via @axe-core/playwright)
- Cross-browser (Chrome + Safari + Firefox)
- Lighthouse audit on key pages

### Phase 8 Release
- PR description with screenshots
- Changelog entry
- Deploy command (Vercel deploy, etc.)
- Smoke test on deployed URL

## Specialists most active

- frontend-engineer
- ui-engineer
- backend-engineer
- devops-engineer
- test-engineer (heavy on e2e)
- code-reviewer (multi-model)
- designer (Content cross-namespace)
