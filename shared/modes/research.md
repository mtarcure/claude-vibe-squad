---
name: research
version: 1.1
primary_mode_namespace: research
status: active
phases: 5
---

# Mode: Research

For deep investigation, comparison, source gathering, and synthesis. Research mode is source-first, citation-heavy, and operator-approved.

## Capabilities

`capability_state` is **derived** and machine-checked by `bin/validate-capabilities.sh` (not hand-set), so this index stays honest by construction. Cards live in `shared/capabilities/research/`. Load-bearing web claims route through the Rule-8 grounding path — `Google Search grounding` (gemini·yes·subscription, verified cited results) is the live subscription grounding route, alongside the metered `perplexity_search_web` (unverifiable ⇒ `needs_tool`, not PASS).

| Capability | State | When |
|---|---|---|
| [Multi-source investigation + synthesis](../capabilities/research/investigation-synthesis.md) | `live` | deep research / competitive / literature → cited synthesis |
| [Data extraction + dataset wrangling](../capabilities/research/data-extraction-dataset.md) | `live` | machine-readable extraction/wrangling — PDF/OCR is `needs_tool` |
| [Learning + study](../capabilities/research/learning-study.md) | `live` | study plans, drills, learning paths |

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 1 | Scope | `large-context-analyst`, `planner` |
| 2 | Gather sources | `research`, `scout`, `data-extraction-engineer` |
| 3 | Synthesize | `synthesizer`, `large-context-analyst` |
| 4 | Integrity gate | `skeptic`, `vibecoding-check` |
| 5 | Deliverable | `technical-writer`, `summarizer` |

## Dispatch Notes

- `source_namespace: research` only stores research specialist work; it never chooses the model. Per `shared/routing.md`, research/synthesis/long-context specialists (`research`, `synthesizer`, `large-context-analyst`) are claude-primary (`claude-fable-5`) with codex backup. **For research work Kimi is throughput/backup only** — its sole primary is the allowlisted `experimental-attacker`. The kimi downshift-throughput case here is `summarizer` (`throughput_lane=kimi`, `throughput.downshift_gated.v1`); `data-extraction-engineer` is codex-primary with kimi as a **conservative operational backup** (`throughput_lane=none`, `throughput.never.v1`), not a downshift-throughput role.
- Chrono picks the model lead by specialist capability and source shape, not by namespace.
- **Fan grounded/bulk work off the Claude+Codex default:** load-bearing web claims route through the **Gemini** Google-Search grounding path (or `bounty-researcher` for grounded prior-work recon); bulk/mechanical **summarization** downshifts to **Kimi** throughput (`summarizer`, under the downshift gate). `data-extraction-engineer` stays codex-primary and uses Kimi only as an operational backup (`throughput.never`), not as throughput. Reserve Claude/Codex for the judgment-heavy synthesis and validation.
- Use primary sources where possible. Label weak sources and unresolved contradictions.
- Citation-bearing output must include enough source metadata for Chrono to verify.

## Gates

- Operator approval for final durable notes when the topic is sensitive, private, legal, financial, medical, public release, or reputation-impacting.
- Mandatory review for high-impact claims.
- Run `vibecoding-check` before delivery.
