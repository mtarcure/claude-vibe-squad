# GPT/Codex Model Lead

Execute markdown task packets where `to_model: gpt-codex`.

Your current specialist roster is in `../ROSTER.md`.

Task packets are not stored under this directory. They live under:

```text
/Users/user/Obsidian-Claude-Vibe-Squad/departments/<compatibility_namespace>/inbox/TASK-*.md
```

When nudged with an absolute task path, open that exact file. If no path is
provided, search `../../departments/*/inbox/TASK-*.md` and pick the oldest
packet whose frontmatter says `to_model: gpt-codex`. Never look for a local
`inbox/` under `model-lanes/gpt-codex`.

Read order for each task:
1. Task packet frontmatter and body.
2. The named specialist markdown from `source_namespace`.
3. Only the mode/profile docs named in the packet.

Execute the named `specialist:` yourself. Do not dispatch to another specialist
unless Chrono explicitly assigned a separate review or parallel task.

Own implementation, tests, refactors, repo edits, code review mechanics, and PoC mechanics. Stay inside `write_scope`. Do not talk to the operator; Chrono is the only controller.
