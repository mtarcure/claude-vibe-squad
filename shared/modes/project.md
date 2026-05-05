---
name: project
version: 1.1
primary_mode_namespace: coding
status: active
phases: 8
---

# Mode: Project

For building, refactoring, or shipping software. Chrono controls the workflow, then dispatches the best specialist to the mapped model lead.

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
