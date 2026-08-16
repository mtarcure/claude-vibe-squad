#!/usr/bin/env python3
"""Run the export-gate test suite, and fail if there was no suite to run.

This exists because the suite it runs was, until 2026-08-11, wired into nothing.
`grep -n "tools/export" bin/test .github/workflows/*.yml` returned no match:
thirty-two tests covering the gate that decides what becomes public had never
been executed by CI or by the unified runner, and nothing about the repository
looked any different for it.

    python3 tools/export/tests/run_tests.py

The zero-test refusal is the same principle the suite tests for elsewhere. A
discovery path that silently matches nothing exits 0 and prints "OK", which is
indistinguishable from a passing gate -- and an import error inside a test
module makes unittest's discovery skip that module rather than fail. Both are
counted here and both are fatal.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[2]

#: Every `test_*.py` beside this file is expected to contribute. Discovery that
#: comes back short means a module failed to import, not that it had nothing to
#: say.
MINIMUM_TESTS = 1


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(TESTS_DIR), top_level_dir=str(REPO_ROOT))

    if loader.errors:
        for error in loader.errors:
            print(error, file=sys.stderr)
        print(f"{len(loader.errors)} test module(s) failed to import; "
              f"a suite that cannot load has not passed", file=sys.stderr)
        return 2

    discovered = suite.countTestCases()
    modules = sorted(path.name for path in TESTS_DIR.glob("test_*.py"))
    if discovered < MINIMUM_TESTS or not modules:
        print(f"discovered {discovered} test(s) from {len(modules)} module(s) under "
              f"{TESTS_DIR}; refusing to report success for an empty run",
              file=sys.stderr)
        return 2

    print(f"export-gate suite: {discovered} test(s) from {len(modules)} module(s) "
          f"({', '.join(modules)})")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
