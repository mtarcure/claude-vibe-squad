#!/usr/bin/env python3
"""Focused tests for guarded-subset validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("validate_staged.py")
SPEC = importlib.util.spec_from_file_location("validate_staged", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GuardedSubsetTests(unittest.TestCase):
    def test_live_config_allows_unrelated_mcp(self) -> None:
        servers = {name: {} for name in MODULE.EXPECTED}
        servers["playwright"] = {}
        guarded, issues = MODULE.guarded_subset(
            "live", servers, allow_unrelated=True
        )
        self.assertEqual(list(guarded), MODULE.EXPECTED)
        self.assertEqual(issues, [])

    def test_staged_mirror_rejects_unrelated_mcp(self) -> None:
        servers = {name: {} for name in MODULE.EXPECTED}
        servers["playwright"] = {}
        _guarded, issues = MODULE.guarded_subset(
            "staged", servers, allow_unrelated=False
        )
        self.assertIn("staged:unexpected-extra-server", issues)


if __name__ == "__main__":
    unittest.main()

