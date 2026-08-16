---
name: parity-probe
description: Run representative capability smoke tasks through the ordinary VibeSquad board after lane, adapter, native-CLI, or utility-MCP changes.
---

# Run the provider parity probe

Use the existing Markdown task board. This skill is an operator checklist, not a second runner, receipt format, or capability catalog.

## Procedure

1. Dispatch an ordinary Project or Bounty task through `shared/routing.md`. Never invoke a provider CLI directly from this skill.
2. For each changed family, choose a representative specialist whose declared surface contains the capability being checked.
3. Require the task to write its normal artifact and completion envelope. When relevant, have it execute one meaningful declared local CLI or utility MCP operation and one harmless negative check for an undeclared operation.
4. For Kimi, keep utility MCP calls on the main lead's reviewed allowlist; native Agent children remain MCP-free.
5. Accept the smoke result only when the normal board receipt, artifact, envelope, and focused test agree. Configuration, PATH output, or a listed tool alone is not proof that the operation worked.

## Stop conditions

Stop and report the route as unproven when the task fails, the declared surface differs, the operation is denied or unavailable, or the provider requires an unapproved paid or credentialed action. Do not widen credentials, retry through another family, or bypass the board.

Keep private task output and credentials out of tracked files. Record only the concise pass/fail result and the affected family/capability in the phase evidence used for the final repository-wide audit.
