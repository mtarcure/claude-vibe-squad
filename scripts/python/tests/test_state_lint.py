#!/usr/bin/env python3
"""Plan B Task 10 -- lints for the two defect shapes no `except:` count sees.

daemon/main.py fired `asyncio.create_task(WATCHER.run())` with no
done-callback (silent exceptions for the process's whole life), and
daemon/watcher.py / daemon/routes/task.py / bin/vs-board-dashboard.py /
bin/vs-board-snapshot.py defaulted VAULT_ROOT to the maintainer's own
home-relative path (phantom directory on any other machine). See
scripts/python/state_lint.py for the full rationale.

The synthetic-snippet tests below pin the two rules' true/false-positive
boundary. Plan B task 6 (2026-08-17) fixed all five live sites -- `python3
scripts/python/state_lint.py` now reports zero -- so the tests that used to
assert the checker still fires on the actual daemon/main.py and
daemon/watcher.py are now synthetic-snippet regression pins too (see
HistoricalDefectShapesStillFlagTests below), reconstructing the exact shape
those files shipped with rather than depending on files that were correctly
fixed out from under them.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import state_lint  # noqa: E402


def _rules(source: str) -> list[str]:
    return [v.rule for v in state_lint.find_violations(source)]


class DanglingCreateTaskTests(unittest.TestCase):
    def test_flags_stored_task_with_no_done_callback(self) -> None:
        src = """
import asyncio

async def lifespan():
    watcher_task = asyncio.create_task(WATCHER.run())
    try:
        yield
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
"""
        self.assertEqual(_rules(src), [state_lint.DANGLING_CREATE_TASK])

    def test_allows_task_with_done_callback(self) -> None:
        src = """
import asyncio

async def lifespan():
    watcher_task = asyncio.create_task(WATCHER.run())
    watcher_task.add_done_callback(_log_task_exception)
    yield
"""
        self.assertEqual(_rules(src), [])

    def test_allows_chained_create_task_with_immediate_callback(self) -> None:
        src = """
import asyncio

def fire():
    asyncio.create_task(background()).add_done_callback(_log_task_exception)
"""
        self.assertEqual(_rules(src), [])

    def test_allows_create_task_passed_directly_to_gather(self) -> None:
        src = """
import asyncio

async def run_all(coros):
    await asyncio.gather(*(asyncio.create_task(c) for c in coros))
"""
        self.assertEqual(_rules(src), [])

    def test_matches_loop_create_task_receiver(self) -> None:
        src = """
import asyncio

def fire():
    loop = asyncio.get_running_loop()
    t = loop.create_task(background())
"""
        self.assertEqual(_rules(src), [state_lint.DANGLING_CREATE_TASK])

    def test_callback_in_nested_function_does_not_satisfy_outer_scope(self) -> None:
        src = """
import asyncio

def outer():
    t = asyncio.create_task(background())

    def inner():
        t.add_done_callback(_log_task_exception)
"""
        # The callback is only *referenced* inside inner(), never called from
        # outer() -- outer() still leaks the task if inner() is never invoked.
        self.assertEqual(_rules(src), [state_lint.DANGLING_CREATE_TASK])

    # -- Fix round 1: the four probes team-lead ran directly. Pinned together
    # because the false negative (bare call) and the false positive
    # (TaskGroup) are coupled -- fixing one without the other regresses.

    def test_probe_1_bare_create_task_is_flagged(self) -> None:
        src = """
import asyncio

def fire():
    asyncio.create_task(work())
"""
        self.assertEqual(_rules(src), [state_lint.DANGLING_CREATE_TASK])

    def test_probe_2_stored_create_task_is_flagged(self) -> None:
        src = """
import asyncio

def fire():
    t = asyncio.create_task(work())
"""
        self.assertEqual(_rules(src), [state_lint.DANGLING_CREATE_TASK])

    def test_probe_3_bare_taskgroup_create_task_is_not_flagged(self) -> None:
        src = """
import asyncio

async def fire():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(work())
"""
        self.assertEqual(_rules(src), [])

    def test_probe_4_assigned_taskgroup_create_task_is_not_flagged(self) -> None:
        src = """
import asyncio

async def fire():
    async with asyncio.TaskGroup() as tg:
        t = tg.create_task(work())
"""
        self.assertEqual(_rules(src), [])


class HomeRelativeEnvDefaultTests(unittest.TestCase):
    def test_flags_path_home_joined_with_literal(self) -> None:
        src = """
import os
from pathlib import Path

vault_root = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
"""
        self.assertEqual(_rules(src), [state_lint.HOME_RELATIVE_ENV_DEFAULT])

    def test_flags_os_path_join_variant(self) -> None:
        src = """
import os
from pathlib import Path

root = os.environ.get("ROOT", os.path.join(str(Path.home()), "SomeApp"))
"""
        self.assertEqual(_rules(src), [state_lint.HOME_RELATIVE_ENV_DEFAULT])

    def test_flags_getenv_variant(self) -> None:
        src = """
import os
from pathlib import Path

root = os.getenv("ROOT", str(Path.home() / "SomeApp"))
"""
        self.assertEqual(_rules(src), [state_lint.HOME_RELATIVE_ENV_DEFAULT])

    def test_allows_repo_relative_default(self) -> None:
        src = """
import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VIBE_SQUAD_ROOT", Path(__file__).resolve().parents[1]))
"""
        self.assertEqual(_rules(src), [])

    def test_allows_bare_home_with_no_extra_segment(self) -> None:
        src = """
import os
from pathlib import Path

root = os.environ.get("ROOT", str(Path.home()))
"""
        self.assertEqual(_rules(src), [])

    def test_allows_bare_expanduser_tilde(self) -> None:
        src = """
import os

root = os.environ.get("ROOT", os.path.expanduser("~"))
"""
        self.assertEqual(_rules(src), [])

    def test_allows_dotfile_config_default(self) -> None:
        # The real false positive this rule was tightened for (2026-08-17):
        # scripts/python/browser_keep_alive.py defaults an optional,
        # read-only, missing-file-tolerant config path to ~/.config/chrono/...
        # -- the ordinary XDG idiom, not the VAULT_ROOT phantom-directory bug.
        src = """
import os
from pathlib import Path

path = Path(os.environ.get(
    "CHRONO_BROWSER_TABS_FILE",
    str(Path.home() / ".config" / "chrono" / "browser-tabs.json"),
))
"""
        self.assertEqual(_rules(src), [])

    def test_flags_joinpath_variant_with_non_dotfile_segment(self) -> None:
        src = """
import os
from pathlib import Path

root = os.environ.get("ROOT", str(Path.home().joinpath("SomeApp", "data")))
"""
        self.assertEqual(_rules(src), [state_lint.HOME_RELATIVE_ENV_DEFAULT])

    def test_allows_no_default_at_all(self) -> None:
        src = """
import os

home = os.environ.get("HOME")
"""
        self.assertEqual(_rules(src), [])

    def test_allows_empty_string_default(self) -> None:
        src = """
import os

home = os.environ.get("HOME", "")
"""
        self.assertEqual(_rules(src), [])


class HistoricalDefectShapesStillFlagTests(unittest.TestCase):
    """Originally pinned the checker against the two real files (daemon/main.py,
    daemon/watcher.py) the defects shipped in, so a future weakening of the
    rule couldn't silently stop catching the shape it was written for. Plan B
    task 6 (2026-08-17) fixed both files -- correctly, since fixing them was
    exactly what the rule existed to make happen -- which would have made a
    file-path pin assert the bug is still live in code that no longer has it.
    Converted to synthetic snippets reconstructing the exact original shape
    instead, so this stays a true-positive regression pin without depending on
    a real file anyone is free to legitimately fix out from under it."""

    def test_daemon_main_dangling_task_shape_still_flagged(self) -> None:
        # The exact shape daemon/main.py:10 shipped with before task 6: a
        # create_task() result assigned to a name, awaited only in the
        # lifespan shutdown `finally`, no add_done_callback anywhere.
        src = """
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from daemon.watcher import WATCHER

@asynccontextmanager
async def lifespan(_app: FastAPI):
    watcher_task = asyncio.create_task(WATCHER.run())
    try:
        yield
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
"""
        self.assertIn(state_lint.DANGLING_CREATE_TASK, _rules(src))

    def test_daemon_watcher_home_default_shape_still_flagged(self) -> None:
        # The exact shape daemon/watcher.py:11 shipped with before task 6.
        src = """
import os
from pathlib import Path

def _state_dir() -> Path:
    vault_root = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
    return Path(os.environ.get("VIBESQUAD_STATE_DIR", str(vault_root / "daemon" / "state")))
"""
        self.assertIn(state_lint.HOME_RELATIVE_ENV_DEFAULT, _rules(src))


if __name__ == "__main__":
    unittest.main()
