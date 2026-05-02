# Contributing to claude-vibe-squad

Thanks for considering a contribution. The squad is a small, opinionated framework — the bar for additions is **does this make a single-operator squad work better, with no power-user prerequisites?** If you can answer yes, the patch is welcome.

## Philosophy you'll be matched against

These aren't aspirations — they're how PRs get evaluated:

- **Vibe-coder friendly.** A non-tmux-power-user should be able to clone the repo, run `bash bin/launch-squad.sh`, attach, and start working. Anything that adds a setup step needs to justify it.
- **Walk-away friendly.** Modes pause at hard gates, never on time. No background process should require the operator to be present.
- **Markdown-first.** Mode workflows, specialist roles, mailbox messages — all human-readable markdown in the vault. If your patch hides behavior in code that should live in markdown, it'll bounce.
- **Subscription-first auth.** The squad runs on Claude Max, ChatGPT Plus, Gemini OAuth, Kimi login. Nothing should add a hard dependency on pay-per-token API keys. Optional API features are fine if they're flagged off by default.
- **Adversarial by default.** High-stakes specialist output gets reviewed by an opposite-family model. If your patch adds a new specialist, declare its `multi_model` requirement and reviewer chain.
- **No silent KG mutation.** Auto-routines propose; the operator approves. Don't add code paths that quietly modify the operator's vault.

## Setup for development

```bash
git clone https://github.com/mtarcure/claude-vibe-squad.git
cd claude-vibe-squad
brew install tmux uv jq fswatch  # core tooling

# Make sure you've installed + logged into all 4 CLIs:
#   claude (Claude Code), codex (OpenAI), gemini (Gemini CLI), kimi (Moonshot)

bash bin/launch-squad.sh
tmux attach -t squad
```

The repo IS its own working vault — there's no separate "dev" copy. Editing files in your clone takes effect immediately when scripts re-read them.

## What's likely to land

- **New specialists** under `shared/specialists/` or `departments/<lead>/specialists/` (markdown role files with `multi_model` flag)
- **New mode profiles** under `shared/mode-profiles/<mode>/` for new target types (e.g., a new bounty profile for a specific platform)
- **HTML-scrape configs** for additional vendor blogs (`_state/feed-config.yaml` — link patterns + processor)
- **Doctor checks** that catch new failure modes (process pathologies, MCP retry storms, quota anomalies)
- **Mailbox protocol extensions** that stay backward-compatible with existing send-task.sh
- **Bug fixes** with a clear reproducer

## What's unlikely to land without discussion

- Anything that adds a hard dependency (Python package, system binary, web service) — open an issue first
- New Lead departments — five is enough; if you have a domain that doesn't fit, propose a new specialist under an existing Lead
- Changes to the per-CLI identity loading mechanism — that's load-bearing and extensively tested
- Anything that bypasses the `vibecoding-check` exit verifier
- Anything that auto-applies dream proposals (the `aggressive` mode in `dream-config.yaml` exists but is gated behind explicit opt-in for a reason)

## How to propose a change

1. **Open an issue first** for anything bigger than a typo fix or a missing test. Describe the operator-facing improvement.
2. **Branch off `main`** with a descriptive name: `feat/<thing>` or `fix/<thing>`.
3. **Run the dispatch smoke test** before opening the PR:
   ```bash
   bash bin/launch-squad.sh
   bash scripts/send-task.sh coding /path/to/test-task.md
   # Wait for response in departments/coding/outbox/
   ```
4. **Run vibecoding-check** if your patch touches a mode flow:
   ```bash
   bash bin/vibecoding-check.sh --run-id <test-run-id>
   ```
5. **Commit messages** follow the shape used in `git log` — concise subject, bulleted body.
6. **Open the PR** with a clear summary of what changes for an operator using the squad day-to-day.

## Code style

- **Bash:** `set -uo pipefail` at the top. `${VAR:-default}` for any operator-overridable parameter. `mkdir -p` before any write. Atomic writes (temp + `mv`) for state files.
- **Python:** uv-managed inline metadata (`# /// script` block) for any new script under `scripts/python/`. No `requirements.txt`. Type hints where they help, not as ritual. `>=3.11` minimum.
- **Markdown:** YAML frontmatter for every specialist / mode / mode-profile file. The `multi_model` field is required on specialist files.

## Testing

There's no formal test suite yet — the squad is filesystem + tmux orchestration, hard to unit-test in the conventional sense. The operational tests are:

- `bin/doctor.sh` — passes with `issue_count: 0`
- `bin/launch-squad.sh` followed by 5-Lead headless ping (one task per Lead, all return responses)
- `bin/vibecoding-check.sh` smoke run
- `bin/verify.sh --writer claude --reviewer kimi --output <sample>` returns a structured verdict

If your patch touches one of these paths, add the corresponding smoke check to your PR description.

## Where to ask

- **Issues** — for bugs, feature proposals, design questions
- **Discussions** — for "is this how I should use the squad?" / setup questions / use-case sharing

If you're contributing your first PR and unsure about scope or style, just open the issue and ask before writing code. The maintainer would rather give you a quick yes/no on direction than have you write something that doesn't fit.

## License

By contributing, you agree your contribution will be licensed under the [AGPL-3.0](LICENSE) license that covers the rest of the project.
