"""`git commit` spawns a detached child; fixture repos must not let it.

~31 test files build a scratch repo (`git init` + `git add` + `git commit`)
inside a `tempfile.TemporaryDirectory` and delete it as soon as the test body
ends. `git commit` finishes by spawning

    git maintenance run --auto --quiet --detach

which daemonizes -- so `git commit` returns while that child is still alive and
holding the repo open. When it touches `.git` between `shutil.rmtree`'s scan and
its final `rmdir`, cleanup dies with `OSError: [Errno 39] Directory not empty`.
That took down two ubuntu-latest runs; the failing test's own assertions had all
passed, and the runner's orphan-process gate stayed green because nothing leaked.

`bin/test` exports GIT_CONFIG_* so every git call in the suite's process tree
disables auto-maintenance. These tests exist so that export cannot be dropped
without something going red.

The negative control is the point. It asserts git DOES spawn the child when the
guard is absent, so this file cannot pass by failing to measure -- if trace2 went
away or the probe broke, the control fails instead of quietly agreeing.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

GUARD_KEYS = ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_KEY_1")


def _commit_and_count_children(env: dict[str, str]) -> tuple[int, list[list[str]]]:
    """Commit into a throwaway repo; return spawned-child count and their argv."""
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        trace = repo.parent / f"trace-{repo.name}.json"
        run = lambda *a, **kw: subprocess.run(  # noqa: E731
            ("git", *a), cwd=repo, check=True, capture_output=True, **kw
        )
        run("init", "-q", ".")
        run("add", ".")
        run(
            "-c", "user.name=Fixture",
            "-c", "user.email=fixture@example.invalid",
            "commit", "-qm", "baseline",
            env={**os.environ, **env, "GIT_TRACE2_EVENT": str(trace)},
        )
        children: list[list[str]] = []
        for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") == "child_start":
                children.append(list(event.get("argv") or ()))
        trace.unlink(missing_ok=True)
        return len(children), children


GUARD_ENV = {
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "maintenance.auto", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "gc.auto", "GIT_CONFIG_VALUE_1": "0",
}
# Strip any ambient guard so the control measures unguarded git.
UNGUARDED_ENV = {
    key: "" for key in (
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0",
        "GIT_CONFIG_KEY_1", "GIT_CONFIG_VALUE_1",
    )
}


class GitFixtureMaintenanceTests(unittest.TestCase):
    def test_unguarded_commit_spawns_detached_maintenance(self) -> None:
        """Negative control: without the guard git really does spawn the child.

        If this fails, the probe is broken (or git changed) -- fix the probe
        before trusting the guarded case below.
        """
        env = {k: v for k, v in UNGUARDED_ENV.items()}
        env["GIT_CONFIG_COUNT"] = "0"
        count, argvs = _commit_and_count_children(env)
        self.assertGreaterEqual(
            count, 1,
            "git commit spawned no child at all -- the trace2 probe is not "
            "measuring anything, so the guarded assertion below proves nothing",
        )
        self.assertTrue(
            any("maintenance" in " ".join(argv) for argv in argvs),
            f"expected a detached `git maintenance` child, saw: {argvs}",
        )
        self.assertTrue(
            any("--detach" in argv for argv in argvs),
            f"the maintenance child must be the daemonizing one, saw: {argvs}",
        )

    def test_guarded_commit_spawns_nothing(self) -> None:
        """maintenance.auto=false removes the writer at its source."""
        count, argvs = _commit_and_count_children(GUARD_ENV)
        self.assertEqual(
            count, 0,
            f"guarded git commit still spawned {count} child process(es): {argvs}",
        )

    def test_maintenance_auto_is_the_load_bearing_key(self) -> None:
        """`maintenance.auto=false` alone suppresses the spawn.

        The guard sets `gc.auto=0` as well, and which key suffices depends on
        the git version -- measured, after an earlier version of this test
        asserted one host's answer as universal and CI correctly rejected it:

            git 2.50.1 (macOS)  gc.auto=0 alone -> 1 child, still spawns
            git 2.55.0 (Linux)  gc.auto=0 alone -> 0 children, suppressed

        So `gc.auto` alone cannot be asserted portably and is not asserted here.
        `maintenance.auto` names the spawner directly on both, which is why the
        guard leads with it and why dropping it would restore the race on any
        host whose git behaves like 2.50. Both keys stay exported; that both are
        present is pinned by test_runner_environment_applies_the_guard.
        """
        count, argvs = _commit_and_count_children({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "maintenance.auto", "GIT_CONFIG_VALUE_0": "false",
        })
        self.assertEqual(
            count, 0,
            f"maintenance.auto=false did not suppress the spawn: {argvs}",
        )

    def test_runner_environment_applies_the_guard(self) -> None:
        """The suite's own process must carry the guard bin/test exports."""
        missing = [key for key in GUARD_KEYS if not os.environ.get(key)]
        if missing:
            self.skipTest(
                "guard not present in this process ("
                + ", ".join(missing)
                + "); it is exported by bin/test, so a direct `python -m "
                "unittest` run is exposed to the ENOTEMPTY race this file "
                "documents. Run via `bash bin/test` to exercise this assertion."
            )
        self.assertEqual(os.environ.get("GIT_CONFIG_COUNT"), "2")
        pairs = {
            os.environ.get(f"GIT_CONFIG_KEY_{i}"): os.environ.get(f"GIT_CONFIG_VALUE_{i}")
            for i in range(int(os.environ["GIT_CONFIG_COUNT"]))
        }
        self.assertEqual(pairs.get("maintenance.auto"), "false")
        self.assertEqual(pairs.get("gc.auto"), "0")


if __name__ == "__main__":
    unittest.main()
