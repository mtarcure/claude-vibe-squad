"""Server-owned sensitivity clearance for Chrono Vault MCP instances."""

from __future__ import annotations

import os


INTERNAL = "internal"
RESTRICTED = "restricted"
SENSITIVITIES = frozenset({INTERNAL, RESTRICTED})


class ClearanceError(PermissionError):
    """The current MCP instance may not return the requested note."""


def lane_clearance() -> str:
    """Return this process's configured clearance, defaulting fail-safe."""
    configured = os.environ.get("CHRONO_VAULT_CLEARANCE")
    if configured == RESTRICTED:
        return RESTRICTED
    return INTERNAL


def can_read(note_sensitivity: str, clearance: str) -> bool:
    """Return whether a server clearance permits one sensitivity label."""
    if note_sensitivity not in SENSITIVITIES:
        return False
    if note_sensitivity == INTERNAL:
        return True
    return note_sensitivity == RESTRICTED and clearance == RESTRICTED
