---
name: agent-app
extends: project
status: active
---

# Project Profile: Agent / LLM Application

Apps built on Anthropic / OpenAI / Google SDKs — agent loops, RAG systems, multi-step LLM applications.

## Auto-detection signals

- Imports `anthropic` / `openai` / `@anthropic-ai/sdk` / `claude-agent-sdk` / etc.
- File names like `agent.py`, `tools.py`, prompts/
- Operator mentions "agent" / "LLM app" / "RAG"

## Phase customizations

### Phase 1 Intake
- Define agent's capability scope
- List required tools (file ops? web? specialized APIs?)
- Determine eval requirements (regression tests for prompts)

### Phase 2 Design
- ai-engineer is primary (knows agentic patterns)
- architect for any non-trivial multi-tool composition
- Decide: single agent vs orchestrated team
- Decide: prompt caching strategy
- Multi-model routing: which model for which subtask

### Phase 4 Build
- ai-engineer (primary)
- backend-engineer for service-layer wrap
- prompt-engineer (cross-cutting) for tuning prompts

### Phase 6 Test
- Eval suite (promptfoo / Anthropic eval guidance / custom)
- Regression tests for prompt changes
- Cost / latency tracking
- Tool-call fidelity (does the agent invoke tools correctly?)

### Phase 8 Release
- Eval results in changelog
- Prompt-cache hit rate measured
- Token / cost telemetry hooked up

## Specialists most active

- ai-engineer (primary)
- prompt-engineer (cross-cutting)
- backend-engineer
- test-engineer (eval-focused testing)
- code-reviewer (multi-model)

## Agent-app concerns

- Token cost matters even on subscriptions (rate limits)
- Prompt caching reduces 80%+ of cost on repeated runs
- Tool descriptions are PROMPTS (not just code) — write them for the model
- Hallucinated tool calls are common — add guardrails
- Deterministic output is rare; design for variance
- Logging tool-calls is critical for debugging
