# Container path

The one operator guide for running Vibe Squad in Docker. Host install stays
[README.md](README.md). Do not copy install facts here — this page is the
volume map, profiles, and validation commands.

Model lanes stay **native-CLI OAuth**. API keys in `.env` never authenticate
`claude` / `codex` / `agy` / `kimi`. See [provider-clis.md](provider-clis.md).

## Profiles

| Profile | Image target | What it does |
|---|---|---|
| `test` | `test` | `SQUAD_CI_HOST_INDEPENDENT=1 bin/test --fast` |
| `runtime` | `runtime` | `daemon` (uvicorn `:9876`) + `squad` (`bin/squad up`) |
| `tools` | `tools` | runtime plus `scripts/bootstrap-mcps.sh` wiring |

`tools` builds `runtime` as well: its `volume-init` runs from that image.

```bash
cp .env.example .env          # then fill values you actually use
docker compose --profile test build
docker compose --profile test run --rm test
docker compose --profile runtime up
```

## Volume map (never baked into the image)

| Host / named volume | Container | Why |
|---|---|---|
| named `chrono-vault` or `$CHRONO_VAULT_ROOT` | `/vault` | private memory; `volume-init` chowns to uid 1000, then the entrypoint writes `.chrono-vault` if missing |
| named `squad-state` | `/squad/_state` | runtime when the repo is copied rather than bind-mounted; same chown |
| `~/.claude`, `~/.codex`, agy/kimi/grok config dirs | matching paths under `/home/squad` | CLI OAuth; mount only if you have them |
| repo checkout | `/squad` (optional bind) | live worktrees need `.git` |

`.env` is `env_file` (optional). Docker secrets / Key Vault CSI land in
`SQUAD_SECRETS_DIR` (default `/run/secrets`). Load order is
`shared/load-secrets.sh`.

## What stays out of `test` and `runtime`

- Trail of Bits `mcp-context-protector` and guarded security MCPs
- Bounty arsenal / ItyFuzz / Playwright browsers
- Moat Colima e2e

A PR check that finds those in `vibe-squad:test` or `vibe-squad:runtime` fails
the size contract.

## Provider CLIs inside the image

Hard Rule 9: a capability is proven by a live probe, not a Dockerfile line.
The runtime image does **not** pretend to contain `claude` / `codex` / `agy` /
`grok` / `kimi`. If a provider has a Linux installer you trust, bind-mount the
host binary and its auth dir. `bin/squad doctor` reports CLI auth as UNKNOWN
until those dirs are mounted.

## Validation (record literal command + literal result)

```text
docker compose --profile test build
docker compose --profile test run --rm test
# focused seams (what CI runs; --fast still host-couples some suites):
docker compose --profile test run --rm test python -m unittest \
  scripts.python.tests.test_linux_portability_seams \
  scripts.python.tests.test_research_credential_single_source \
  scripts.python.tests.test_doctor_launch_dependency_parity -v
docker images --format "{{.Repository}}:{{.Tag}}\t{{.Size}}"
docker compose --profile runtime config
docker compose --profile runtime up -d
# doctor inside runtime: required commands present; CLI auth UNKNOWN unless dirs mounted
# if daemon on: curl 127.0.0.1:9876/health
docker compose --profile runtime down
```

## Size budgets

Measured 2026-09-06 on Docker Desktop (Windows host), then pinned. These
predate the 2026-09-07 build changes (`.claude/worktrees` excluded from the
context, whole-tree `chown -R` layer dropped), which only move the numbers
down — re-measure before tightening a ceiling:

- `vibe-squad:test`: 605 MB (ceiling 650 MB). Over the first-pass 250–400 MB
  guess because the image copies the checkout plus `.git` (suite inventory
  is `git ls-files`) and a locked `uv sync`. No Node, no provider CLIs.
- `vibe-squad:runtime`: 1.04 GB (ceiling 1200 MB). Node 22 + tmux +
  inotify-tools + `uv sync --no-dev`. Still no context-protector, browsers,
  or bounty arsenal.

`VIBESQUAD_DAEMON_TOKEN` is required to construct the daemon app (even
`/health`). Compose passes the host value when set; the entrypoint mints a
process-local token when it is empty so `runtime` healthchecks work without
a host `.env`. Override it in `.env` for anything beyond localhost.
