"""Shared skip policy for tests that require trusted host infrastructure."""

from __future__ import annotations

import os
from collections.abc import Callable
import unittest
from typing import TypeVar


HOST_INDEPENDENT_ENV = "SQUAD_CI_HOST_INDEPENDENT"
_TestItem = TypeVar("_TestItem", bound=Callable[..., object] | type)


def skip_in_host_independent_ci(reason: str) -> Callable[[_TestItem], _TestItem]:
    """Skip a live-host test only when the explicit CI boundary is enabled."""

    return unittest.skipIf(
        os.environ.get(HOST_INDEPENDENT_ENV) == "1",
        f"host-dependent: {reason}",
    )
