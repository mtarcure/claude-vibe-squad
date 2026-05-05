# Capability Manifest: UI Engineer

Status: draft
Owner: coding namespace, with Content Designer handoff
Canonical specialist: `departments/coding/specialists/ui-engineer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-designer/0.1.0/`

## Role Contract

UI Engineer owns technical UI fidelity: design-token plumbing, Figma-to-code fidelity, accessibility audits, visual regression, component snapshots, SVG hygiene, and implementation-quality UI checks. It lives beside `frontend-engineer`: frontend builds app/framework logic; UI Engineer ensures the implementation matches the design system and accessibility bar. Content `designer` owns visual/brand decisions.

## Preserved From Current Specialist

- Technical UI implementation validation.
- Figma/source-design clarification handoff.
- A11y and visual regression gates.
- No new aesthetic system design.
- Skills: `frontend-design`, `design-token-governance`, `a11y-audit`, `chrono-ui-aesthetic-framework`, `figma-implement-design`, `figma-code-connect`.

## Preserve From Old Designer Plugin

### Required Tool Surface

- `svgo_optimize`
- `style_dictionary_build`
- `a11y_axe_scan`
- `a11y_pa11y_scan`
- `design_token_lint`
- `color_contrast_check`
- `component_snapshot`
- `figma_export`
- `playwright_visual_compare`

### Skills

- `a11y-audit`
- `chrono-ui-aesthetic-framework`
- `design-review-flow`
- `design-token-governance`
- `figma-to-code-fidelity`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> inspect design/source -> run token/a11y/visual checks -> classify issues -> handoff to frontend or designer
```

Required behavior:

- Validate accessibility with tool evidence, not opinion.
- Check contrast before signing off visual changes.
- Verify visual regression baseline freshness before calling failure.
- Prefer design tokens over hardcoded values.
- Degrade gracefully when Figma auth is unavailable by using local screenshots/snapshots.
- Do not claim pixel fidelity without visual comparison evidence.

## Output Contract

Return a structured report with:

- `ok`
- `component`
- `a11y_violations`
- `contrast_failures`
- `visual_diff_score`
- `token_lint_issues`
- `artifacts`
- `kg_finding_id`
- `suggested_next_stage`
- missing-capability list when tools/auth are unavailable

## KG And Memory Behavior

- Recall prior audits for component/screen before work.
- Record attempt before validation.
- Record durable findings for WCAG violations, contrast failures, token decisions, and accepted baselines.

## Safety Boundaries

- No business logic or application state ownership.
- No brand/design authorship unless explicitly asked.
- No Figma source mutation.
- No production deploy.
- No accessibility waiver without operator approval.

## Live Dispatch Proof

1. Chrono dispatches a UI fixture to coding namespace.
2. coding namespace selects `ui-engineer`.
3. Specialist runs a11y/token/visual check or structured missing-tool output.
4. Response includes artifact/evidence paths.
5. Active registry closes.
6. Chrono summarizes whether `frontend-engineer`, Content `designer`, or `test-engineer` should run next.

## Public/Private Disposition

- Public: a11y/token/visual protocol, fixture snapshots, output schema.
- Private/local: Figma tokens/assets from private clients, authenticated screenshots, proprietary UI references.

## Cleanup Disposition

Do not delete old designer plugin source until both this UI manifest and the later Content `designer` manifest are complete and their responsibilities are separated clearly.
