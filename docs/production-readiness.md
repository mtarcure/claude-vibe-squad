# Production Readiness

Supported platform is macOS first.

## Release Checklist

- `bash -n bin/*.sh scripts/*.sh shared/*.sh`
- `python3 -m py_compile scripts/python/*.py bin/*.py`
- `bash bin/validate-specialists.sh`
- `bash bin/validate-capabilities.sh`
- `bash bin/test`
- `bash bin/doctor.sh`
- `bash bin/mcp-audit.sh`
- `bash bin/product-hygiene.sh --public-export`
- Dispatch smoke test in a temporary checkout
- Fresh clone setup test
- Confirm no runtime/private file patterns are staged

## Public Commands

- `squad up` launches autonomous daily-driver mode.
- `squad up --safe` launches conservative permissions mode.
- `squad stop` writes a handoff and stops the tmux session.
- `squad status` prints canonical live state.
- `squad doctor` runs health checks.

## Script Policy

Keep public entrypoints stable even when implementation moves:

- `bin/squad` is the main user interface.
- `scripts/send-task.sh` remains Chrono's compatibility entrypoint.
- `bin/send-task.sh` remains the hardened dispatch primitive.
- Tiny shell wrappers are acceptable when they give a stable command name around a larger Python implementation.
- One-off migration scripts should move to `tools/` or `docs/legacy/` after they are no longer needed at runtime.

## Known Limitations

- MCP audit can verify stdio server usability, but CLI-specific MCP invocation quality still depends on each CLI's current implementation.
- Kimi has no per-directory auto-load convention, so a board-spawned Kimi specialist is given an explicit role-read instruction in its task packet rather than inheriting one from its working directory.
- Kimi subagents cannot hold MCP, so any MCP work on a Kimi-routed specialist must be brokered rather than performed in-subagent.
- Public CI cannot validate private OAuth state or local Chrome CDP sessions.
