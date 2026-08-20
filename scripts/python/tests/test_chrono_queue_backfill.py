"""Backfill keeps only queue lines whose task is still open."""
import hashlib
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OPEN_STATES = ("review-required", "needs_review", "needs_human")
SCRIPT = REPO / "bin" / "chrono-queue-backfill.sh"


class ChronoQueueBackfill(unittest.TestCase):
    def _run(self, queue_lines: list[str], registry: dict) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "_state"
            state.mkdir()
            (state / "active-tasks.json").write_text(json.dumps(registry), encoding="utf-8")
            q = state / "chrono-queue.md"
            q.write_text("# Chrono Queue\n" + "\n".join(queue_lines) + "\n", encoding="utf-8")
            subprocess.run(
                ["bash", str(SCRIPT)],
                env={"PATH": "/usr/bin:/bin", "VAULT_ROOT": str(d)},
                check=True, capture_output=True, text=True,
            )
            handled = state / "chrono-queue-handled.md"
            return q.read_text(encoding="utf-8"), (handled.read_text(encoding="utf-8") if handled.exists() else "")

    def _invoke(self, vault_root: str) -> None:
        subprocess.run(
            ["bash", str(SCRIPT)],
            env={"PATH": "/usr/bin:/bin", "VAULT_ROOT": vault_root},
            check=True, capture_output=True, text=True,
        )

    def test_open_task_line_is_kept(self) -> None:
        line = "2026-08-16T00:00:00Z | complete | coding/T-OPEN | done"
        kept, archived = self._run([line], {"T-OPEN": {"status": "review-required"}})
        self.assertIn("T-OPEN", kept)
        self.assertNotIn("T-OPEN", archived)

    def test_closed_task_line_is_archived(self) -> None:
        line = "2026-08-16T00:00:00Z | complete | coding/T-DONE | done"
        kept, archived = self._run([line], {"T-DONE": {"status": "closed"}})
        self.assertNotIn("T-DONE", kept)
        self.assertIn("T-DONE", archived)

    def test_task_absent_from_registry_is_archived(self) -> None:
        line = "2026-08-16T00:00:00Z | complete | coding/T-GHOST | done"
        kept, archived = self._run([line], {})
        self.assertNotIn("T-GHOST", kept)
        self.assertIn("T-GHOST", archived)

    def test_unparseable_line_is_kept(self) -> None:
        line = "this line has no pipe delimiters at all"
        kept, archived = self._run([line], {})
        self.assertIn(line, kept)
        self.assertNotIn(line, archived)

    def test_rerun_is_idempotent(self) -> None:
        """Invokes the script TWICE against the same persistent state and
        asserts handled.md is byte-identical after the second run: the first
        run archives T-DONE (queue.md no longer contains it afterward), so
        the second run's recomputed archived set is empty and handled.md
        must not be touched at all."""
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "_state"
            state.mkdir()
            line = "2026-08-16T00:00:00Z | complete | coding/T-DONE | done"
            (state / "active-tasks.json").write_text(
                json.dumps({"T-DONE": {"status": "closed"}}), encoding="utf-8"
            )
            (state / "chrono-queue.md").write_text("# Chrono Queue\n" + line + "\n", encoding="utf-8")
            handled = state / "chrono-queue-handled.md"

            self._invoke(str(d))
            first_handled = handled.read_text(encoding="utf-8")
            self.assertIn("T-DONE", first_handled)

            self._invoke(str(d))
            second_handled = handled.read_text(encoding="utf-8")
            self.assertEqual(first_handled, second_handled)

    def test_crash_between_writes_does_not_duplicate_on_retry(self) -> None:
        """Simulates a crash after handled.md commits but before queue.md
        commits: handled.md already has the archived batch + its marker, but
        queue.md is untouched (still contains the archived line). On retry,
        the script must recognize the batch already landed -- not append it
        again -- and finish the interrupted queue.md write."""
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "_state"
            state.mkdir()
            line = "2026-08-16T00:00:00Z | complete | coding/T-DONE | done"
            (state / "active-tasks.json").write_text(
                json.dumps({"T-DONE": {"status": "closed"}}), encoding="utf-8"
            )
            q = state / "chrono-queue.md"
            q.write_text("# Chrono Queue\n" + line + "\n", encoding="utf-8")

            batch_hash = hashlib.sha256(line.encode("utf-8")).hexdigest()
            marker = f"<!-- chrono-queue-backfill:batch={batch_hash} -->"
            handled = state / "chrono-queue-handled.md"
            handled.write_text(line + "\n" + marker + "\n", encoding="utf-8")

            self._invoke(str(d))

            handled_text = handled.read_text(encoding="utf-8")
            self.assertEqual(handled_text.count("T-DONE"), 1)
            self.assertNotIn("T-DONE", q.read_text(encoding="utf-8"))

    def test_waits_for_live_lock_owner_then_proceeds(self) -> None:
        """The backfill must take chrono-queue.md.lockdir like every other
        queue writer -- a concurrent settlement append cannot be allowed to
        land between this script's read and its whole-file rewrite and be
        silently discarded. Simulate a concurrent writer by pre-creating the
        lockdir with a genuinely live owner PID (a `cat` process blocked on
        its own stdin). The backfill subprocess must still be running after
        a short pause (proving it waited rather than barrelling through),
        then complete correctly once the owner exits and the lock is freed."""
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "_state"
            state.mkdir()
            line = "2026-08-16T00:00:00Z | complete | coding/T-OPEN | done"
            (state / "active-tasks.json").write_text(
                json.dumps({"T-OPEN": {"status": "review-required"}}), encoding="utf-8"
            )
            (state / "chrono-queue.md").write_text("# Chrono Queue\n" + line + "\n", encoding="utf-8")

            owner = subprocess.Popen(
                ["cat"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            )
            try:
                lockdir = state / "chrono-queue.md.lockdir"
                lockdir.mkdir()
                (lockdir / "owner.pid").write_text(f"{owner.pid}\n", encoding="utf-8")

                proc = subprocess.Popen(
                    ["bash", str(SCRIPT)],
                    env={"PATH": "/usr/bin:/bin", "VAULT_ROOT": str(d)},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                try:
                    time.sleep(0.3)
                    self.assertIsNone(
                        proc.poll(),
                        "backfill did not wait for the live lock owner -- it "
                        "ran while the lockdir was still held",
                    )
                finally:
                    owner.stdin.close()
                    owner.wait(timeout=5)

                stdout, stderr = proc.communicate(timeout=10)
                self.assertEqual(proc.returncode, 0, stderr)
                self.assertIn("kept=1 archived=0", stdout)
                self.assertFalse(lockdir.exists(), "lockdir was not released")
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait()

    def test_breaks_stale_lock_from_dead_owner(self) -> None:
        """A lockdir left behind by a dead owner (crash, kill -9) must not
        wedge the backfill forever -- same rule as the other chrono-queue.md
        writers: break the lock if the owner PID is dead, regardless of the
        lock's age."""
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "_state"
            state.mkdir()
            line = "2026-08-16T00:00:00Z | complete | coding/T-DONE | done"
            (state / "active-tasks.json").write_text(
                json.dumps({"T-DONE": {"status": "closed"}}), encoding="utf-8"
            )
            (state / "chrono-queue.md").write_text("# Chrono Queue\n" + line + "\n", encoding="utf-8")

            dead = subprocess.Popen(["true"])
            dead.wait()  # reaped: dead.pid is now guaranteed not alive
            lockdir = state / "chrono-queue.md.lockdir"
            lockdir.mkdir()
            (lockdir / "owner.pid").write_text(f"{dead.pid}\n", encoding="utf-8")

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                env={"PATH": "/usr/bin:/bin", "VAULT_ROOT": str(d)},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("kept=0 archived=1", result.stdout)
            self.assertFalse(lockdir.exists(), "stale lockdir was not broken")

    def test_self_locates_vault_root_without_env_var(self) -> None:
        """Reproduces the exact command in Task 5's brief -- `bash
        bin/chrono-queue-backfill.sh` with no VAULT_ROOT set -- against a
        temp copy laid out like the repo (bin/, shared/repo-root.sh,
        _state/). The script must self-locate VAULT_ROOT via
        shared/repo-root.sh, the same way 41/41 other bin/ scripts do,
        rather than dying on the `${VAULT_ROOT:?}` guard."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "bin").mkdir()
            (root / "shared").mkdir()
            (root / "_state").mkdir()
            script_copy = root / "bin" / "chrono-queue-backfill.sh"
            script_copy.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
            script_copy.chmod(0o755)
            (root / "shared" / "repo-root.sh").write_text(
                (REPO / "shared" / "repo-root.sh").read_text(encoding="utf-8"), encoding="utf-8"
            )
            line = "2026-08-16T00:00:00Z | complete | coding/T-OPEN | done"
            (root / "_state" / "active-tasks.json").write_text(
                json.dumps({"T-OPEN": {"status": "review-required"}}), encoding="utf-8"
            )
            (root / "_state" / "chrono-queue.md").write_text("# Chrono Queue\n" + line + "\n", encoding="utf-8")

            result = subprocess.run(
                ["bash", "bin/chrono-queue-backfill.sh"],
                cwd=str(root),
                env={"PATH": "/usr/bin:/bin"},
                check=True, capture_output=True, text=True,
            )
            self.assertIn("kept=1 archived=0", result.stdout)
            self.assertIn("T-OPEN", (root / "_state" / "chrono-queue.md").read_text(encoding="utf-8"))
