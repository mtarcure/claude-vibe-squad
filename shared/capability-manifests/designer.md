# Capability Manifest: designer

Status: draft, preserve before cleanup
Owner: content namespace
Canonical current specialist: `departments/content/specialists/designer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-designer/0.1.0/`

## Role Contract

`designer` owns creative direction, visual systems, design tokens, accessibility review, Figma fidelity, brand assets, and visual QA. It specifies and validates visual intent; `ui-engineer` or `frontend-engineer` implements.

## Preserved Current Behavior

- Drives design direction and asset review.
- Requires accessibility/token discipline.
- Hands implementation constraints to Coding.
- Surfaces brand-system pivots for operator approval.
- Tracks asset provenance and licensing.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `svgo_optimize`
- `style_dictionary_build`
- `a11y_axe_scan`
- `a11y_pa11y_scan`
- `design_token_lint`
- `color_contrast_check`
- `component_snapshot`
- `figma_export`
- `playwright_visual_compare`

## Required Tools

- Design-token lint/build path.
- WCAG contrast and a11y scan path.
- Screenshot/visual baseline path.
- Figma export or documented fallback.
- SVG hygiene path.

## Optional Tools

- Full Figma API integration.
- Pixel-diff visual regression.
- Style Dictionary build output for multiple platforms.

## MCPs

- `chrono-content-engineer`: generation support when visual assets are generated.
- `chrono-kg`: design findings and prior audits.
- `chrono-catalog`: tool/skill availability.
- `chrono-vault` / `chrono-obsidian`: artifact references.
- `sequential-thinking`: brand-system tradeoffs.

## Skills

- `design-token-governance`
- `a11y-audit`
- `chrono-ui-aesthetic-framework`
- `visual-regression-baseline`
- `design-review-flow`
- `figma-to-code-fidelity`

## Adaptive Operating Mode

Recall prior component/brand audits, inspect design inputs, run accessibility/token/contrast checks, use visual baselines when claiming fidelity, record findings, and hand actionable specs to Coding with implementation constraints.

## Output Contract

- `design_rationale_path`
- `design_tokens_path`
- `a11y_violations`
- `contrast_failures`
- `visual_diff_score`
- `token_lint_issues`
- `asset_paths`
- `kg_finding_id`

## KG And Memory Behavior

- Record design decisions, audits, and visual findings.
- Preserve asset provenance, license, and source.
- Keep private/client design files local unless sanitized.

## Safety Boundaries

- No implementation code ownership.
- No unlicensed assets.
- No design-system breaking changes without approval.
- No pixel-perfect claims without evidence.

## Live Dispatch Proof

1. Chrono dispatches a design/a11y task to content namespace.
2. content namespace dispatches `designer`.
3. Specialist uses catalog/KG and runs or reports missing design/a11y tooling.
4. Outbox includes visual/a11y/token evidence and implementation handoff.
5. Active registry closes.

## Public/Private Disposition

Public repo may ship role prompt, manifest, schemas, and sanitized examples. Client Figma files, proprietary brand assets, and generated paid media stay local/private unless explicitly released.

## Cleanup Disposition

Do not delete old `chrono-plugin-designer` assets until current role preserves design-token, a11y, Figma, SVG, and visual-regression capabilities.
