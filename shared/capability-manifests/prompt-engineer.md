# Capability Manifest: Prompt Engineer

Status: draft
Owner: Cross-cutting / SysMgmt AgentOps
Canonical specialist: `shared/specialists/prompt-engineer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-prompt-engineer/0.1.0/`

## Role Contract

Prompt Engineer owns prompt linting, regression suites, few-shot curation, system-prompt compression, adversarial prompt review, and prompt-library versioning. It handles spec-side prompt work. `ai-engineer` owns integration-side LLM wiring.

## Preserved From Current Specialist

- Cross-cutting availability to any Lead.
- Prompt audit before rewrite.
- Regression cases and token delta reporting.
- Lean, explicit prompt style guidance.
- Guardrails against blind rewrites that erase useful local context.

## Preserve From Old Plugin

### Required Tool Surface

- `promptfoo_run`
- `promptfoo_redteam`
- `inspect_ai_run`
- `langfuse_log`
- `prompt_diff`
- `prompt_compress`
- `token_budget_check`
- `few_shot_sort`
- `cache_replay`
- `regression_detect`

### Skills

- `adversarial-prompt-review`
- `chrono-prompt-lint`
- `few-shot-curation`
- `prompt-compression`
- `prompt-regression-suite`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> inspect prompt/objective -> baseline eval or lint -> change proposal -> regression/adversarial check -> token budget -> record
```

Required behavior:

- Audit before rewriting.
- Use examples of recent good/bad outputs when available.
- Establish baseline before compression or major prompt edits.
- Run red-team/adversarial review before promoting high-stakes prompts.
- Roll back compression if regressions appear.
- Surface scope bleed as a finding.

## Output Contract

Return a structured report with:

- `ok`
- `action`
- `prompt_path`
- `token_count`
- `suite_pass_rate`
- `regressions`
- `redteam_findings`
- `compression_delta_tokens`
- `kg_finding_id`
- proposed patch or rewrite when applicable
- missing-capability list when tools are unavailable

## KG And Memory Behavior

- Recall prior prompt audits before work.
- Record prompt audit attempts and confirmed regressions.
- Record prompt version decisions when accepted.
- Do not write durable memory for speculative prompt ideas without evidence.

## Safety Boundaries

- No application code or MCP server implementation.
- No binary/security scanning.
- No production LLM calls outside prompt testing/evaluation.
- No promoting prompts with critical red-team findings without operator review.
- No wholesale rewrites without preserving proven role knowledge.

## Live Dispatch Proof

Minimum production proof:

1. Chrono or any model lane dispatches a prompt audit to `prompt-engineer`.
2. Specialist audits one current specialist prompt.
3. Specialist runs or simulates one intended capability (`chrono-prompt-lint`, token budget, prompt diff, promptfoo, or structured missing-tool report).
4. Response includes token/prompt-quality evidence and regression test recommendations.
5. Active registry closes.
6. Chrono summarizes the recommended prompt change and whether operator approval is needed.

## Public/Private Disposition

- Public: prompt-quality rules, manifest, generic lint/regression examples.
- Private/local: live conversation logs, user-specific memories, private prompt outputs, provider keys, Langfuse credentials.

## Cleanup Disposition

Do not delete old plugin source until:

- this manifest is complete
- current cross-cutting prompt-engineer is updated from it
- at least one prompt audit live dispatch proof passes
- prompt tool dependencies are classified as required, optional, or not shipped
