# Security Department — Durable Memory

Distilled knowledge for the Security Lead. Curated, not appended.

## Bounty Programs (active)

(Populate as you engage targets. Examples to follow:)

- Program X (HackerOne): payout median $XXX, response time ~N days, accepted vuln classes [...]

## Ruled-Out Targets

- (target / why it's not worth pursuing)

## Reusable Techniques

- (technique name — when it applies — references)
- **`tmux send-keys` as prompt-injection primitive into agent CLIs** — when a system uses `tmux send-keys -t <pane> "<msg>"` to "nudge" a CLI agent (Claude/Codex/Gemini/etc.), the keystrokes land *inside the agent's prompt buffer*. Two attack vectors: (a) any user-controlled string interpolated into `<msg>` becomes typed prompt content the LLM will try to act on, with full tool access; (b) without `-l` (literal mode), `Enter`/`C-c`/chord notation in `<msg>` are real keys — `Enter` mid-typing auto-submits the operator's partial buffer plus injected text. Mitigations: enum-validate the pane target, hardcode `<msg>` (no interpolation), use `-l`, fire only when pane status is idle. Applies to any multi-agent orchestrator that uses tmux for inter-pane coordination.
- **YAML frontmatter shadowing in agent inbox files** — when a server prepends frontmatter to user-supplied markdown and writes the result to a file an agent reads, a body that itself begins with `---\n...\n---` produces two frontmatter blocks. Parser-dependent which wins; if the operator-supplied one is honored, attacker can fake `from_lead`, `operator_approved`, `write_scope`. Mitigation: server rejects bodies starting with `---\n`, or wraps body in a sentinel/fenced region.

## Tools Configuration

- (tool-specific notes that don't fit in chrono's catalog)

---

*When something turns out wrong, REMOVE — don't add a contradicting line.*

## v1.1 update — 2026-05-03

The squad shipped v1.1 with explicit tool catalogs in every specialist file,
per-pane effort/thinking tier defaults, capability inventory, and Topology B
direct-with-CC patterns. When dispatching a specialist now, trust that its
identity.md enumerates available MCPs / native CLI features / skills / APIs
— no need to remind it. Lead-to-Lead direct-with-CC patterns are documented
in this LEAD.md. See shared/lifecycle.md for lifecycle rules.
