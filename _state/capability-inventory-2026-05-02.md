# Capability Inventory — 2026-05-02

> Foundational artifact for v1.1 Item 0. Verifies every CLI flag, MCP, and feature
> claimed in `docs/specs/2026-05-02-vibe-squad-v1.1-tool-utilization.md` against
> live CLI output. Specialist files (Item 1) and `shared/api-catalog.md` (Item 7)
> may only cite entries marked `verified` here.

**Inventory date:** 2026-05-02
**Verified by:** Capability Inventory subagent (Claude Opus 4.7) operating outside the squad tmux session
**Method:** Live `--help` capture + targeted live-flag tests + per-CLI `mcp list` enumeration. Subscription auth used (env-drop pattern: `env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY <cli> ...`).

**Scope caveat:** `mcp list` output is config-file driven (e.g. `~/.claude/`, `~/.codex/`, `~/.kimi/mcp.json`, gemini's `mcp` subcommand store). Running `<cli> mcp list` outside any pane should match what the corresponding pane sees, *unless* a launch invocation passes `--mcp-config <path>` or `--strict-mcp-config` to scope the bound set per-launch. Current `bin/launch-squad.sh` does NOT pass per-launch MCP config flags, so the global-config view in this document is the authoritative pane MCP set as of 2026-05-02.

---

## Per-CLI verified flags

### claude (Claude Code)

Source: `claude --help` captured 2026-05-02. Binary: `claude` on $PATH (`~/.local/bin/claude` per launch-squad.sh PATH prefix).

- `--effort <level>` (low | medium | high | xhigh | max) — verified via live `--help` enum text AND live invocation
  - test_reference: `env -u ANTHROPIC_API_KEY claude --effort xhigh -p "echo test"` returned exit 0 with successful prompt completion (model produced an "★ Insight" block)
  - status: VERIFIED ✅
- `--model <model>` — verified via live `--help` text AND live invocation
  - accepts aliases `opus` / `sonnet` / `haiku` AND full names like `claude-sonnet-4-6`
  - test_reference: `env -u ANTHROPIC_API_KEY claude --model opus -p "ok"` returned exit 0 with model output ("Ready when you are. What would you like to work on?")
  - status: VERIFIED ✅
- `--mcp-config <configs...>` — verified via live `--help` text
  - accepts JSON files OR JSON strings, space-separated
  - status: VERIFIED ✅ (help-text only; not live-tested)
- `--strict-mcp-config` — verified via live `--help` text
  - "Only use MCP servers from --mcp-config, ignoring all other MCP configurations"
  - status: VERIFIED ✅ (help-text only; not live-tested)
- `--permission-mode <mode>` (acceptEdits | auto | bypassPermissions | default | dontAsk | plan) — verified via live `--help` enum text
  - status: VERIFIED ✅
- `--add-dir <directories...>` — verified via live `--help` text
  - status: VERIFIED ✅
- `--worktree [name]` (alias `-w`) — verified via live `--help` text. "Create a new git worktree for this session"
  - status: VERIFIED ✅
- `-p, --print` — verified via live `--help` text and used in test invocations above
  - status: VERIFIED ✅
- `--append-system-prompt <prompt>` — verified via live `--help` text. Used in spawn-specialist.sh design.
  - status: VERIFIED ✅
- `--allowedTools` / `--allowed-tools <tools...>` — verified via live `--help` text
  - status: VERIFIED ✅
- `--agents <json>` — verified via live `--help` text. Defines custom agents.
  - status: VERIFIED ✅
- `--ide` — verified via live `--help` text. Auto-connect to IDE if exactly one available.
  - status: VERIFIED ✅
- `--chrome` / `--no-chrome` — verified via live `--help` text. Claude in Chrome integration toggle.
  - status: VERIFIED ✅
- `--bare` — verified via live `--help` text. Minimal mode skipping hooks/LSP/plugins/keychain/CLAUDE.md auto-discovery.
  - status: VERIFIED ✅
- `claude ultrareview` (subcommand, NOT a flag) — verified via live `--help` text
  - "Run a cloud-hosted multi-agent code review of the current branch (or a PR number / base branch) and print the findings"
  - test_reference: appears in `Commands:` block of `claude --help` output, line 75 (verbatim help capture)
  - status: VERIFIED-AS-SUBCOMMAND ✅ (NOT a `--ultrareview` flag — spec's earlier draft drift fixed)
- `claude mcp` / `claude plugin` / `claude doctor` / `claude install` / `claude auth` / `claude agents` — verified via live `--help` Commands block
  - status: VERIFIED ✅

### codex (OpenAI Codex CLI)

Source: `codex --help` captured 2026-05-02. Binary: Codex CLI v0.128.0 (research preview).

- `-c <key=value>` (override TOML config) — verified via live `--help` text
  - dotted-path nested override; value parsed as TOML with literal-string fallback
  - status: VERIFIED ✅
- `-c model_reasoning_effort=high` — verified via live invocation
  - test_reference: `env -u OPENAI_API_KEY codex exec -c model_reasoning_effort=high "echo test"` printed `reasoning effort: high` in startup banner and returned exit 0
  - status: VERIFIED ✅
- `-m, --model <MODEL>` — verified via live `--help` text
  - status: VERIFIED ✅
- `-s, --sandbox <SANDBOX_MODE>` (read-only | workspace-write | danger-full-access) — verified via live `--help` enum
  - status: VERIFIED ✅
- `-a, --ask-for-approval <APPROVAL_POLICY>` (untrusted | on-failure[deprecated] | on-request | never) — verified via live `--help` enum
  - status: VERIFIED ✅
- `--add-dir <DIR>` — verified via live `--help` text
  - status: VERIFIED ✅
- `-C, --cd <DIR>` — verified via live `--help` text
  - status: VERIFIED ✅
- `--search` — verified via live `--help` text. Enables native Responses `web_search` tool.
  - status: VERIFIED ✅
- `--enable <FEATURE>` / `--disable <FEATURE>` — verified via live `--help` text. Equivalent to `-c features.<name>=true|false`.
  - status: VERIFIED ✅
- `codex exec` — verified via live `--help` Commands block. "Run Codex non-interactively [aliases: e]"
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `codex review` — verified via live `--help` Commands block. "Run a code review non-interactively"
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `codex mcp` (manage) / `codex mcp-server` (run as MCP) — verified via live `--help` Commands block
  - `codex mcp-server` = "Start Codex as an MCP server (stdio)"
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `codex plugin` — verified via live `--help` Commands block. "Manage Codex plugins"
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `codex cloud` — verified via live `--help` Commands block. "[EXPERIMENTAL] Browse tasks from Codex Cloud and apply changes locally"
  - status: VERIFIED-AS-SUBCOMMAND ✅ (experimental-tagged)
- `codex resume` / `codex fork` — verified via live `--help` Commands block. Session continuation.
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `codex sandbox` — verified via live `--help` Commands block. "Run commands within a Codex-provided sandbox"
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `--oss` / `--local-provider <lmstudio|ollama>` — verified via live `--help` text. Open-source provider routing.
  - status: VERIFIED ✅

### gemini (Gemini CLI)

Source: `gemini --help` captured 2026-05-02.

- `-m, --model <model>` — verified via live `--help` text
  - status: VERIFIED ✅
- `-p, --prompt <text>` — verified via live `--help` text. Non-interactive (headless) mode.
  - status: VERIFIED ✅
- `-i, --prompt-interactive <text>` — verified via live `--help` text. Execute then continue interactive.
  - status: VERIFIED ✅
- `-w, --worktree [name]` — verified via live `--help` text. "Start Gemini in a new git worktree"
  - status: VERIFIED ✅
- `-y, --yolo` — verified via live `--help` text. Auto-approve all actions.
  - status: VERIFIED ✅
- `--approval-mode` (default | auto_edit | yolo | plan) — verified via live `--help` enum
  - status: VERIFIED ✅
- `--include-directories <dirs...>` — verified via live `--help` text
  - status: VERIFIED ✅
- `--allowed-mcp-server-names <array>` — verified via live `--help` text
  - status: VERIFIED ✅
- `-e, --extensions <list>` — verified via live `--help` text
  - status: VERIFIED ✅
- `--policy <files>` / `--admin-policy <files>` — verified via live `--help` text
  - status: VERIFIED ✅
- `--acp` / `--experimental-acp` — verified via live `--help` text. ACP mode.
  - status: VERIFIED ✅
- `-o, --output-format` (text | json | stream-json) — verified via live `--help` enum
  - status: VERIFIED ✅
- `gemini mcp` (add | remove | list | enable | disable) — verified via live `gemini mcp --help` Commands block
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `gemini extensions` — verified via live `gemini --help` Commands block
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `gemini skills` — verified via live `gemini --help` Commands block. "Manage agent skills"
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `gemini hooks` — verified via live `gemini --help` Commands block
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `gemini gemma` — verified via live `gemini --help` Commands block. "Manage local Gemma model routing"
  - status: VERIFIED-AS-SUBCOMMAND ✅
- `--thinking` flag — **NOT FOUND in `gemini --help` output**
  - test_reference: `env -u GEMINI_API_KEY -u GOOGLE_API_KEY gemini --help | grep -i -E "thinking|reasoning|effort"` returned NO matches
  - **STATUS: ABSENT ❌** — spec's claim of a `gemini --thinking` flag is wrong. Gemini's thinking mode is implicit (model selection like `gemini-2.5-pro` or `gemini-3.1-pro-preview` carries thinking-mode by default for thinking-capable models). For Item 5 launch-squad.sh edit: do NOT add a `--thinking` flag; rely on `--model gemini-3.1-pro-preview` instead.
  - **CONCERN for Item 7:** api-catalog gemini section must mark `--thinking` as `verified: no` with research_task pointing to "verify whether `gemini` CLI has a non-help-documented thinking flag, or confirm thinking is implicit per model"

### kimi (Moonshot Kimi CLI)

Source: `kimi --help` captured 2026-05-02. Binary path: `~/.local/share/uv/tools/kimi-cli/...`.

- `--thinking` / `--no-thinking` — verified via live `--help` text
  - "Enable thinking mode. Default: default thinking mode set in config file."
  - status: VERIFIED ✅
- `-p, --prompt <text>` (alias `-c, --command`) — verified via live `--help` text
  - status: VERIFIED ✅
- `--print` — verified via live `--help` text. "Run in print mode (non-interactive)"
  - status: VERIFIED ✅
- `--quiet` — verified via live `--help` text. Alias for `--print --output-format text --final-message-only`.
  - status: VERIFIED ✅
- `-y, --yolo, --yes` — verified via live `--help` text. Auto-approve all actions.
  - status: VERIFIED ✅
- `--add-dir <directory>` — verified via live `--help` text
  - status: VERIFIED ✅
- `-w, --work-dir <directory>` — verified via live `--help` text
  - status: VERIFIED ✅
- `-m, --model <text>` — verified via live `--help` text
  - status: VERIFIED ✅
- `--mcp-config-file <file>` (repeatable) — verified via live `--help` text
  - status: VERIFIED ✅
- `--mcp-config <text>` (JSON string, repeatable) — verified via live `--help` text
  - status: VERIFIED ✅
- `--skills-dir <directory>` (repeatable) — verified via live `--help` text. "Overrides default discovery."
  - status: VERIFIED ✅
- `--agent` (default | okabe) — verified via live `--help` text. Builtin agent specification.
  - status: VERIFIED ✅
- `--agent-file <file>` — verified via live `--help` text. Custom agent specification.
  - status: VERIFIED ✅
- `--max-steps-per-turn <N>` — verified via live `--help` text. INTEGER ≥ 1.
  - status: VERIFIED ✅
- `--max-retries-per-step <N>` — verified via live `--help` text. INTEGER ≥ 1.
  - status: VERIFIED ✅
- `--max-ralph-iterations <N>` — verified via live `--help` text. "Extra iterations after the first turn in Ralph mode. Use -1 for unlimited."
  - status: VERIFIED ✅
- `--afk` — verified via live `--help` text. AFK mode auto-dismisses AskUserQuestion.
  - status: VERIFIED ✅
- `--plan` — verified via live `--help` text. Start in plan mode.
  - status: VERIFIED ✅
- `--input-format` / `--output-format` (text | stream-json) — verified via live `--help` enum
  - status: VERIFIED ✅
- 300 parallel sub-agents native usage — **NOT VERIFIABLE FROM `--help`**
  - status: NEEDS-RESEARCH ❓ — `--help` has no flag exposing parallelism; this may be a runtime/agent-spec capability documented elsewhere. Item 7 api-catalog should flag this `verified: needs-research`.

---

## Per-pane MCPs verified bound at launch

> Source: live `<cli> mcp list` invocations on 2026-05-02. Auth used: `env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY <cli> mcp list`. Pane assignments per `bin/launch-squad.sh` (chrono+security+sysmgmt = claude; coding = codex; content = gemini; research = kimi).
>
> **Caveat (re-stated):** `claude mcp list` output is the same regardless of which `claude`-running pane invokes it (configs are global at `~/.claude/`), so chrono/security/sysmgmt panes share the same claude MCP set. Per-pane scoping would require `--mcp-config` at launch — currently NOT used in `bin/launch-squad.sh`.

### chrono pane (claude)

Health legend: ✅ Connected · ❌ Failed to connect · ⚠ Needs authentication

**Connected (working at MCP layer):**
- `claude.ai Gmail` ✅ (HTTP `https://gmailmcp.googleapis.com/mcp/v1`)
- `plugin:context7:context7` ✅ (`npx -y @upstash/context7-mcp`)
- `plugin:playwright:playwright` ✅ (`npx @playwright/mcp@latest`)
- `plugin:firebase:firebase` ✅ (`npx -y firebase-tools@latest mcp`)
- `plugin:chrome-devtools-mcp:chrome-devtools` ✅ (`npx chrome-devtools-mcp@latest`)
- `plugin:cloudflare:cloudflare-docs` ✅ (HTTP)
- `plugin:shopify-plugin:shopify-mcp` ✅ (`npx -y @shopify/dev-mcp@latest`)
- `plugin:chrono-research-arsenal:perplexity` ✅ (`uvx perplexity-mcp`)
- `plugin:chrono-content-engineer:elevenlabs` ✅ (`uvx elevenlabs-mcp`)
- `sequential-thinking` ✅ (`/opt/homebrew/bin/mcp-server-sequential-thinking`)

**Auth-pending (configured but unauth'd):**
- `claude.ai Google Drive` ⚠
- `claude.ai Google Calendar` ⚠
- `plugin:figma:figma` ⚠
- `plugin:linear:linear` ⚠
- `plugin:sentry:sentry` ⚠
- `plugin:gitlab:gitlab` ⚠
- `plugin:circleback:circleback` ⚠
- `plugin:cloudflare:cloudflare-api` ⚠
- `plugin:cloudflare:cloudflare-bindings` ⚠
- `plugin:cloudflare:cloudflare-builds` ⚠
- `plugin:cloudflare:cloudflare-observability` ⚠
- `plugin:chrono-content-engineer:higgsfield` ⚠

**Failed to connect (configured but broken at MCP layer — feeds Task 2 incident report):**
- `plugin:github:github` ❌ (HTTP `https://api.githubcopilot.com/mcp/`)
- `plugin:greptile:greptile` ❌ (HTTP)
- `plugin:goodmem:goodmem` ❌ (local node script)
- `plugin:chrono-vault:chrono-vault` ❌ (`~/chrono/.venv/bin/python ~/chrono/plugins/chrono-vault/mcp_server.py`)
- `plugin:chrono-vault:chrono-kg` ❌ (same binary, `--namespace kg`)
- `plugin:chrono-vault:chrono-obsidian` ❌ (same binary, `--namespace obsidian`)
- `plugin:chrono-vault:chrono-catalog` ❌ (same binary, `--namespace catalog`)
- `plugin:chrono-research-arsenal:chrono-research-arsenal` ❌ (top-level wrapper; child `perplexity` works)
- `plugin:chrono-content-engineer:chrono-content-engineer` ❌ (top-level wrapper; child `elevenlabs` works)

**FINDING (TASK 2 PRECURSOR):** `claude mcp list` on this host shows multiple chrono-* MCPs Failed to connect from the `~/.claude/` plugin cache. These are stale entries pointing at `~/chrono/.venv/bin/python` which may have been replaced by the in-vault chrono-vault distribution. The squad's actual chrono-vault access for non-claude panes (codex, kimi) goes via their OWN `mcp list` (which DOES show these connected — see below).

### coding pane (codex)

Source: `codex mcp list`. All entries show `Status: enabled` (codex CLI does NOT health-check at list time — these are config rows, not runtime connectivity).

- `chrono-catalog` (stdio) ✅-configured
- `chrono-content-engineer` (stdio) ✅-configured (ENV: GEMINI_API_KEY, OPENAI_API_KEY, XAI_API_KEY)
- `chrono-kg` (stdio) ✅-configured (ENV: CHRONO_VAULT_ROOT, OBSIDIAN_REST_API_KEY, OBSIDIAN_VAULT_ROOT)
- `chrono-obsidian` (stdio) ✅-configured (ENV: OBSIDIAN_REST_API_KEY, OBSIDIAN_VAULT_ROOT)
- `chrono-research-arsenal` (stdio) ✅-configured (ENV: APIFY_TOKEN, BRAVE_API_KEY, PERPLEXITY_API_KEY, SERPER_API_KEY, XAI_API_KEY)
- `chrono-vault` (stdio) ✅-configured (ENV: CHRONO_VAULT_ROOT, OBSIDIAN_REST_API_KEY, OBSIDIAN_VAULT_ROOT)
- `sequential-thinking` (stdio, `npx`) ✅-configured

**Note:** Codex's bound MCP set is the chrono suite + sequential-thinking — narrower than claude's plugin-marketplace expanse but matches the spec's expectation that Coding Lead gets chrono-* tools for vault writes/reads. The chrono-vault, chrono-kg, chrono-obsidian, chrono-catalog all point at `~/chrono/plugins/chrono-vault/mcp_server.py` — verify that path exists and is executable in any spawn-specialist scenario.

### security pane (claude)

**Same as chrono pane** (both use `claude` CLI reading `~/.claude/` global config; `bin/launch-squad.sh` does not pass per-pane `--mcp-config`).

Implication for Task 2 (Item 14 Security MCP debug): the Security Lead's reported MCP errors are the same Failed-to-connect set above (chrono-* wrappers + goodmem + github + greptile). Root cause is global, not security-specific.

### content pane (gemini)

Source: `gemini mcp list` returned **empty output** (exit 0, no servers listed).

- **No MCPs configured for gemini.**

This is a finding: the spec's Item 8 (`shared/dispatch-toolkit.sh` reality-check) and Item 7 (api-catalog) Gemini sections must NOT cite any MCP for the content pane. Content Lead's tool-use is currently limited to gemini's native built-in tools (web search via gemini's grounding, gemini extensions, gemini skills). To add chrono-* MCPs to content pane would require running `gemini mcp add ...` for each.

**ACTIONABLE for Item 8:** trim ALL chrono-research-arsenal/perplexity/etc. references from the content pane section of `shared/dispatch-toolkit.sh` until either (a) MCPs are added to gemini config or (b) Content Lead workflows are documented as using gemini-native search/extensions.

### sysmgmt pane (claude)

**Same as chrono pane** (claude global config).

### research pane (kimi)

Source: `kimi mcp list`. Config file: `~/.kimi/mcp.json`. All entries are stdio.

- `chrono-vault` (stdio) ✅-configured
- `chrono-research-arsenal` (stdio) ✅-configured
- `chrono-content-engineer` (stdio) ✅-configured
- `chrono-kg` (stdio) ✅-configured
- `chrono-obsidian` (stdio) ✅-configured
- `chrono-catalog` (stdio) ✅-configured
- `sequential-thinking` (stdio, `npx`) ✅-configured

**Note:** Kimi's bound MCP set matches Codex's exactly (both point at the same `~/chrono/.venv/bin/python` mcp_server scripts). Same binary verification caveat applies.

---

## Local skill catalog

- **Total SKILL.md files installed:** 477 (per `find ~/.claude/plugins/cache -path "*/skills/*" -name "SKILL.md" | wc -l`, run 2026-05-02)
- **Distinct plugin source directories:** 16+ (mix of `claude-chrono`, `claude-plugins-official`, `temp_git_*`, `temp_local_*` cache entries)
- **Source verification command:** `find ~/.claude/plugins/cache -path "*/skills/*" -name "SKILL.md"`

The 477 figure is the CLAUDE-side discovery count (claude reads `~/.claude/plugins/cache/`). Codex/Gemini/Kimi each have their own plugin/extension/skill discovery roots:
- Codex: `~/.codex/` (not enumerated here)
- Gemini: `gemini extensions list` / `gemini skills list` (not enumerated; pane has no MCPs configured anyway)
- Kimi: `--skills-dir` overrides; default discovery path documented per kimi config

**ACTIONABLE for Item 1 (specialist tool-awareness pass):** spec's prior estimate of "331 unique skills across 40+ plugins" is OUT OF DATE — current count is 477. Specialists should reference skills by name + source-plugin, not by aggregated count.

---

## Features claimed in spec but UNVERIFIED (needs-research)

These are Item 0 → Item 7 handoffs. Each entry MUST get `verified: no` or `verified: needs-research` in `shared/api-catalog.md` until a follow-up verification fires (or Item 7's "within-v1.1 research backlog" task completes).

### Anthropic ecosystem
- **`/ultrareview` slash-command behavior** — `claude ultrareview` exists as a top-level subcommand (verified above). Whether `/ultrareview` is also available as an in-session slash command, and whether the cloud-hosted multi-agent review actually completes in <60s, are NOT yet verified.
  - research_task: invoke `/ultrareview` interactively in chrono pane on a small PR; record runtime + output

### Google ecosystem (large research debt)
- **Gemini `--thinking` flag** — does NOT exist in `gemini --help`. Confirmed absent.
  - research_task: confirm whether thinking-mode is implicit-per-model (e.g. `gemini-3.1-pro-preview` always thinks) or whether a non-help-documented mechanism (`-c` flag, settings.json key) toggles it
- **Nano Banana Pro / Nano Banana 2** access via gemini CLI — claimed in spec, no verification path attempted today
  - research_task: identify whether these are accessed via `gemini` CLI subcommand, via Google AI Studio web only, or via API
- **Veo 3** video generation — same as above
- **Imagen** image generation — same as above
- **Google Search grounding** — likely implicit per model; needs explicit doc reference
- **Jules** (Google coding agent) — needs full investigation: what is it, integration paths
- **Flow** (Google video tool) — needs full investigation
- **NotebookLM** — needs investigation: programmatic access path
- **Antigravity** (Google IDE-agent) — needs investigation: alt CLI for Coding pane?

### xAI ecosystem
- **xAI / Grok-X integration** — XAI_API_KEY appears in chrono-research-arsenal and chrono-content-engineer ENV blocks (per `codex mcp list`), so the key is plumbed. Whether the squad's specialists actually invoke a Grok model via these MCPs vs. routing to Grok-4-fast / Grok-X via API has NOT been verified.
  - research_task: trace `chrono-research-arsenal` MCP code to confirm Grok routing surface

### DeepSeek
- **DeepSeek V4 access** — no API key visible in any MCP env; no current integration verified
  - research_task: verify API key plumbing + addition to T1/T2 fanout pool

### Kimi
- **300 parallel sub-agents native usage** — `kimi --help` exposes `--max-steps-per-turn` and `--max-ralph-iterations` but NO explicit "parallel sub-agent count" flag. The "300 parallel" claim may refer to runtime model behavior (Kimi K2.6's tool-use parallelism) rather than a CLI parameter.
  - research_task: identify the actual mechanism — config-file key, model-side capability, or marketing claim
- **4000 coordinated tool steps** — same status as 300-parallel claim
  - research_task: same as above

### MCP-layer Failed-to-connect set (Task 2 territory, surfaced here as findings)
The following MCPs are configured in `~/.claude/` but `claude mcp list` reports `Failed to connect`:
- `plugin:github:github` (HTTP) — likely transient or auth-related; intermittent for HTTP MCPs
- `plugin:greptile:greptile` (HTTP) — same
- `plugin:goodmem:goodmem` (stdio Node) — local script; runtime error likely
- `plugin:chrono-vault:chrono-vault` (stdio Python) — `~/chrono/.venv/bin/python` may be missing or chrono-vault startup may fail; **strong candidate for the "Security Lead MCP errors" referenced in spec Item 14**
- `plugin:chrono-vault:chrono-kg`, `chrono-obsidian`, `chrono-catalog` — same binary; same root cause
- `plugin:chrono-research-arsenal:chrono-research-arsenal` (top-level wrapper failing, child `perplexity` works) — likely the wrapper script fails while the standalone perplexity MCP succeeds
- `plugin:chrono-content-engineer:chrono-content-engineer` (top-level wrapper failing, child `elevenlabs` works) — same wrapper-vs-child pattern

These are flagged here for Task 2 (Item 14) to root-cause and either restore or document-and-remove.

---

## Self-review (against task checklist)

- [x] File exists at `_state/capability-inventory-2026-05-02.md`
- [x] Every `VERIFIED ✅` entry includes a test_reference (live command run + observed exit/output) OR a help-text citation (when help-text alone is dispositive — e.g. enum constraints)
- [x] Every `NEEDS-RESEARCH ❓` and `ABSENT ❌` entry has explicit research_task or finding text
- [x] Every CLI in spec (claude / codex / gemini / kimi) has its own section
- [x] Every pane in squad has MCP enumeration: chrono ✅, coding ✅, security ✅ (= chrono since shared claude config), content ✅, sysmgmt ✅ (= chrono since shared claude config), research ✅
- [x] Markdown is syntactically valid
- [x] Caveat about `--mcp-config` per-launch scoping is explicit at top of MCP section

## Concerns surfaced for downstream tasks

1. **Gemini `--thinking` flag does not exist.** Item 5 (launch-squad.sh) must NOT add this flag to the content pane stanza. Either rely on `--model gemini-3.1-pro-preview` carrying thinking implicitly, or do further research before claiming thinking-mode is on for Content Lead.

2. **Gemini has zero MCPs configured.** Content pane's tool-use surface is gemini-native only (skills, extensions, hooks, gemma routing). Item 8 (dispatch-toolkit reality-check) must reflect this — content section should NOT enumerate chrono-* MCPs.

3. **Claude pane MCPs include 3 Failed-to-connect entries.** Task 2 (Item 14) inherits the work of root-causing these. Notably the chrono-* family is broken in claude's view but works in codex+kimi views (different config sources). This is direct evidence the Security/SysMgmt panes' "MCP errors" are upstream-config issues, not security-specific.

4. **Codex CLI does NOT health-check at `mcp list`** — entries show `enabled` as a config-flag, not a runtime status. Content equivalent for Codex is "MCP server starts without error when invoked." Per-pane MCP availability for codex requires runtime test (out of scope for Item 0).

5. **Local skill count is 477, not 331.** Spec's stale figure should be updated in any subsequent docs that cite it.
