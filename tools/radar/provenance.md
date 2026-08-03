# Source and license provenance

- Upstream: `Auditware/radar`
- Resolved upstream commit: `2327887cd47a2bcc71b7a6d0f88f60c9db026436` (GitHub connector result, commit date 2026-07-09)
- Upstream license: GPL-3.0-only (`LICENSE` and `api/pyproject.toml` returned by the connector)
- Upstream files inspected: `README.md`, `install-radar.sh`, `radar`, `docker-compose.yml`, `docs/How-to-Write-Templates.md`, and selected built-in templates/tests.
- `templates/positive-control-pda-sharing.yaml` is an unmodified internal copy of upstream `api/builtin_templates/pda_sharing.yaml` at the pinned commit.
- `compose.yaml` is marked as a task-isolated derivative of the upstream compose file; it removes host-published ports/global container names and does not invoke pruning.
- `templates/missing-pda-seeds-canary.yaml`, both fixture projects, and `bin/*.sh` are task-authored.

Primary source links:

- <https://github.com/Auditware/radar/tree/2327887cd47a2bcc71b7a6d0f88f60c9db026436>
- <https://github.com/Auditware/radar/blob/2327887cd47a2bcc71b7a6d0f88f60c9db026436/docs/How-to-Write-Templates.md>
- <https://github.com/Auditware/radar/blob/2327887cd47a2bcc71b7a6d0f88f60c9db026436/api/builtin_templates/pda_sharing.yaml>

