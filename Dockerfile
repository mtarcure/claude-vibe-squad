# Vibe Squad layered images. Three targets, one file.
#
#   test     — hermetic CI: python + uv + git/jq/curl/bash. No Node, no CLIs, no tmux.
#   runtime  — isolated deploy: tmux, inotify-tools, uv, Node (Codex only).
#   tools    — runtime plus utility-MCP bootstrap wiring.
#
# Do not bake Trail of Bits mcp-context-protector, Playwright browsers, or the
# bounty arsenal. Those stay optional bind-mounts. See docs/install/container.md.

# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS test

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

RUN useradd --create-home --uid 1000 --shell /bin/bash squad
WORKDIR /squad
COPY --chown=squad:squad . /squad
RUN find /squad \( -name '*.sh' -o -name '*.py' -o -name 'squad-watch' \
            -o -name 'squad' -o -name 'test' -o -path '*/.githooks/*' \) \
        -type f -exec sed -i 's/\r$//' {} + \
    && chmod +x /squad/scripts/container-entrypoint.sh /squad/bin/squad-watch \
        /squad/bin/squad /squad/bin/test /squad/bin/doctor.sh \
    && { [ ! -f /squad/.githooks/pre-commit ] || chmod +x /squad/.githooks/pre-commit; } \
    && chown -R squad:squad /squad

USER squad
ENV HOME=/home/squad \
    VAULT_ROOT=/squad \
    PATH="/squad/bin:/home/squad/.local/bin:/usr/local/bin:${PATH}" \
    UV_LINK_MODE=copy

RUN uv sync

ENV SQUAD_CI_HOST_INDEPENDENT=1
ENTRYPOINT ["/squad/scripts/container-entrypoint.sh"]
CMD ["bin/test", "--fast"]

# ---------------------------------------------------------------------------
# runtime
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        inotify-tools \
        jq \
        tmux \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

# Minimal Node for Codex only. Not Playwright, not a browser runtime.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash squad
WORKDIR /squad
COPY --chown=squad:squad . /squad
RUN find /squad \( -name '*.sh' -o -name '*.py' -o -name 'squad-watch' \
            -o -name 'squad' -o -name 'test' -o -path '*/.githooks/*' \) \
        -type f -exec sed -i 's/\r$//' {} + \
    && chmod +x /squad/scripts/container-entrypoint.sh /squad/bin/squad-watch \
        /squad/bin/squad /squad/bin/test /squad/bin/doctor.sh \
    && { [ ! -f /squad/.githooks/pre-commit ] || chmod +x /squad/.githooks/pre-commit; } \
    && chown -R squad:squad /squad

USER squad
ENV HOME=/home/squad \
    VAULT_ROOT=/squad \
    PATH="/squad/bin:/home/squad/.local/bin:/usr/local/bin:${PATH}" \
    UV_LINK_MODE=copy \
    SQUAD_DAEMON_MODE=process

RUN uv sync --no-dev

# Provider CLIs are not baked: Linux installers and auth dirs vary, and a
# missing binary must stay a bind-mount rather than a pretend capability
# (CLAUDE.md Hard Rule 9). See docs/install/container.md.

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD bash -c 'if [ "${SQUAD_DAEMON_MODE:-}" = process ]; then curl -fsS http://127.0.0.1:9876/health; else true; fi'

ENTRYPOINT ["/squad/scripts/container-entrypoint.sh"]
CMD ["bin/squad", "up"]

# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------
FROM runtime AS tools

# Same tree as runtime. Utility MCP registration is `scripts/bootstrap-mcps.sh`
# against mounted CLI auth dirs — no extra packages, no guarded security stack.
CMD ["bash", "scripts/bootstrap-mcps.sh", "--status"]
