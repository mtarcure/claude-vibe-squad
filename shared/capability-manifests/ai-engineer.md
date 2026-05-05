# Capability Manifest: ai-engineer

Status: draft, preserve before cleanup
Owner: coding namespace
Canonical current specialist: `departments/coding/specialists/ai-engineer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-ai-engineer/0.1.0/`

## Role Contract

`ai-engineer` owns LLM application design, MCP tool design, RAG evaluation, local model experiments, multi-model routing, and eval-backed AI architecture decisions. It does not provision infrastructure, deploy services, or own production backend wiring.

## Preserved Current Behavior

- Reads KG/memory before AI architecture or eval work.
- Applies architecture and routing skills before inventing new orchestration.
- Requires eval evidence for RAG, generation, or routing changes.
- Hands implementation to `backend-engineer` or deployment to `devops-engineer`.

## Old Plugin Capabilities To Preserve

Old plugin tool surface:

- `litellm_complete`, `litellm_stream`, `litellm_list_models`
- `embedding_compare`
- `inspect_ai_run`
- `ragas_run`
- `langfuse_trace`
- `ollama_run`, `ollama_pull`
- `mcp_use_local`, `mcp_use_remote`
- `dspy_compile`

Old shared tools:

- `httpx_probe`
- `docker_run`
- `gh_api`
- `http_get`

Preservation rule: these are capability requirements. They may be represented as direct MCP tools, CLI instructions, skills, or verified local commands, but cleanup must not erase the ability to run AI evals, compare models, test local models, or design MCP surfaces.

## Required Tools

- Multi-model call surface through LiteLLM or equivalent provider router.
- RAG eval runner, preferably `ragas`, with structured metric output.
- Structured generation eval runner, preferably `inspect-ai`.
- Local model runner, preferably `ollama`, for local experiment paths.
- MCP invocation/probe path for local and remote MCP tool testing.

## Optional Tools

- Langfuse tracing, graceful-degrade when env/auth is unavailable.
- DSPy compilation, graceful-degrade when not installed.
- Embedding similarity helper.

## MCPs

- `chrono-kg`: recall prior AI decisions and record attempts/findings.
- `chrono-catalog`: list currently available skills/tools at dispatch time.
- `chrono-vault` / `chrono-obsidian`: durable artifact and memory references.
- `sequential-thinking`: complex architecture and routing tradeoff analysis.

## Skills

Current or old skills to keep represented:

- `agent-architecture-pattern`
- `mcp-tool-design`
- `multi-model-routing-discipline`
- `rag-eval-loop`
- `prompt-cache-discipline`
- `eval-harness-pattern`
- `local-model-experiment-flow`

## Adaptive Operating Mode

Recall prior baselines, apply the relevant design/eval skill, run a baseline, iterate only when evidence warrants it, record the result, and hand off implementation. The specialist should not pick a model, routing rule, RAG chunking change, or agent architecture without a cost/quality or eval rationale.

## Output Contract

Expected return shape:

- `artifact_type`: `architecture_spec`, `eval_result`, `routing_config`, or `experiment_result`
- `artifact_path` when a spec/config is written
- `eval_metrics` when evaluation runs
- `routing_recommendation` when model routing is changed
- `cost_quality_justification`
- `kg_finding_id`
- `suggested_next_stage`

## KG And Memory Behavior

- Recall previous results before new evals.
- Record every eval or model experiment as an attempt.
- Record confirmed findings with metric names, dataset paths, model versions, and cost assumptions.
- Do not store sensitive prompts or private customer data in public docs.

## Safety Boundaries

- No deployment or infra provisioning.
- No production routing change without review and benchmark evidence.
- No sensitive prompt/content exfiltration to tracing providers without explicit approval.
- No vector database or RAG infrastructure expansion for small corpora unless evidence justifies it.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches coding namespace with an AI eval/routing task.
2. coding namespace dispatches `ai-engineer`.
3. `ai-engineer` uses `chrono-catalog` and `chrono-kg`.
4. Specialist runs or gracefully-degrades one eval/tool probe (`inspect-ai`, `ragas`, LiteLLM, Ollama, or MCP probe).
5. Outbox includes metrics or explicit missing-tool disposition.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship the manifest, prompt contract, skills, and setup docs. Local provider keys, Langfuse credentials, private eval datasets, and private KG contents stay local.

## Cleanup Disposition

Do not delete old `chrono-plugin-ai-engineer` assets until the current specialist, manifest, catalog, and live dispatch proof cover every required tool or mark it optional/deprecated.
