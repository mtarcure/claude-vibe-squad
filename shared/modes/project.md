---
name: project
version: 1.1
primary_mode_namespace: coding
status: active
phases: 8
---

# Mode: Project

For building, refactoring, or shipping software. Chrono controls the workflow, then dispatches the best specialist to the mapped model lead.

## Capabilities

`capability_state` is **derived** and machine-checked by `bin/validate-capabilities.sh` (not hand-set), so this index stays honest by construction. Cards live in `shared/capabilities/project/`.

| Capability | State | When |
|---|---|---|
| [Backend service / API (server, persistence, data flows)](../capabilities/project/backend-service-api.md) | `live` | headless server / API / data-flow — protocol, persistence, concurrency |
| [Data pipeline (ETL / analytics / ML-wiring)](../capabilities/project/data-pipeline.md) | `live` | ETL / analytics plumbing, or wire data into an ML/serving system |
| [AI / LLM application (agents · RAG · tool-use · evals)](../capabilities/project/ai-llm-application.md) | `live` | ship an AI-enabled product — agents, RAG, tool-use, eval harnesses |
| [Smart-contract / web3 BUILD — EVM/Solidity](../capabilities/project/smart-contract-web3.md) | `live` | author/test/deploy EVM/Solidity contracts (non-bounty) |
| [Platform / release (CI · IaC · release rails)](../capabilities/project/platform-release.md) | `live` | CI/CD, IaC, release rails, production reliability |
| [Self-extension — MCP servers · plugins · skills · agents](../capabilities/project/self-extension-agent-tooling.md) | `live` | build or change the agent/tool platform itself |
| [Web application (browser UI / SaaS)](../capabilities/project/web-app.md) | `needs_tool` | browser-facing app / SaaS UI — browser/design/deploy MCPs catalog-absent |
| [Systems / low-level (cross-arch · SIMD · runtime)](../capabilities/project/systems-low-level.md) | `needs_tool` | cross-arch / SIMD / runtime — build+emulation toolchain not cataloged |

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 0 | Scope audit | Chrono direct |
| 1 | Requirements | `product-manager`, `architect` |
| 2 | Design | `architect`, `security-analyst` when security-touching |
| 3 | Plan | `planner` |
| 4 | Build | `backend-engineer`, `frontend-engineer`, `ui-engineer`, `devops-engineer`, `systems-engineer`, `ai-engineer`, `smart-contract-engineer` as needed |
| 5 | Review | `code-reviewer`, `skeptic` |
| 6 | Test | `test-engineer`, `performance-optimizer` when relevant |
| 7 | Release notes | `technical-writer`, `vibecoding-check` |

## Dispatch Notes

- Use `source_namespace: coding` for code specialists, but do not infer the model lead from that namespace.
- Security-touching design, auth, privacy, secrets, or public release work requires review from a different model family.
- Only one writer owns a file path at a time.
- Run `vibecoding-check` before declaring the mode complete.

## Gates

- Operator approval before implementing a broad design.
- Operator approval before destructive changes, credential changes, dependency trust changes, public release actions, or force pushes.
- Mandatory multi-model review for security, privacy, auth, release, and high-blast-radius changes.
