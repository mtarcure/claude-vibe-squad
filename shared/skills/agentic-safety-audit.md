---
name: agentic-safety-audit
status: authored
---

# Agentic Safety Audit

Audit an LLM agent system for the failure modes that only exist because a model is in the control loop.

## Steps
1. Map the trust boundary: which inputs reach the model, which of those are attacker-influenced (web pages, files, tool output, other agents), and which model outputs become actions.
2. Enumerate the action surface — every tool, shell, network call, file write, and spend the agent can reach, plus everything those actions can reach transitively.
3. Test prompt injection at each untrusted input: can retrieved content redirect the agent, exfiltrate context, or invoke a tool the operator did not intend? Tool output is untrusted input.
4. Check the confused-deputy path: does the agent act with credentials or scope broader than the requester's own authority?
5. Verify gates are enforced by the harness, not by instructions. An approval that the model can talk itself past is not a gate; test it with an adversarial prompt.
6. Check scope containment: write scope, network scope, and working directory. Prove containment with a real denied attempt, not by reading the config.
7. Audit memory and state: can untrusted content be written into durable memory and later recalled as if it were operator instruction? Check that recalled memory is labelled untrusted at the point of use.
8. Check the multi-agent edges: a subagent's output re-entering a parent as trusted context is an injection path, and delegation frequently widens scope silently.
9. Review failure behavior: on tool error, timeout, or refusal, does the agent stop, or does it improvise a less-safe path?
10. Record every finding with the concrete prompt or input that triggers it.

## Acceptance
- The trust boundary and full action surface are enumerated, including transitive reach.
- Injection was actually attempted at each untrusted input, with the payloads recorded.
- Every claimed gate was tested adversarially and observed to hold or fail.
- Containment claims rest on an observed denial, not on configuration text.
- Memory write-then-recall and agent-to-agent edges are covered explicitly.
