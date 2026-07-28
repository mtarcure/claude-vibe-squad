"""FastMCP entrypoint for target-scoped prior-art checking."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from chrono_dedup import prior_art_check as check_prior_art


mcp = FastMCP("chrono-dedup")


@mcp.tool()
def prior_art_check(
    target: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    """Check one finding or composite chain against public and private prior art."""
    return check_prior_art(target, item)


if __name__ == "__main__":
    mcp.run()
