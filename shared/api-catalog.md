# Squad API & Feature Catalog

Verified-from-Capability-Inventory list of every API, native CLI feature, and MCP available to the squad. Specialist files (`departments/*/specialists/*.md`) may only cite entries marked `verified: yes` here. Entries marked `needs-research` are current research backlog tasks for harness-optimizer and do not block specialist authoring.

> **Authoritative catalog.** This file (`shared/api-catalog.md`) is the **single source of truth** for tool/MCP/API citations — `bin/validate-specialists.sh` gates specialist `required_tools` / `preferred_tools` against the `verified: yes` entries here. `shared/tool-catalog.md` is a convenience quick-reference index only; **if the two disagree, this file wins** and the index must be corrected to match.

Last full inventory: 2026-05-02 (`_state/capability-inventory-2026-05-02.md`)
Tilde-path fix applied to claude chrono-* MCPs: 2026-05-03 (`_state/incident-2026-05-03-claude-mcp-tilde.md`)

---

## Schema

Every entry in this catalog uses this shape:

```markdown
### <feature/MCP/API name>
- url: <URL or N/A>
- access: <Pro/Max/Team/Enterprise/Public/Subscription>
- specialists: <comma-separated list of specialist names>
- verified: yes / no / needs-research
- last_checked: <YYYY-MM-DD>
- test_reference: <command or doc-citation that proves this works — REQUIRED if verified: yes>
- notes: <brief usage notes>
- research_task: <if needs-research, what investigation is needed>
```

---

## 1. Anthropic / Claude

Claude Code CLI flags — verified live via `claude --help` capture and targeted live-flag tests on 2026-05-02. Subscription auth (Max plan) used via env-drop pattern.

### claude --effort {low,medium,high,xhigh,max}
- url: N/A (CLI flag)
- access: Max
- specialists: all claude-pane specialists (chrono, security, sysmgmt panes)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `env -u ANTHROPIC_API_KEY claude --effort xhigh -p "echo test"` returned exit 0 with successful prompt completion (model produced an "★ Insight" block)
- notes: Reasoning-effort selector. `xhigh` and `max` reserved for hardest specialist work; `medium` is sane default for routine.

### claude --model <model>
- url: N/A (CLI flag)
- access: Max
- specialists: all claude-pane specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `env -u ANTHROPIC_API_KEY claude --model opus -p "ok"` returned exit 0 with model output
- notes: Accepts aliases (`opus` / `sonnet` / `haiku`) and full names (e.g. `claude-sonnet-4-6`).

### claude --mcp-config <configs...>
- url: N/A (CLI flag)
- access: Max
- specialists: spawn-specialist harness, security-lead (for per-spawn MCP scoping)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` lines describing flag accept JSON files OR JSON strings, space-separated
- notes: Used to scope MCP set per-launch. Combine with `--strict-mcp-config` to ignore other configs.

### claude --strict-mcp-config
- url: N/A (CLI flag)
- access: Max
- specialists: spawn-specialist harness
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` text "Only use MCP servers from --mcp-config, ignoring all other MCP configurations"
- notes: Pairs with `--mcp-config`. Use when a specialist must be deterministically scoped to a tool subset.

### claude --permission-mode {acceptEdits,auto,bypassPermissions,default,dontAsk,plan}
- url: N/A (CLI flag)
- access: Max
- specialists: spawn-specialist harness, all headless invocations
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` enum capture
- notes: Headless writes need `acceptEdits` (or `bypassPermissions` for fully unattended).

### claude --add-dir <directories...>
- url: N/A (CLI flag)
- access: Max
- specialists: any specialist that needs filesystem access outside cwd
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` capture
- notes: Whitelist additional directories for file access.

### claude --worktree [name] (alias -w)
- url: N/A (CLI flag)
- access: Max
- specialists: feature-dev, executing-plans, refactor-cleaner
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` text "Create a new git worktree for this session"
- notes: Native worktree spawn — preferred over manual `git worktree add` for isolated specialist work.

### claude -p / --print
- url: N/A (CLI flag)
- access: Max
- specialists: all headless dispatch (spawn-specialist.sh, dispatch-toolkit.sh)
- verified: yes
- last_checked: 2026-05-02
- test_reference: Used in test invocations above (`claude -p "ok"`)
- notes: Non-interactive mode. Required for any subprocess dispatch.

### claude --append-system-prompt <prompt>
- url: N/A (CLI flag)
- access: Max
- specialists: spawn-specialist harness (used to inject specialist identity)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` capture
- notes: Core mechanism for specialist-identity injection per-spawn.

### claude --allowedTools / --allowed-tools <tools...>
- url: N/A (CLI flag)
- access: Max
- specialists: spawn-specialist harness (least-privilege per role)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` capture
- notes: Restrict tool set for a launch. Pair with `--strict-mcp-config` for deterministic specialist sandboxing.

### claude --agents <json>
- url: N/A (CLI flag)
- access: Max
- specialists: dispatching-parallel-agents harness
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` capture; "Defines custom agents"
- notes: Inline agent definitions. Useful for fan-out where roles aren't already on disk.

### claude --bare
- url: N/A (CLI flag)
- access: Max
- specialists: minimal-mode probes (parity-probe), capability inventory
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` capture; "Minimal mode skipping hooks/LSP/plugins/keychain/CLAUDE.md auto-discovery"
- notes: Reproducibility tool — strips host config to isolate behavior under test.

### claude --json-schema
- url: N/A (CLI flag)
- access: Max
- specialists: structured-output specialists, validators
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` capture
- notes: Constrain headless output to a schema for downstream parsing.

### claude --from-pr
- url: N/A (CLI flag)
- access: Max
- specialists: code-reviewer, ultrareview workflow
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` capture
- notes: Seed session from a PR diff.

### claude --ide
- url: N/A (CLI flag)
- access: Max
- specialists: IDE-bound interactive sessions only
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` text "Auto-connect to IDE if exactly one available"
- notes: Not used in headless squad pipelines.

### claude --chrome / --no-chrome
- url: N/A (CLI flag)
- access: Max
- specialists: claude-in-chrome integration only
- verified: yes
- last_checked: 2026-05-02
- test_reference: `claude --help` capture
- notes: Toggles Claude-in-Chrome bridge per session.

### claude ultrareview (subcommand, NOT a flag)
- url: N/A (subcommand)
- access: Max (cloud-hosted, requires auth)
- specialists: code-reviewer (Coding)
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `claude --help` Commands block lists `ultrareview` — "Run a cloud-hosted multi-agent code review of the current branch (or a PR number / base branch) and print the findings"
- notes: It is a SUBCOMMAND (`claude ultrareview ...`), not a `--ultrareview` flag. Spec drift fixed during Capability Inventory.

### claude mcp / claude plugin / claude doctor / claude install / claude auth / claude agents
- url: N/A (subcommands)
- access: Max
- specialists: harness-optimizer, memory-curator (audit), bootstrap helpers
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `claude --help` Commands block
- notes: Management surface — generally invoked by harness scripts, not specialists directly.

### Claude Design (claude.ai/design)
- url: https://claude.ai/design
- access: Max
- specialists: image-designer (Content-Engineer), ui-engineer (Coding)
- verified: yes
- last_checked: 2026-05-02
- test_reference: claude.ai/design web access via Max plan
- notes: Web-app surface for design generation. Operator has Max access.

### Claude Computer Use API
- url: https://docs.anthropic.com/en/docs/build-with-claude/computer-use
- access: API tier (uncertain via CLI)
- specialists: scraping-engineer (potentially)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: verify access path from claude CLI vs API-only — does `claude` CLI expose computer use, or is it Claude API SDK only?
- notes: Operator already has computer-use MCP in this very session. Need to confirm CLI-side access for squad use.

---

## 2. OpenAI / Codex

Codex CLI flags — verified live via `codex --help` capture and targeted live-flag tests on 2026-05-02. Subscription auth (ChatGPT Plus) used via env-drop pattern.

### codex -c <key=value>
- url: N/A (CLI flag)
- access: Subscription (ChatGPT login)
- specialists: all codex-pane specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `codex --help` capture; dotted-path nested override; value parsed as TOML with literal-string fallback
- notes: Generic config override. Most-used: `-c model_reasoning_effort=<level>`.

### codex -c model_reasoning_effort=high
- url: N/A (CLI config override)
- access: Subscription
- specialists: high-effort coding specialists (architect, code-reviewer)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `env -u OPENAI_API_KEY codex exec -c model_reasoning_effort=high "echo test"` printed `reasoning effort: high` in startup banner and returned exit 0
- notes: This is the codex equivalent of claude's `--effort`. Confirmed via banner output.

### codex -m / --model <MODEL>
- url: N/A (CLI flag)
- access: Subscription
- specialists: all codex-pane specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `codex --help` capture
- notes: Model selector.

### codex -s / --sandbox <SANDBOX_MODE> {read-only,workspace-write,danger-full-access}
- url: N/A (CLI flag)
- access: Subscription
- specialists: all codex-pane specialists doing file writes
- verified: yes
- last_checked: 2026-05-02
- test_reference: `codex --help` enum capture
- notes: REQUIRED `workspace-write` for outbox writes. Encoded in `bin/launch-squad.sh` and the GPT/Codex model-lane prompt.

### codex -a / --ask-for-approval <APPROVAL_POLICY> {untrusted,on-request,never}
- url: N/A (CLI flag)
- access: Subscription
- specialists: headless dispatch
- verified: yes
- last_checked: 2026-05-02
- test_reference: `codex --help` enum capture
- notes: `on-failure` is deprecated. Use `never` for fully-unattended specialist runs.

### codex --add-dir <DIR> / -C / --cd <DIR>
- url: N/A (CLI flags)
- access: Subscription
- specialists: cross-directory codex specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `codex --help` capture
- notes: Filesystem-scope expansion.

### codex --search
- url: N/A (CLI flag)
- access: Subscription
- specialists: research, large-context-analyst (when codex is the runner)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `codex --help` text "Enables native Responses web_search tool"
- notes: Native web search via OpenAI Responses API.

### codex --enable <FEATURE> / --disable <FEATURE>
- url: N/A (CLI flag)
- access: Subscription
- specialists: feature-toggle harness
- verified: yes
- last_checked: 2026-05-02
- test_reference: `codex --help` capture; equivalent to `-c features.<name>=true|false`
- notes: Feature flag toggles.

### codex exec (alias e)
- url: N/A (subcommand)
- access: Subscription
- specialists: all headless codex dispatch
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `codex --help` Commands block "Run Codex non-interactively"
- notes: Primary subcommand for spawn-specialist.sh codex path.

### codex review
- url: N/A (subcommand)
- access: Subscription
- specialists: code-reviewer
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `codex --help` Commands block "Run a code review non-interactively"
- notes: Native code-review subcommand. Used in multi-model code-review fanout.

### codex mcp / codex mcp-server
- url: N/A (subcommands)
- access: Subscription
- specialists: harness-optimizer (audit), bootstrap helpers
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `codex --help` Commands block; `codex mcp-server` = "Start Codex as an MCP server (stdio)"
- notes: Codex can also act as an MCP server.

### codex plugin
- url: N/A (subcommand)
- access: Subscription
- specialists: harness-optimizer
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `codex --help` Commands block "Manage Codex plugins"
- notes: Codex plugin management surface.

### codex resume / codex fork
- url: N/A (subcommands)
- access: Subscription
- specialists: any codex specialist resuming a long-running task
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `codex --help` Commands block (session continuation)
- notes: Session continuation primitives.

### codex sandbox
- url: N/A (subcommand)
- access: Subscription
- specialists: bounty-sandbox-provision workflows
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `codex --help` Commands block "Run commands within a Codex-provided sandbox"
- notes: Wraps a command in codex's sandbox without entering a chat.

### codex --oss / --local-provider {lmstudio,ollama}
- url: N/A (CLI flag)
- access: Public (local provider)
- specialists: local-model-experiment-flow specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `codex --help` capture
- notes: Routes to local OSS providers instead of OpenAI cloud.

### codex cloud (EXPERIMENTAL)
- url: N/A (subcommand)
- access: Subscription
- specialists: async-task workflows (potential)
- verified: yes-as-subcommand (existence) / needs-research (operator-tier access)
- last_checked: 2026-05-02
- test_reference: `codex --help` Commands block; tagged `[EXPERIMENTAL]`
- research_task: verify access from operator's ChatGPT Plus tier — is async cloud-task surface gated to higher tiers?
- notes: Subcommand exists; operator-tier-gated capabilities unconfirmed.

### Codex Cloud Agents (async)
- url: https://chat.openai.com/codex (web)
- access: Subscription (ChatGPT Plus or higher)
- specialists: long-running coding tasks (if available)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: verify async-agent access at operator's ChatGPT Plus tier; identify CLI dispatch path if any
- notes: Distinct from `codex cloud` subcommand (which is local-side).

### Codex native macOS computer use
- url: https://platform.openai.com/docs/guides/computer-use
- access: API/Plus tier (uncertain)
- specialists: test-engineer (potential)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: verify access path from codex CLI; is computer use a CLI surface or API-only?
- notes: Operator has computer-use MCP in claude session — codex equivalent unconfirmed.

---

## 3. Google / Gemini

Gemini CLI flags — verified live via `gemini --help` capture on 2026-05-02. Subscription auth (personal OAuth) used via env-drop pattern.

### gemini -m / --model <model>
- url: N/A (CLI flag)
- access: Subscription (personal OAuth)
- specialists: all gemini-pane specialists (Content)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: Use `gemini-3.1-pro-preview` for thinking-capable model. `--thinking` flag does NOT exist (see entry below).

### gemini --thinking
- url: N/A
- access: N/A
- specialists: N/A
- verified: no
- last_checked: 2026-05-02
- test_reference: `env -u GEMINI_API_KEY -u GOOGLE_API_KEY gemini --help | grep -i -E "thinking|reasoning|effort"` returned NO matches
- notes: **Flag does NOT exist.** Thinking is implicit at model level. Use `--model gemini-3.1-pro-preview` for thinking-capable model. Do NOT cite this flag in any specialist file.
- research_task: confirm whether thinking-mode is implicit-per-model (`gemini-3.1-pro-preview` always thinks) or whether a non-help-documented mechanism (`-c` flag, settings.json key) toggles it

### gemini -p / --prompt <text>
- url: N/A (CLI flag)
- access: Subscription
- specialists: all headless gemini dispatch
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: Non-interactive (headless) mode.

### gemini -i / --prompt-interactive <text>
- url: N/A (CLI flag)
- access: Subscription
- specialists: hybrid interactive workflows
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: Execute then drop into interactive.

### gemini -w / --worktree [name]
- url: N/A (CLI flag)
- access: Subscription
- specialists: feature-dev workflows on gemini pane
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` text "Start Gemini in a new git worktree"
- notes: Native worktree.

### gemini -y / --yolo
- url: N/A (CLI flag)
- access: Subscription
- specialists: fully-unattended dispatch
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: Auto-approve all actions. Use with caution.

### gemini --approval-mode {default,auto_edit,yolo,plan}
- url: N/A (CLI flag)
- access: Subscription
- specialists: headless dispatch
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` enum capture
- notes: Granular approval policy.

### gemini --include-directories <dirs...>
- url: N/A (CLI flag)
- access: Subscription
- specialists: cross-dir specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: Like `--add-dir` on other CLIs.

### gemini --allowed-mcp-server-names <array>
- url: N/A (CLI flag)
- access: Subscription
- specialists: spawn-specialist harness (when MCPs eventually installed on gemini)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: Per-launch MCP scoping. Currently moot — gemini has zero MCPs configured (Task 6 will install Hybrid Path A set).

### gemini -e / --extensions <list>
- url: N/A (CLI flag)
- access: Subscription
- specialists: gemini-extension-using specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: Gemini's extension surface (analogous to claude plugins).

### gemini --policy <files> / --admin-policy <files>
- url: N/A (CLI flag)
- access: Subscription
- specialists: governance/security harness
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: Policy-file injection.

### gemini --acp / --experimental-acp
- url: N/A (CLI flag)
- access: Subscription
- specialists: ACP-bridge workflows
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` capture
- notes: ACP (Agent Communication Protocol) mode.

### gemini -o / --output-format {text,json,stream-json}
- url: N/A (CLI flag)
- access: Subscription
- specialists: structured-output specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `gemini --help` enum capture
- notes: Structured output for downstream parsing.

### gemini mcp {add,remove,list,enable,disable}
- url: N/A (subcommand)
- access: Subscription
- specialists: harness-optimizer (Task 6 will use `gemini mcp add` for Hybrid Path A install)
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `gemini mcp --help` Commands block
- notes: MCP management surface.

### gemini extensions
- url: N/A (subcommand)
- access: Subscription
- specialists: harness-optimizer
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `gemini --help` Commands block
- notes: Extension management.

### gemini skills
- url: N/A (subcommand)
- access: Subscription
- specialists: harness-optimizer
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `gemini --help` Commands block "Manage agent skills"
- notes: Native skill surface.

### gemini hooks
- url: N/A (subcommand)
- access: Subscription
- specialists: harness-optimizer
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `gemini --help` Commands block
- notes: Hook management.

### gemini gemma (local Gemma model routing)
- url: N/A (subcommand)
- access: Subscription / local
- specialists: local-model-experiment-flow specialists
- verified: yes-as-subcommand
- last_checked: 2026-05-02
- test_reference: `gemini --help` Commands block "Manage local Gemma model routing"
- notes: Routes to local Gemma. Squad-relevant for offline/local fallback.

### Nano Banana Pro / Nano Banana 2
- url: https://aistudio.google.com (likely)
- access: Subscription (uncertain)
- specialists: image-designer (potential)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: identify whether accessed via `gemini` CLI subcommand, via Google AI Studio web only, or via API
- notes: Image-gen models. Access path unconfirmed.

### Veo 3
- url: https://veo.google
- access: Subscription (uncertain)
- specialists: video-director (video)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: identify access path — gemini CLI vs API vs web only
- notes: Video generation.

### Imagen
- url: https://imagen.research.google
- access: Subscription (uncertain)
- specialists: image-designer
- verified: needs-research
- last_checked: 2026-05-02
- research_task: identify access path
- notes: Image generation.

### Google Search grounding
- url: N/A (model-side)
- access: Subscription (likely implicit per model)
- specialists: research
- verified: needs-research
- last_checked: 2026-05-02
- research_task: confirm built into `gemini-3.1-pro-preview` by default; verify with sample grounded query
- notes: Likely implicit. Critical for content-pane research after Hybrid Path A omits chrono-research-arsenal on gemini.

### Jules (Google coding agent)
- url: https://jules.google
- access: Subscription (uncertain)
- specialists: coding workflows (potential)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: investigate — what is it, integration paths, CLI surface
- notes: Coding agent product.

### Flow (Google video tool)
- url: https://flow.google
- access: Subscription (uncertain)
- specialists: video-director (video)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: investigate scope and integration paths
- notes: Video tool product.

### NotebookLM
- url: https://notebooklm.google
- access: Subscription
- specialists: research, large-context-analyst (potential)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: investigate programmatic access path (CLI / API / web only)
- notes: Notebook research product. Web is verified accessible; CLI/API access unconfirmed.

### Antigravity (Google IDE-agent)
- url: https://antigravity.google
- access: Subscription (uncertain)
- specialists: coding workflows (potential alt CLI)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: investigate — possible alternate CLI for implementation work?
- notes: IDE-agent product.

---

## 4. Moonshot / Kimi

Kimi CLI flags — verified live via `kimi --help` capture on 2026-05-02. Subscription auth (`kimi login`) is OAuth-only; no env-drop needed.

### kimi --print
- url: N/A (CLI flag)
- access: Subscription (`kimi login`)
- specialists: all headless kimi dispatch (research pane)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` text "Run in print mode (non-interactive)"
- notes: Headless mode.

### kimi --quiet
- url: N/A (CLI flag)
- access: Subscription
- specialists: structured-output kimi specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture; alias for `--print --output-format text --final-message-only`
- notes: Compact output mode.

### kimi --thinking / --no-thinking
- url: N/A (CLI flag)
- access: Subscription
- specialists: research, deep-thinking specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` text "Enable thinking mode. Default: default thinking mode set in config file."
- notes: Explicit thinking-mode toggle (kimi has it, gemini does NOT).

### kimi -p / --prompt <text> (alias -c / --command)
- url: N/A (CLI flag)
- access: Subscription
- specialists: all headless kimi dispatch
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Prompt input.

### kimi -y / --yolo / --yes
- url: N/A (CLI flag)
- access: Subscription
- specialists: fully-unattended dispatch
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Auto-approve all actions.

### kimi --add-dir <directory>
- url: N/A (CLI flag)
- access: Subscription
- specialists: cross-dir kimi specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Filesystem-scope expansion.

### kimi -w / --work-dir <directory>
- url: N/A (CLI flag)
- access: Subscription
- specialists: kimi specialists working in non-cwd directory
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Working-directory override.

### kimi -m / --model <text>
- url: N/A (CLI flag)
- access: Subscription
- specialists: model-routing specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Model selector.

### kimi --mcp-config-file <file> (repeatable)
- url: N/A (CLI flag)
- access: Subscription
- specialists: spawn-specialist harness (kimi path)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Per-launch MCP scoping.

### kimi --mcp-config <text> (JSON string, repeatable)
- url: N/A (CLI flag)
- access: Subscription
- specialists: spawn-specialist harness
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: JSON-string MCP config.

### kimi --skills-dir <directory> (repeatable)
- url: N/A (CLI flag)
- access: Subscription
- specialists: harness-optimizer (skill-set scoping)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` text "Overrides default discovery"
- notes: Override skill-discovery roots.

### kimi --agent {default,okabe}
- url: N/A (CLI flag)
- access: Subscription
- specialists: persona-specific kimi dispatch
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Builtin agent selection.

### kimi --agent-file <file>
- url: N/A (CLI flag)
- access: Subscription
- specialists: spawn-specialist harness (custom-agent path)
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Custom agent specification.

### kimi --max-steps-per-turn <N>
- url: N/A (CLI flag)
- access: Subscription
- specialists: long-running kimi specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture; INTEGER ≥ 1
- notes: Step-budget per turn.

### kimi --max-retries-per-step <N>
- url: N/A (CLI flag)
- access: Subscription
- specialists: harness-optimizer
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture; INTEGER ≥ 1
- notes: Retry budget.

### kimi --max-ralph-iterations <N>
- url: N/A (CLI flag)
- access: Subscription
- specialists: ralph-loop kimi workflows
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` text "Extra iterations after the first turn in Ralph mode. Use -1 for unlimited."
- notes: Ralph-mode iteration cap.

### kimi --afk
- url: N/A (CLI flag)
- access: Subscription
- specialists: long-running unattended dispatch
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture; "AFK mode auto-dismisses AskUserQuestion"
- notes: Auto-dismiss user-question prompts.

### kimi --plan
- url: N/A (CLI flag)
- access: Subscription
- specialists: planner specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` capture
- notes: Start in plan mode.

### kimi --input-format / --output-format {text,stream-json}
- url: N/A (CLI flag)
- access: Subscription
- specialists: structured-IO specialists
- verified: yes
- last_checked: 2026-05-02
- test_reference: `kimi --help` enum capture
- notes: Structured I/O.

### Kimi 300 parallel sub-agents (native)
- url: N/A
- access: Subscription
- specialists: research, large-context-analyst (potentially)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: verify usage pattern; not a CLI flag, may be K2.6 model behavior or runtime/agent-spec capability documented elsewhere
- notes: `--help` exposes `--max-steps-per-turn` and `--max-ralph-iterations` but NO explicit "parallel sub-agent count" flag.

### Kimi 4000 coordinated tool steps
- url: N/A
- access: Subscription
- specialists: research, multi-step kimi specialists
- verified: needs-research
- last_checked: 2026-05-02
- research_task: identify the actual mechanism — config-file key, model-side capability, or marketing claim
- notes: Same status as 300-parallel claim.

### MoonViT vision
- url: https://moonshot.ai (likely)
- access: Subscription (uncertain)
- specialists: vision specialists, screenshot-analysis workflows
- verified: needs-research
- last_checked: 2026-05-02
- research_task: confirm access path (CLI surface vs API)
- notes: Moonshot's vision capability.

---

## 5. xAI / Grok

### Grok-4-fast (2M context)
- url: https://x.ai/api
- access: API (XAI_API_KEY)
- specialists: large-context-analyst, long-context fan-out
- verified: needs-research
- last_checked: 2026-05-02
- research_task: API setup + verify endpoint access; trace `chrono-research-arsenal` MCP code to confirm Grok routing surface
- notes: XAI_API_KEY is plumbed into chrono-research-arsenal and chrono-content-engineer MCPs (per `codex mcp list`). End-to-end invocation path unverified.

### Grok-X integration
- url: https://x.ai
- access: API
- specialists: research (potential)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: investigate full integration surface
- notes: Beyond Grok-4-fast model access — broader xAI product surface.

---

## 6. DeepSeek

### DeepSeek V4-Pro / V4-Flash
- url: https://api.deepseek.com
- access: API (key not yet plumbed)
- specialists: cost-sensitive fan-out, contrarian model voice
- verified: needs-research
- last_checked: 2026-05-02
- research_task: API setup; verify API key plumbing into a chrono MCP; addition to T1/T2 fanout pool
- notes: No DEEPSEEK_API_KEY visible in any MCP env block. Currently unplumbed.

---

## 7. ElevenLabs (chrono-content-engineer)

### ElevenLabs MCP — Scribe transcription, TTS, sound effects, music composition, voice cloning
- url: https://elevenlabs.io
- access: API (ELEVENLABS_API_KEY)
- specialists: voice-narrator, music-composer, sound-designer
- verified: yes for Claude child MCP; not exposed through the current Gemini `chrono-content-engineer` wrapper
- last_checked: 2026-05-02
- test_reference: `claude mcp list` shows `plugin:chrono-content-engineer:elevenlabs` ✓ Connected via `uvx elevenlabs-mcp` (Capability Inventory)
- notes: Full Claude child surface includes speech-to-text, text-to-speech, sound effects, music composition, voice cloning, voice library search, and conversational agents. Do not ask Gemini for `elevenlabs__*` tools unless a live lane schema proves they exist.

---

## 8. Higgsfield (chrono-content-engineer)

### Higgsfield MCP — image/video generation
- url: https://higgsfield.ai
- access: HTTP MCP (auth required)
- specialists: image-designer, video-director (image/video)
- verified: no
- last_checked: 2026-05-02
- test_reference: `claude mcp list` shows `plugin:chrono-content-engineer:higgsfield` ⚠ Needs authentication
- notes: HTTP MCP. Auth not yet completed. Specialists must NOT cite this until auth resolved. Tracked as separate operational task.

---

## 9. chrono MCPs squad-wide

Per-pane verification matrix for each chrono-* family MCP. Claude pane verification is post-2026-05-03 tilde-fix (see `_state/incident-2026-05-03-claude-mcp-tilde.md`).

### chrono-vault MCP
- purpose: KG read/write, durable memory across model leads
- specialists: brand-voice (Content), memory-curator (SysMgmt), memory-curator (SysMgmt), all model leads' memory.md persistence
- verified per pane:
  - chrono pane (claude): yes — test_reference: `claude mcp list` post-2026-05-03 tilde-fix shows ✓ Connected
  - security pane (claude): yes — same (claude global config)
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — `codex mcp list` shows enabled in chrono-* config (ENV: CHRONO_VAULT_ROOT, OBSIDIAN_REST_API_KEY, OBSIDIAN_VAULT_ROOT)
  - content pane (gemini): yes — verified post-Task 6 (gemini mcp list -d shows configured + Connected); paths absolute
  - research pane (kimi): yes — `kimi mcp list` shows configured
- last_checked: 2026-05-03 for claude panes; 2026-05-02 for codex/kimi; 2026-05-02 for gemini (absent)

### chrono-kg MCP
- purpose: Knowledge-graph query and write surface (separate namespace under chrono-vault binary)
- specialists: memory-curator, memory-curator, kg-integrity-gate workflows, all model leads writing durable findings
- verified per pane:
  - chrono pane (claude): yes — test_reference: `claude mcp list` post-2026-05-03 tilde-fix shows ✓ Connected
  - security pane (claude): yes — same
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — `codex mcp list` shows enabled (same binary as chrono-vault, `--namespace kg`)
  - content pane (gemini): yes — verified post-Task 6
  - research pane (kimi): yes — `kimi mcp list` shows configured
- last_checked: 2026-05-03 for claude panes; 2026-05-02 for codex/kimi; 2026-05-02 for gemini (absent)

### chrono-obsidian MCP
- purpose: Obsidian REST-API bridge for vault read/write
- specialists: technical-writer, brand-voice, any specialist publishing markdown to operator's vault
- verified per pane:
  - chrono pane (claude): yes — test_reference: `claude mcp list` post-2026-05-03 tilde-fix shows ✓ Connected
  - security pane (claude): yes — same
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — `codex mcp list` shows enabled (ENV: OBSIDIAN_REST_API_KEY, OBSIDIAN_VAULT_ROOT)
  - content pane (gemini): yes — verified post-Task 6
  - research pane (kimi): yes — `kimi mcp list` shows configured
- last_checked: 2026-05-03 for claude panes; 2026-05-02 for codex/kimi; 2026-05-02 for gemini (absent)

### chrono-catalog MCP
- purpose: Local skill / plugin / tool catalog query surface
- specialists: harness-optimizer, prompt-engineer, any specialist needing skill-discovery
- verified per pane:
  - chrono pane (claude): yes — test_reference: `claude mcp list` post-2026-05-03 tilde-fix shows ✓ Connected
  - security pane (claude): yes — same
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — `codex mcp list` shows enabled (same binary, `--namespace catalog`)
  - content pane (gemini): yes — verified post-Task 6
  - research pane (kimi): yes — `kimi mcp list` shows configured
- last_checked: 2026-05-03 for claude panes; 2026-05-02 for codex/kimi; 2026-05-02 for gemini (absent)

### chrono-research-arsenal MCP
- purpose: Current live research wrapper exposing `arxiv_search`, `xai_search`, and `perplexity_search_web` (the last as a sibling MCP under the same plugin namespace via `uvx perplexity-mcp`). Brave, Apify, and Serper remain planned/unverified.
- specialists: research, scout, large-context-analyst
- verified per pane:
  - chrono pane (claude): yes — wrapper registered; verified live: `arxiv_search`, `perplexity_search_web` (Perplexity smoke test 2026-07-12 returned cited results), and `xai_search` (fixed 2026-07-12 to use xAI Responses API `POST https://api.x.ai/v1/responses` with `web_search` / `x_search` tools; smoke test returned `ok:true` with real URLs).
  - security pane (claude): yes — same
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — registered; task packets must still verify `tools/list` before naming provider-specific tools
  - content pane (gemini): no — **INTENTIONALLY SKIPPED in Hybrid Path A.** Google Search grounding (built into `gemini-3.1-pro-preview`) is the substitute. Gemini pane research uses native grounding, not chrono-research-arsenal.
  - research pane (kimi): registered; same wrapper; `xai_search` endpoint fixed tool-wide via the 2026-07-12 Responses API patch. Re-smoke in-lane before relying on Kimi-specific tool availability.
- last_checked: 2026-07-12 for `xai_search` endpoint fix + arxiv/perplexity sibling smoke tests

### chrono-content-engineer MCP
- purpose: Current live content/media wrapper exposing `generate_image`, `generate_video`, and `generate_audio`. Provider-specific child routes such as ElevenLabs and Higgsfield are separate surfaces unless the active lane schema exposes them.
- specialists: image-designer, video-director, video-editor, music-composer, sound-designer, voice-narrator
- verified per pane:
  - chrono pane (claude): yes — wrapper registered; Claude also has the separate ElevenLabs child MCP
  - security pane (claude): yes — same
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — registered; wrapper tools must be verified with `tools/list`
  - content pane (gemini): yes — wrapper registered; current wrapper tools are `generate_image`, `generate_video`, `generate_audio`; do not request ElevenLabs child tools from Gemini unless the lane schema exposes them
  - research pane (kimi): yes — registered; wrapper tools must be verified with `tools/list`
- last_checked: 2026-05-05 for current wrapper tool names

### chrono-recon MCP
- purpose: OSINT recon — DNS, WHOIS, crt.sh certificate enumeration, Wayback snapshots, GitHub leaked-secrets search. Tools: `dns_enumerate_tool`, `whois_lookup_tool`, `crt_sh_certificates_tool`, `wayback_snapshots_tool`, `github_leaked_secrets_tool`.
- specialists: scout, security-analyst, exploit-developer
- verified per pane:
  - chrono pane (claude): yes — `claude mcp list` shows `plugin:chrono-recon:chrono-recon` ✓ Connected (loaded via the `chrono` plugin marketplace, not the `settings.json` `mcpServers` block)
  - security pane (claude): yes — same (claude global config)
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — `codex mcp list` shows `chrono-recon` enabled (ENV: GH_TOKEN)
  - content pane (gemini): yes — `~/.gemini/settings.json` `mcpServers` includes `chrono-recon`
  - research pane (kimi): yes — `kimi mcp list` shows `chrono-recon` (stdio)
- last_checked: 2026-07-12 — live re-verified on all 4 model CLIs; 5 tools returned by a `tools/list` handshake
- notes: Recon-only (no active scanning). `github_leaked_secrets_tool` requires a valid `GH_TOKEN` in the lane env (the Gemini pane currently stores it literally — tracked separately). Cited in `scout` / `security-analyst` / `exploit-developer` `preferred_tools`.

### sequential-thinking MCP
- purpose: Multi-step structured reasoning tool (`sequentialthinking`)
- specialists: any specialist doing multi-step planning, brainstorming, debugging
- verified per pane:
  - chrono pane (claude): yes — test_reference: `claude mcp list` shows `sequential-thinking` ✓ Connected via `/opt/homebrew/bin/mcp-server-sequential-thinking`
  - security pane (claude): yes — same
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — `codex mcp list` shows enabled (stdio, npx)
  - content pane (gemini): yes — verified post-Task 6
  - research pane (kimi): yes — `kimi mcp list` shows configured (stdio, npx)
- last_checked: 2026-05-02 (claude/codex/kimi); 2026-05-02 (gemini absent)

---

## 9.5 Non-chrono plugin MCPs & capabilities (Claude lane)

Claude Code plugins available on the `claude` / `chrono` panes. Not part of the chrono-* family; registered via `enabledPlugins`, not the chrono marketplace.

### context7 MCP
- url: https://github.com/upstash/context7
- access: Public (Claude Code plugin `context7@claude-plugins-official`)
- specialists: any specialist needing current library/framework docs (e.g. ai-engineer, backend-engineer, frontend-engineer)
- verified: yes
- last_checked: 2026-07-12
- test_reference: `claude mcp list` shows `plugin:context7:context7` ✓ Connected (`npx -y @upstash/context7-mcp`)
- notes: Live docs fetch (`resolve-library-id`, `query-docs`). Claude/chrono panes only; not registered on codex/gemini/kimi.

### firecrawl (plugin skills — NOT an MCP server)
- url: https://www.firecrawl.dev
- access: Public (Claude Code plugin `firecrawl@claude-plugins-official`; live calls need a Firecrawl API key)
- specialists: copywriter (carries `firecrawl:scrape` in `required_tools`), any specialist doing web scrape/crawl
- verified: yes (plugin enabled) — NOTE: firecrawl is a **skills** plugin, not an MCP server; it does **not** appear in `claude mcp list`.
- last_checked: 2026-07-12
- test_reference: `jq '.enabledPlugins["firecrawl@claude-plugins-official"]' ~/.claude/settings.json` → `true`; skills `firecrawl-scrape` / `firecrawl-crawl` / `firecrawl-map` / `firecrawl-parse` present in the plugin catalog.
- notes: The `firecrawl:scrape` token used in `required_tools` / `tool-catalog.md` refers to this plugin's scrape capability, not an MCP `server:tool`. Claude-lane only — a specialist routed to a non-claude lane must treat firecrawl as unavailable and report `capability_gap`.

---

## 10. Personal Ops, Outreach, and Notifications

### Gmail / email triage
- access: Claude connected app / Gmail MCP where configured
- specialists: personal-ops, privacy-steward, Outreach Mode approval gate
- verified: partial
- last_checked: 2026-05-02 inventory shows Claude Gmail connected; current live MCP audit does not catalog it yet
- notes: Read/triage/draft workflows are allowed only when the active pane has verified access. Sending requires explicit per-message operator approval.

### Google Calendar / reminders / todos
- access: Calendar/Todo MCPs where configured
- specialists: personal-ops
- verified: auth-pending
- last_checked: 2026-05-02 inventory marked Calendar auth-pending
- notes: Specialists must return a missing-auth report instead of claiming calendar/todo writes when auth is absent.

### Outreach pipeline bridge
- access: private/local `<private-outreach-repo>`
- specialists: research, data-extraction-engineer, privacy-steward, brand-voice, editor, personal-ops
- verified: dry-run bridge only
- last_checked: 2026-05-04 local inspection
- test_reference: `bin/outreach-dry-run.sh` runs `python -m outreach.runner --dry-run` in the private package when present
- notes: No live sends. Public repo must not track private lead DBs, raw emails, credentials, or operator-specific voice files.

### Morning / weekly summary notifications
- access: local markdown morning brief and terminal/status commands
- specialists: loop-operator, memory-curator, agentops, personal-ops
- verified: local only
- last_checked: 2026-05-04
- notes: Telegram or other external notification sinks are future send-only adapters. They must not accept coding/editing commands unless separately designed and approved.

---

## 11. Out-of-scope failed MCPs (separate plugin issues)

These showed `Failed to connect` in `claude mcp list` post-2026-05-03 tilde fix and are NOT chrono-* family. Specialists must NOT cite `verified: no` entries here. **Exception (audit A6, re-verified 2026-07-12): `plugin:github:github` now connects — it is `verified: yes` below and is citable on the claude lane. This resolves the `tool-catalog.md`-vs-`api-catalog.md` github contradiction.**

### plugin:goodmem:goodmem
- verified: no
- last_checked: 2026-05-03
- notes: separate plugin issue. Likely missing dep or upstream package issue. Worth investigating in the next compatibility pass.

### plugin:github:github (HTTP)
- verified: yes (re-verified 2026-07-12; the 2026-05-03 "Failed to connect" no longer reproduces)
- last_checked: 2026-07-12
- test_reference: `claude mcp list` shows `plugin:github:github: https://api.githubcopilot.com/mcp/ (HTTP) - ✔ Connected`
- notes: Now connects on the claude lane — the earlier failure is resolved (github graduated out of the failed set; kept here with a resolved marker rather than moved). Availability on codex/gemini/kimi is per-lane; verify before citing off-claude.

### plugin:greptile:greptile (HTTP)
- verified: no
- last_checked: 2026-05-03
- notes: separate plugin issue. HTTP MCP — same root-cause class as github MCP.

---

## 12. Local Security Toolchain

Local security/bounty CLIs installed on the operator's Mac, invoked via **Bash** (these are CLIs, not MCPs). Specialists in the `security` and smart-contract namespaces may now cite any `verified: yes` entry here (this section is the sanction that unblocks the `## Tools` prose in those briefs).

All `--version` output below was reproduced live on 2026-07-12 (root CLAUDE.md rule 8). `access: Public` = locally installed binary, no subscription/API gate.

**PATH caveat:** `waybackurls` and `interactsh-client` are installed under `~/go/bin`, which is NOT on the default login PATH. Invoke them by absolute path, or add `~/go/bin` to PATH (operator action — not done by this task). All other tools are on PATH via `/opt/homebrew/bin` or `~/.local/bin`.

### Smart-contract tooling → `smart-contract-engineer`, `exploit-developer`

#### forge (Foundry)
- url: https://getfoundry.sh
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `forge --version` → `forge Version: 1.5.1-Homebrew` (/opt/homebrew/bin/forge)
- notes: Use when writing Foundry PoC tests / fork-testing a fund-loss finding before submission (the profile that actually pays — see `_state/bounty-retro-2026-07-12/SUMMARY.md`).

#### cast (Foundry)
- url: https://getfoundry.sh
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `cast --version` → `cast Version: 1.5.1-Homebrew` (/opt/homebrew/bin/cast)
- notes: Use when reading on-chain state / encoding calldata / verifying an exploit tx against a fork.

#### anvil (Foundry)
- url: https://getfoundry.sh
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `anvil --version` → `anvil Version: 1.5.1-Homebrew` (/opt/homebrew/bin/anvil)
- notes: Use when standing up a local/forked EVM to reproduce a smart-contract PoC deterministically.

#### chisel (Foundry)
- url: https://getfoundry.sh
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `chisel --version` → `chisel Version: 1.5.1-Homebrew` (/opt/homebrew/bin/chisel)
- notes: Use when scratch-testing Solidity snippets / arithmetic (e.g. reproducing an underflow) in a REPL.

#### slither
- url: https://github.com/crytic/slither
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `slither --version` → `0.11.5` (`~/.local/bin/slither`)
- notes: Use when static-analysing Solidity source for known vuln patterns before manual review.

#### myth (Mythril)
- url: https://github.com/Consensys/mythril
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `myth version` → `Mythril version v0.24.8` (`~/.local/bin/myth`). NOTE: version flag is `myth version`, not `--version`.
- notes: Use when symbolic-executing EVM bytecode to confirm reachability of a suspected bug.

#### echidna
- url: https://github.com/crytic/echidna
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `echidna --version` → `Echidna 2.3.2` (/opt/homebrew/bin/echidna)
- notes: Use when property/invariant fuzzing a contract to find fund-loss violations.

#### medusa
- url: https://github.com/crytic/medusa
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `medusa --version` → `medusa version 1.5.1` (/opt/homebrew/bin/medusa)
- notes: Use as a parallel/coverage-guided fuzzer alongside echidna for invariant checks.

#### halmos
- url: https://github.com/a16z/halmos
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `halmos --version` → `halmos 0.3.3` (`~/.local/bin/halmos`)
- notes: Use when symbolic-testing Foundry test suites to prove/disprove invariants exhaustively.

#### aderyn
- url: https://github.com/Cyfrin/aderyn
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `aderyn --version` → `aderyn 0.6.8` (/opt/homebrew/bin/aderyn)
- notes: Use as a fast Rust-based Solidity static analyzer for a first-pass issue sweep.

### Web / recon tooling → `scout`

#### nuclei
- url: https://github.com/projectdiscovery/nuclei
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: `nuclei --version` → `Nuclei Engine Version: v3.8.0` (/opt/homebrew/bin/nuclei)
- notes: Use when template-scanning an in-scope web target for known CVEs/misconfigs during recon.

#### subfinder
- url: https://github.com/projectdiscovery/subfinder
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: `subfinder --version` → `Current Version: v2.13.0` (/opt/homebrew/bin/subfinder)
- notes: Use when passively enumerating subdomains of an in-scope program asset.

#### httpx
- url: https://github.com/projectdiscovery/httpx
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: `httpx -version` → `Current Version: v1.9.0` (/opt/homebrew/bin/httpx). NOTE: single-dash `-version`; reads stdin by default.
- notes: Use when probing which enumerated hosts are live / their tech stack. (This is the ProjectDiscovery httpx, not the Python HTTP lib.)

#### katana
- url: https://github.com/projectdiscovery/katana
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: `katana -version` → `Current version: v1.5.0` (/opt/homebrew/bin/katana). NOTE: single-dash `-version`.
- notes: Use when crawling an in-scope web app to map endpoints/attack surface.

#### naabu
- url: https://github.com/projectdiscovery/naabu
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: `naabu -version` → `Current Version: 2.5.0` (/opt/homebrew/bin/naabu). NOTE: single-dash `-version`.
- notes: Use when port-scanning an in-scope host (respect program scope/rate rules).

#### dnsx
- url: https://github.com/projectdiscovery/dnsx
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: `dnsx -version` → `Current Version: 1.2.3` (/opt/homebrew/bin/dnsx). NOTE: single-dash `-version`.
- notes: Use when resolving/validating enumerated subdomains and pulling DNS records at scale.

#### amass
- url: https://github.com/owasp-amass/amass
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: `amass --version` → `v5.1.1` (/opt/homebrew/bin/amass)
- notes: Use for deeper OSINT-driven attack-surface mapping (complements subfinder).

#### gau
- url: https://github.com/lc/gau
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: `gau --version` → `gau version: 2.2.4` (/opt/homebrew/bin/gau)
- notes: Use when pulling historical/known URLs for an in-scope host from OTX/Wayback/etc. during recon.

#### ffuf
- url: https://github.com/ffuf/ffuf
- access: Public
- specialists: scout, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `ffuf -V` → `ffuf version: 2.1.0-dev` (/opt/homebrew/bin/ffuf). NOTE: version flag is `-V`; `--version` is not defined and exits non-zero. This is a dev build, not a tagged release.
- notes: Use for content/parameter fuzzing on an in-scope web app. (Specialist mapping is my judgment — packet didn't assign ffuf/gau explicitly.)

#### waybackurls
- url: https://github.com/tomnomnom/waybackurls
- access: Public
- specialists: scout
- verified: yes
- last_checked: 2026-07-12
- test_reference: installed via `go install …/waybackurls@latest`; binary at `~/go/bin/waybackurls` (8.5MB, 2026-07-12). `waybackurls -h` prints usage. NOTE: no `--version` flag exists; verification is presence + runnable `-h`.
- notes: Use when fetching a host's Wayback-known URLs during recon. NOT on default PATH (`~/go/bin`).

#### interactsh-client
- url: https://github.com/projectdiscovery/interactsh
- access: Public
- specialists: scout, exploit-developer
- verified: yes
- last_checked: 2026-07-12
- test_reference: `~/go/bin/interactsh-client -version` → `Current Version: 1.3.1` (installed via `go install` 2026-07-12)
- notes: Use for OOB interaction detection (blind SSRF/RCE callbacks) — an *impact-demonstrating* tool, directly relevant to the retro's "prove impact, not reachability" lesson. NOT on default PATH (`~/go/bin`).

### SAST / secrets / SCA → `security-analyst`

#### semgrep
- url: https://semgrep.dev
- access: Public
- specialists: security-analyst
- verified: yes
- last_checked: 2026-07-12
- test_reference: `semgrep --version` → `1.157.0` (/opt/homebrew/bin/semgrep)
- notes: Use for pattern-based SAST over target source. Kept CLI-only (see §12 footnote on the disabled `semgrep` plugin MCP).

#### osv-scanner
- url: https://github.com/google/osv-scanner
- access: Public
- specialists: security-analyst
- verified: yes
- last_checked: 2026-07-12
- test_reference: `osv-scanner --version` → `osv-scanner version: 2.3.5` (/opt/homebrew/bin/osv-scanner)
- notes: Use for dependency/SCA vulnerability scanning against OSV.dev.

#### gitleaks
- url: https://github.com/gitleaks/gitleaks
- access: Public
- specialists: security-analyst
- verified: yes
- last_checked: 2026-07-12
- test_reference: `gitleaks version` → `gitleaks version 8.30.1` (/opt/homebrew/bin/gitleaks)
- notes: Use for secret-scanning a repo/history before or during an audit.

#### trufflehog
- url: https://github.com/trufflesecurity/trufflehog
- access: Public
- specialists: security-analyst
- verified: yes
- last_checked: 2026-07-12
- test_reference: `trufflehog --version` → `trufflehog 3.95.1` (/opt/homebrew/bin/trufflehog)
- notes: Use for verified-secret detection (complements gitleaks; can validate live credentials — respect scope).

#### trivy
- url: https://github.com/aquasecurity/trivy
- access: Public
- specialists: security-analyst
- verified: yes
- last_checked: 2026-07-12
- test_reference: `trivy --version` → `Version: 0.72.0` (/opt/homebrew/bin/trivy; installed via `brew install trivy` 2026-07-12)
- notes: Use for container/filesystem/IaC vulnerability + misconfig scanning.

### Active scanners (installed) → scout, security-analyst, exploit-developer

Installed and runnable high-blast-radius active tools. Usable for authorized bounty work with **no per-use operator approval required**, but scope-gated in each entry's notes: run only against explicitly in-scope targets per the program's rules of engagement.

#### nikto
- url: https://github.com/sullo/nikto
- access: Public
- specialists: scout, security-analyst
- verified: yes
- last_checked: 2026-07-12
- test_reference: `nikto -Version` → `Nikto 2.6.0 (LW 2.5)` (/opt/homebrew/bin/nikto; installed 2026-07-12 via brew)
- notes: Installed, active web server/vuln scanner (noisy/intrusive by design). Active scanner — run only against explicitly in-scope bounty targets per the program's rules of engagement; never against out-of-scope or third-party hosts.

#### sqlmap
- url: https://github.com/sqlmapproject/sqlmap
- access: Public
- specialists: exploit-developer, security-analyst
- verified: yes
- last_checked: 2026-07-12
- test_reference: `sqlmap --version` → `1.10.7#stable` (/opt/homebrew/bin/sqlmap; installed 2026-07-12 via brew)
- notes: Installed, active SQLi detection/exploitation tool (high blast-radius against live targets). Active scanner — run only against explicitly in-scope bounty targets per the program's rules of engagement; never against out-of-scope or third-party hosts.

### Not installed / unverified

#### manticore
- url: https://github.com/trailofbits/manticore
- access: Public
- specialists: smart-contract-engineer, exploit-developer
- verified: no
- last_checked: 2026-07-12
- test_reference: `uv tool install manticore` → FAILED (pysha3 native build error on py3.13/ARM 2026-07-12). Superseded by halmos/mythril/echidna (all verified:yes); not pursued.
- notes: Symbolic-execution engine (EVM + native). Heavy/brittle native deps; pip-only, historically fragile install. Deferred — flag before forcing.

**Footnote — semgrep MCP (packet P3):** `~/.claude/settings.json` does NOT contain an active `semgrep` MCP server; it carries `"semgrep@claude-plugins-official": false` in `enabledPlugins` (i.e. the plugin is *disabled*). Since the semgrep **CLI** is verified above and available to `security-analyst` via Bash, the recommendation is to keep semgrep **CLI-only** and NOT replicate a disabled plugin MCP across lanes. No lane MCP configs were changed for semgrep.

---

## Local skill catalog summary

477 unique SKILL.md files across 40+ plugins (verified by `find ~/.claude/plugins/cache -path "*/skills/*" -name "SKILL.md" | wc -l` per Capability Inventory).

Highlights useful to specialists (referenced in upgrade-specialists.py pre-fill):
- Trail of Bits-derived: review-severity-ladder, code-review-loop, multi-llm-audit-adjudication, differential-review, fp-check
- Smart-contract: chain-construct-smart-contract, evm-audit-flow, solana-audit-flow, defi-invariant-check, vulnhunter-solana, gptscan-prompt-templates
- Security: agentic-safety-audit, semgrep-rule-author, supply-chain-audit, web-vuln, github-recon, osint-platform-audit, pre-audit-threat-model
- Frontend/UI: frontend-design, design-token-governance, a11y-audit, react-performance-loop, figma-* (10+ skills)
- Process: brainstorming, writing-plans, writing-skills, executing-plans, verification-before-completion, test-driven-development, systematic-debugging
- KG/memory: kg-integrity-gate, stale-knowledge-purge, brain-trio-amendment-authoring
- Multi-model: cross-provider-dissent, council-consensus, cross-model-verification, multi-stance-audit-fanout

Specialist files cite skills by exact name; validator (Task 9) verifies skill exists in local catalog.

---

## Research backlog

These entries are flagged `verified: needs-research` above. They run as harness-optimizer sub-tasks during compatibility work. Specialist files ignore `needs-research` entries until verified.

Backlog (8 categories):
1. **Gemini ecosystem** (Nano Banana / Veo 3 / Imagen / Search grounding / Jules / Flow / NotebookLM / Antigravity)
2. **Kimi advanced features** (300 parallel sub-agents native usage / 4000 tool steps / MoonViT vision)
3. **xAI / Grok** (Grok-4-fast 2M context / Grok-X integration)
4. **DeepSeek V4** (API setup + integration into chrono MCPs / fanout pool)
5. **Anthropic /ultrareview command behavior** (verify in-session slash-command + cloud-hosted review runtime via live test)
6. **Codex Cloud Agents async access** (operator ChatGPT Plus tier verification)
7. **Codex native macOS computer use** (verify access path — CLI vs API-only)
8. **Higgsfield auth setup** (currently fails Needs authentication — chrono-content-engineer HTTP MCP)

Each produces `_state/research-{topic}-2026-05-02.md` sub-report. Catalog entries flip `needs-research` → `yes`/`no` based on findings.
