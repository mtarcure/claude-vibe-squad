# Security Department — Durable Memory

Distilled knowledge for the security namespace. Curated, not appended.

Governed by `shared/memory-discipline.md`.

## Bounty Programs (active)

(Populate as you engage targets. Examples to follow:)

- Program X (HackerOne): payout median $XXX, response time ~N days, accepted vuln classes [...]

## Ruled-Out Targets

- (target / why it's not worth pursuing)

## Reusable Techniques

- (technique name — when it applies — references)
- **`tmux send-keys` as prompt-injection primitive into agent CLIs** — when a system uses `tmux send-keys -t <pane> "<msg>"` to "nudge" a CLI agent (Claude/Codex/Gemini/etc.), the keystrokes land *inside the agent's prompt buffer*. Two attack vectors: (a) any user-controlled string interpolated into `<msg>` becomes typed prompt content the LLM will try to act on, with full tool access; (b) without `-l` (literal mode), `Enter`/`C-c`/chord notation in `<msg>` are real keys — `Enter` mid-typing auto-submits the operator's partial buffer plus injected text. Mitigations: enum-validate the pane target, hardcode `<msg>` (no interpolation), use `-l`, fire only when pane status is idle. Applies to any multi-agent orchestrator that uses tmux for inter-pane coordination.
- **YAML frontmatter shadowing in agent inbox files** — when a server prepends frontmatter to user-supplied markdown and writes the result to a file an agent reads, a body that itself begins with `---\n...\n---` produces two frontmatter blocks. Parser-dependent which wins; if the operator-supplied one is honored, attacker can fake `from_lead`, `operator_approved`, `write_scope`. Mitigation: server rejects bodies starting with `---\n`, or wraps body in a sentinel/fenced region.
- **Authed-browser pre-flight gate on firsthand-bounty tasks** — for any task that depends on the operator's persistent CDP browser (port 9222 per `reference_bounty_browser_session_state.md`), run raw CDP pre-flight with `curl http://localhost:9222/json/list` and verify non-blank page titles BEFORE dispatching scout. If the endpoint is unreachable or only blank tabs are visible, the authenticated browser is not available — abort, write a `status: blocked` outbox response, surface to Chrono. Do NOT spawn a fresh Playwright/Chrome instance or rely on MCP `list_pages` to "fix" it (clean profile = zero cookies = defeats the auth). The pre-flight lives at the Lead level, not inside the scout specialist, so a subagent never burns its context window on unauthed login walls or fabricates facts from anonymous-view scrapes. First triggered on TASK-2026-05-03-1524-1fe639a0.
- **Raw-CDP DOM extraction pattern (resolved blocker from `1fe639a0`)** — when the in-pane MCP browser tools (chrome-devtools-mcp, playwright-mcp) are attached to a fresh Chrome instead of the operator's authed Chrome at port 9222, bypass them entirely. Pattern: `curl http://localhost:9222/json` → for each `type=page` tab matching the target domain(s), open a WebSocket to its `webSocketDebuggerUrl` → send `Runtime.evaluate` with `expression: "document.body.innerText", returnByValue: true, awaitPromise: true` → save the returned `result.result.value` to disk. Use `uv run` shebang with inline PEP 723 deps (`httpx>=0.28`, `websockets>=12`) so no venv churn. **Strictly read-only**: never call `Page.navigate` or `Target.createTarget` (would create a new tab, violating `feedback_no_new_tabs_in_operator_browser.md`). After capture, dispatch `Task(subagent_type=scout)` with file paths for synthesis — Lead does the raw acquisition, scout does the interpretation. Reference impl: `/tmp/cdp_extract.py` modeled on `scripts/python/browser_keep_alive.py`. Resolved on TASK-2026-05-04-1459-b1211a1a.
- **Workflow-design adversarial reviews need scout-frame + threat-modeler-frame in parallel, not serial** — TASK-2026-05-03-1951-53d3c085 (Phase 5 mode-architecture restructure review): scout-frame caught operationally-load-bearing gaps the threat-modeler missed (program-meta signals, authorized-methods/rate-limits unspec'd in Phase 2 outputs, Phase 0 candidate pre-filter); threat-modeler-frame caught trust-boundary issues the scout missed (Chrono prompt-injection from program descriptions, NDA-program-identity leakage via Research's external query MCPs, audit-attribution muddiness across three overlapping owners). Convergent only on cross-ref drift, cleanup-matrix gap, MCP-vs-raw-CDP contradiction. Conclusion: for any review of a workflow / process / mode-architecture change, fan out BOTH frames in parallel as separate subagents — single-frame review will systematically miss half the failure modes.
- **Phase-renumbering changes are mechanical-edit-heavy across the whole instructional surface** — when a mode's phase numbers shift by N, count the dependents: bounty mode-profile section headers (7 files), security-specialist `When to dispatch` sections (6 files), shared/specialists/skeptic.md (1 file), bounty.md hard-gates block (positional names), chrono/operator-setup.md routing table, SPECIALIST-INDEX common-confusion table, lifecycle.md any-phase-cite. Always recommend semantic gate naming (`phase_program_intel_to_recon_gate`) over positional (`phase_2_to_3`) so future renumberings don't silently drop or re-anchor gates. Specialist files and sub-profiles consistently get omitted from cross-ref scope lists — surface them explicitly in every reno-ish review.

## Tools Configuration

- (tool-specific notes that don't fit in chrono's catalog)

---

*When something turns out wrong, REMOVE — don't add a contradicting line.*

## Tool-catalog update — 2026-05-03

The squad shipped explicit tool catalogs in every specialist file,
per-pane effort/thinking tier defaults, capability inventory, and Topology B
direct-with-CC patterns. When dispatching a specialist now, trust that its
identity.md enumerates available MCPs / native CLI features / skills / APIs
— no need to remind it. Lead-to-Lead direct-with-CC patterns are documented
in this LEAD.md. See shared/lifecycle.md for lifecycle rules.
