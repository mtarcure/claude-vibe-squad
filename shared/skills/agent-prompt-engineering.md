---
name: agent-prompt-engineering
status: authored
---

# Agent Prompt Engineering

Design the system prompt and instruction set for a conversational or task agent so behavior is reliable, scoped, and testable.

## Steps
1. State the agent's role, goals, and hard boundaries (what it must never do) before writing prose.
2. Structure the prompt: role, capabilities, tools/handoffs, output contract, refusal/escalation rules — in that priority order.
3. Specify tool-use and grounding rules explicitly; forbid fabrication and require citing/handing off when knowledge is absent.
4. Add few-shot or format exemplars only where they change behavior; keep the prompt as short as reliability allows.
5. Define an eval set of representative and adversarial turns; iterate the prompt against it rather than against a single demo.

## Acceptance
- Role, boundaries, and output contract are explicit and prioritized.
- Grounding/refusal rules forbid fabrication and define escalation.
- The prompt is validated against an eval set, not a one-off transcript.
