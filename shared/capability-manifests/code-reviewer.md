# Capability Manifest: Code Reviewer

Status: draft
Owner: coding namespace
Canonical specialist: `departments/coding/specialists/code-reviewer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-code-reviewer/0.1.0/`

## Role Contract

Code Reviewer owns diff-aware review, spec compliance, severity-laddered findings, adversarial questions, and static-analysis interpretation for code changes. It reports findings; it does not write fixes, approve directly, or mutate branch history. Multi-model review must exclude the writer family.

## Preserved From Current Specialist

- Mandatory multi-model review with writer-family exclusion.
- Structured severity ladder.
- Handoffs to `refactor-cleaner`, `test-engineer`, and `security-analyst`.
- Output as consolidated `review-findings.md`.
- No direct fix authoring.

## Preserve From Old Plugin

### Required Tool Surface

- `semgrep_diff_scan`
- `ast_grep_rule`
- `ruff_check`
- `ruff_format`
- `mypy_check`
- `codeql_query`
- `difftastic_compare`
- `delta_diff`
- `pr_review_loop`
- `sarif_merge`

### Skills

- `code-review-loop`
- `diff-aware-semgrep-scan`
- `dimensional-analysis-check`
- `review-severity-ladder`
- shared `adversarial-review`
- shared `spec-to-code-compliance`
- shared `fp-check`
- shared `claim-validation-gate`
- shared `differential-review`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> inspect diff/spec -> run diff-aware checks -> adversarial review -> false-positive filter -> consolidate multi-model findings -> record -> handoff
```

Required behavior:

- Review changed files and relevant context, not style churn.
- Use diff-aware Semgrep where available.
- Pivot to AST/type/structural review when SAST is silent.
- Force contract/API questions for public API changes.
- Escalate security-touchpoint findings to Security.
- Mark model agreement/disagreement in consolidated output.

## Output Contract

Return a structured report with:

- `ok`
- `verdict`
- `findings`
- `spec_gaps`
- `adversarial_questions`
- `model_agreement`
- `kg_attempt_id`
- `suggested_next_stage`
- missing-capability list when tools are unavailable

## KG And Memory Behavior

- Recall prior reviews before work.
- Record review attempt before scanning.
- Record confirmed findings only after false-positive filtering.
- Durable memory is appropriate for recurring repo review rules and accepted severity precedents.

## Safety Boundaries

- No code fixes.
- No branch history mutation.
- No active network scanning.
- No CVSS scoring.
- No approval/rejection as final authority.

## Live Dispatch Proof

1. Chrono dispatches a small diff fixture to coding namespace.
2. coding namespace selects `code-reviewer`.
3. Specialist runs diff review, `codex review`, semgrep/ruff/mypy, or structured missing-tool output.
4. Response includes severity-laddered finding format.
5. Active registry closes.
6. Chrono summarizes whether `refactor-cleaner`, `test-engineer`, or Security should run next.

## Public/Private Disposition

- Public: review loop, severity ladder, fixture diffs, output schema.
- Private/local: client diffs, unreleased vulnerabilities, private PR content, SARIF with proprietary paths.

## Cleanup Disposition

Do not delete old code-reviewer plugin source until this manifest is complete, current specialist is updated, and diff review proof passes.
