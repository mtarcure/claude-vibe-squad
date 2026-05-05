# Squad API & Feature Catalog

Verified-from-Capability-Inventory list of every API, native CLI feature, and MCP available to the squad. Specialist files (`departments/*/specialists/*.md`) may only cite entries marked `verified: yes` here. Entries marked `needs-research` are current research backlog tasks for harness-optimizer and do not block specialist authoring.

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
- specialists: designer (Content), ui-engineer (Coding)
- verified: yes
- last_checked: 2026-05-02
- test_reference: claude.ai/design web access via Max plan
- notes: Web-app surface for design generation. Operator has Max access.

### Claude Computer Use API
- url: https://docs.anthropic.com/en/docs/build-with-claude/computer-use
- access: API tier (uncertain via CLI)
- specialists: e2e-runner, scraping-engineer (potentially)
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
- notes: REQUIRED `workspace-write` for outbox writes. Encoded in `bin/launch-squad.sh` and `coding/LEAD.md`.

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
- specialists: e2e-runner (potential)
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
- specialists: designer, media-producer (potential)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: identify whether accessed via `gemini` CLI subcommand, via Google AI Studio web only, or via API
- notes: Image-gen models. Access path unconfirmed.

### Veo 3
- url: https://veo.google
- access: Subscription (uncertain)
- specialists: media-producer (video)
- verified: needs-research
- last_checked: 2026-05-02
- research_task: identify access path — gemini CLI vs API vs web only
- notes: Video generation.

### Imagen
- url: https://imagen.research.google
- access: Subscription (uncertain)
- specialists: designer, media-producer
- verified: needs-research
- last_checked: 2026-05-02
- research_task: identify access path
- notes: Image generation.

### Google Search grounding
- url: N/A (model-side)
- access: Subscription (likely implicit per model)
- specialists: research, media-producer, fact-checking specialists
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
- specialists: media-producer (video)
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
- research_task: investigate — alt CLI for Coding pane?
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
- specialists: research, media-producer (potential)
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
- specialists: media-producer
- verified: yes for Claude child MCP; needs-research for Gemini/content-pane use through chrono-content-engineer
- last_checked: 2026-05-02
- test_reference: `claude mcp list` shows `plugin:chrono-content-engineer:elevenlabs` ✓ Connected via `uvx elevenlabs-mcp` (Capability Inventory)
- notes: Full surface: speech-to-text, text-to-speech, sound effects, music composition, voice cloning, voice library search, conversational agents. See `mcp__plugin_chrono-content-engineer_elevenlabs__*` tool list.

---

## 8. Higgsfield (chrono-content-engineer)

### Higgsfield MCP — image/video generation
- url: https://higgsfield.ai
- access: HTTP MCP (auth required)
- specialists: media-producer, designer (image/video)
- verified: no
- last_checked: 2026-05-02
- test_reference: `claude mcp list` shows `plugin:chrono-content-engineer:higgsfield` ⚠ Needs authentication
- notes: HTTP MCP. Auth not yet completed. Specialists must NOT cite this until auth resolved. Tracked as separate operational task.

---

## 9. chrono MCPs squad-wide

Per-pane verification matrix for each chrono-* family MCP. Claude pane verification is post-2026-05-03 tilde-fix (see `_state/incident-2026-05-03-claude-mcp-tilde.md`).

### chrono-vault MCP
- purpose: KG read/write, durable memory across Leads
- specialists: brand-voice (Content), memory-curator (SysMgmt), memory-curator (SysMgmt), all Leads' memory.md persistence
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
- specialists: memory-curator, memory-curator, kg-integrity-gate workflows, all Leads writing durable findings
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
- specialists: technical-writer, designer, brand-voice, any specialist publishing markdown to operator's vault
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
- purpose: Multi-engine research surface (Perplexity, Brave, Apify, Serper, xAI/Grok routing)
- specialists: research, scout, large-context-analyst, fact-checker
- verified per pane:
  - chrono pane (claude): yes — test_reference: `claude mcp list` post-2026-05-03 tilde-fix shows ✓ Connected (top-level wrapper); child `perplexity` independently ✓ Connected via `uvx perplexity-mcp`
  - security pane (claude): yes — same
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — `codex mcp list` shows enabled (ENV: APIFY_TOKEN, BRAVE_API_KEY, PERPLEXITY_API_KEY, SERPER_API_KEY, XAI_API_KEY)
  - content pane (gemini): no — **INTENTIONALLY SKIPPED in Hybrid Path A.** Google Search grounding (built into `gemini-3.1-pro-preview`) is the substitute. Gemini pane research uses native grounding, not chrono-research-arsenal.
  - research pane (kimi): yes — `kimi mcp list` shows configured
- last_checked: 2026-05-03 for claude panes; 2026-05-02 for codex/kimi; 2026-05-02 for gemini (intentional-skip)

### chrono-content-engineer MCP
- purpose: Content/media provider routing. Provider-specific availability still depends on each child route's verification status.
- specialists: media-producer, designer, content-creator only for non-media content support
- verified per pane:
  - chrono pane (claude): yes — test_reference: `claude mcp list` post-2026-05-03 tilde-fix shows ✓ Connected (top-level wrapper); child `elevenlabs` independently ✓ Connected
  - security pane (claude): yes — same
  - sysmgmt pane (claude): yes — same
  - coding pane (codex): yes — `codex mcp list` shows enabled (ENV: GEMINI_API_KEY, OPENAI_API_KEY, XAI_API_KEY)
  - content pane (gemini): needs-research — wrapper presence claimed in prior docs, but proof log is missing locally; do not claim provider-level success without rerun
  - research pane (kimi): yes — `kimi mcp list` shows configured
- last_checked: 2026-05-03 for claude panes; 2026-05-02 for codex/kimi; gemini requires rerun/proof log

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
- specialists: research, data-extraction-engineer, privacy-steward, content-creator, brand-voice, editor, personal-ops
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

These show `Failed to connect` in `claude mcp list` post-2026-05-03 tilde fix and are NOT chrono-* family. Specialists must NOT cite them.

### plugin:goodmem:goodmem
- verified: no
- last_checked: 2026-05-03
- notes: separate plugin issue. Likely missing dep or upstream package issue. Worth investigating in the next compatibility pass.

### plugin:github:github (HTTP)
- verified: no
- last_checked: 2026-05-03
- notes: separate plugin issue. HTTP MCP — possibly auth or endpoint change. Worth investigating in the next compatibility pass.

### plugin:greptile:greptile (HTTP)
- verified: no
- last_checked: 2026-05-03
- notes: separate plugin issue. HTTP MCP — same root-cause class as github MCP.

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
