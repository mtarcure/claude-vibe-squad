# Capability Manifest: summarizer

Status: draft, current-system capability
Owner: Shared / all Leads
Canonical current specialist: `shared/specialists/summarizer.md`
Old plugin source: none direct in old `claude-chrono`; do not conflate with `synthesizer`.

## Role Contract

`summarizer` owns context compression for long-running Lead sessions, phase summaries, dispatch-history summaries, and resume continuity. It compresses faithfully; it does not synthesize new findings or drop open loops.

## Preserved Current Behavior

- Uses cheap/fast model by default.
- Preserves decisions, artifacts, open loops, citations, errors, and approvals.
- Avoids silent auto-compact except configured phase/dispatch triggers with operator nudge where required.
- Reduces token load while preserving operational continuity.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve current context-compression behavior and keep distinct from research `synthesizer`.

## Required Tools

- Transcript/dispatch history read path.
- Summary artifact write path.
- Preserve/drop field schema.
- Context/token size estimate path where available.

## Optional Tools

- Automatic context threshold detector.
- Summary quality checker.

## MCPs

- `chrono-kg`: record summaries/open loops when durable.
- `chrono-vault` / `chrono-obsidian`: summary artifact references.
- `chrono-catalog`: capability lookup.

## Skills

- `context-compression`
- `decision-preservation`
- `open-loop-preservation`
- `citation-preservation`

## Adaptive Operating Mode

Read source context and preserve list, compress only resolved routine detail, keep decisions/artifacts/open loops/citations/errors, write summary with source range and size estimates, and flag uncertainty by keeping more rather than less.

## Output Contract

- `summary_path`
- `decisions_made`
- `results_produced`
- `open_loops`
- `key_citations`
- `compressed_from`
- `token_reduction_estimate`

## KG And Memory Behavior

- Record summaries as navigation aids, not runtime truth unless explicitly promoted.
- Never drop operator approvals/rejections.

## Safety Boundaries

- No new claims.
- No lossy deletion of open loops.
- No replacement of live state truth.
- No expensive frontier model by default.

## Live Dispatch Proof

1. Chrono dispatches a phase or dispatch-history compression task.
2. Summarizer writes a bounded summary preserving decisions/open loops.
3. Outbox includes summary path and compression range.
4. Active registry closes.

## Public/Private Disposition

Public repo may ship prompt, manifest, and sample summaries. Live transcripts and private session summaries stay local.

## Cleanup Disposition

Keep as current-system capability because it protects tokens/context. Do not remove summary triggers or schemas without replacement.
