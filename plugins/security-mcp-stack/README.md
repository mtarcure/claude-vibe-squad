# Cutover-ready security MCP stack

This directory controls the restart-gated Claude and gpt-codex security MCP cutover. The project-local lane files are now populated, but no running lane has been restarted or activated by this work.

Run the fail-closed static check before review or activation:

```bash
python3 plugins/security-mcp-stack/validate_staged.py
```

The validator compares the exact ordered guarded trio across the staged mirrors, Snyk target, and restart-discoverable lane configs. Unrelated verified MCPs may coexist in a live lane config; they are excluded from this stack's semantic comparison and are never mistaken for guarded children.

The restart-discoverable project-local lane configs are:

- `model-lanes/claude/.mcp.json`
- `model-lanes/gpt-codex/.codex/config.toml`

The retained `*.staged.*` files are exact review mirrors, not unwired leftovers:

- `model-lanes/claude/.mcp.security-arsenal.staged.json`
- `model-lanes/gpt-codex/.codex/security-arsenal.staged.toml`

All four files route Semgrep MCP, Slither MCP, and the remediated production-only Solodit MCP runtime through Trail of Bits' `mcp-context-protector`, in that order. Slither metrics are disabled; Semgrep receives no cloud token; Solodit receives no config-level env value and inherits `SOLODIT_API_KEY` only from the operator launch environment. `held-solodit.json` is now `activated-ready` and records the completed SDK 1.29.0 rebuild plus production install.

Context Protector is configured for schema pinning and ANSI escape visualization. No guardrail provider is configured, so response quarantine is not active and no `--quarantine-path` is claimed. The state-local database starts with the exact upstream shape `{"servers": []}`; therefore all downstream tools fail closed until the operator reviews and pins each schema during the cutover.

Snyk Agent Scan is a mandatory pre-activation gate, not an inline MCP server. `preactivate-security-stack.sh` fails closed unless inherited `SNYK_TOKEN` and `SOLODIT_API_KEY` are present, then scans the normalized `snyk-preactivation-targets.json` mirror with `--ci`. `validate_staged.py` rejects any semantic drift among the live Claude config, live Codex config, both review mirrors, and the Snyk target file.

Google Model Armor remains separate from this MCP stack and is explicitly `blocked-on-operator-credential` in `held-modelarmor.json`; no copied bearer token is configured.

Operator ask: Provide either the absolute path to a durable least-privilege Model Armor service-account JSON key via GOOGLE_APPLICATION_CREDENTIALS, or run `gcloud auth application-default login` for the gateway identity.

## Exact operator cutover

1. Obtain mandatory Claude approval for the frozen plan and artifact bundle; confirm `SOLODIT_API_KEY` and `SNYK_TOKEN` are available only in the inherited launch environment.
2. Run `python3 plugins/chrono-vault/provider_config_check.py`; any failure aborts. A preflight `validate_staged.py` may also be run here and must report `empty-unapproved-fail-closed` before pinning.
3. From an environment inheriting `SOLODIT_API_KEY`, run the Context Protector wrapper with `--review-server --server-config-file _state/tooling-arsenal-2026-07-18/mcp-context-protector/servers.json --command-args ...` once for each exact child command in the lane config: `/opt/homebrew/bin/semgrep mcp`, the state-local `slither-mcp --disable-metrics`, and `/opt/homebrew/bin/node` plus the production Solodit `dist/index.js`. Inspect each schema before approving it.
4. Run `plugins/security-mcp-stack/preactivate-security-stack.sh`; its `--ci` result must be zero. Any finding, runtime failure, missing credential, or unavailable verification service aborts the restart.
5. Run `python3 plugins/security-mcp-stack/validate_staged.py`; require `status: pass` and `context_config_state: three-reviewed-schemas-approved`.
6. Restart Claude and gpt-codex once through the normal squad launcher. Do not manually kill individual panes. Gemini and Kimi remain deferred.
7. In each restarted lane, require `tools/list` plus read-only synthetic fixture calls through all three guarded servers. Retain pinning/tool-call evidence; a config/list success alone is insufficient.
8. Run the existing chrono-vault record/recall parity probes. Promote a lane only if every applicable probe passes; otherwise restore the previously reviewed live registry inputs and perform one controlled launcher restart.

No restart, live lane mutation, Snyk network scan, Solodit API query, or Model Armor call was performed while preparing this configuration.
