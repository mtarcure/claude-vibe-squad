---
name: bounty-researcher
description: "Thin Grok adapter for bounty-researcher; canonical brief is authoritative."
prompt_mode: full
permission_mode: default
agents_md: true
model: grok-4.6
mcpInheritance:
  named:
    - chrono-vault
---

Load and follow the specialist system prompt in the sibling file
`../prompts/bounty-researcher.md`.

The adjacent `bounty-researcher.yaml` file retains Vibe Squad's generated capability
projection for repository-side validation; this Markdown definition is the
native Grok discovery surface.
