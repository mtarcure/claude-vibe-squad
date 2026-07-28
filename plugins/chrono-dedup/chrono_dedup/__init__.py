"""Prior-art and duplicate detection for findings and composite chains."""

from .core import (
    composite_chain_key,
    finding_key,
    prior_art_check,
)

__all__ = ["composite_chain_key", "finding_key", "prior_art_check"]
