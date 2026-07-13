---
name: research
version: 1.1
primary_mode_namespace: research
status: active
phases: 5
---

# Mode: Research

For deep investigation, comparison, source gathering, and synthesis. Research mode is source-first, citation-heavy, and operator-approved.

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 1 | Scope | `large-context-analyst`, `planner` |
| 2 | Gather sources | `research`, `scout`, `data-extraction-engineer` |
| 3 | Synthesize | `synthesizer`, `large-context-analyst` |
| 4 | Integrity gate | `skeptic`, `vibecoding-check` |
| 5 | Deliverable | `technical-writer`, `summarizer` |

## Dispatch Notes

- `source_namespace: research` only stores research specialist work; it never chooses the model. Per `shared/routing.md`, research/synthesis/long-context specialists (`research`, `synthesizer`, `large-context-analyst`) are claude-primary (`claude-fable-5`) with codex backup — **kimi is the throughput-only lane (0 primaries)**, used only for bulk/mechanical passes under the downshift gate (`summarizer`; `data-extraction-engineer` bulk backup).
- Chrono picks the model lead by specialist capability and source shape, not by namespace.
- Use primary sources where possible. Label weak sources and unresolved contradictions.
- Citation-bearing output must include enough source metadata for Chrono to verify.

## Gates

- Operator approval for final durable notes when the topic is sensitive, private, legal, financial, medical, public release, or reputation-impacting.
- Mandatory review for high-impact claims.
- Run `vibecoding-check` before delivery.
