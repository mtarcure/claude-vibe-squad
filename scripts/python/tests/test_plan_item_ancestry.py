#!/usr/bin/env python3
"""Landed-commit ancestry must mean work landed, not that a message said so.

`landed_commits` ran `git log --fixed-strings --grep=<task_id> <ref> --` with no
path filter and no trailer check, so ANY reachable commit whose message merely
named the task satisfied the landed-ancestry leg of the completion gate. That is
a check that cannot fail, sitting inside the mechanism that decides an item is
done. The fix requires the commit to have changed at least one path inside the
task's dispatcher-declared `write_scope`, measured against its FIRST parent.

Four groups, in the order the risk runs:

1. `ScopeNormalisationTests` -- a declared scope cannot be widened by its own
   spelling. Absolute paths and `..` escapes are refused before anything is
   trimmed.
2. `LandingWitnessTests` -- both directions on a linear history: bookkeeping,
   docs-only, and empty commits do NOT witness; a commit that changed the task's
   territory does.
3. `BoardCommitShapeTests` -- the three shapes the board actually produces
   (fast-forward, residue commit, integrate merge), including the pin that a
   merge is credited only for what it brought ONTO the mainline.
4. `DecideAncestryLegTests` -- the leg as `decide` sees it, including the
   fail-closed answer when no scope is declared at all.

The negative cases are the point. A completion path that is easier to satisfy
than a failure path is the defect this file exists to prevent.
"""

import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plan_item_binding as pib  # noqa: E402


TASK = "TASK-2026-08-13-1170-status-segment-liveness"
OTHER_TASK = "TASK-2026-08-13-9999-never-landed"


class _Repo:
    """A throwaway Git repo that can build every commit shape under test."""

    def __init__(self, root: Path):
        self.root = root
        self._env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        }
        self.git("init", "-q", "-b", "main")

    def git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            env=self._env,
        )
        return completed.stdout.strip()

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str, files: dict | None = None) -> str:
        """Commit `files`, or an EMPTY commit when none are given."""

        for relative, text in (files or {}).items():
            self.write(relative, text)
        self.git("add", "-A")
        arguments = ["commit", "-q", "-m", message]
        if not files:
            arguments.insert(1, "--allow-empty")
        self.git(*arguments)
        return self.git("rev-parse", "HEAD")

    def integrate_merge(self, task_id: str, mainline: str, worker_head: str) -> str:
        """The board's own integrate commit, built the way the board builds it.

        Mirrors `worktree_isolation.integrate_worktree_commits`: a merged tree
        from `merge-tree --write-tree`, committed with the MAINLINE as first
        parent and the worker head as second. The parent order is the whole
        point -- it is what makes "what did this commit land" answerable.
        """

        tree = self.git("merge-tree", "--write-tree", mainline, worker_head)
        commit = self.git(
            "commit-tree",
            tree.splitlines()[0].strip(),
            "-p",
            mainline,
            "-p",
            worker_head,
            "-m",
            f"board integrate {task_id}\n\nWorker-Head: {worker_head}\n",
        )
        self.git("update-ref", "refs/heads/main", commit)
        return commit


class ScopeNormalisationTests(unittest.TestCase):
    """A declared scope cannot be widened by how it is spelled."""

    def test_directory_and_dot_forms_normalise_to_one_root(self):
        for value in ("bin", "bin/", "bin//", "./bin", "  bin/  "):
            with self.subTest(value=value):
                self.assertEqual(
                    pib.declared_scope_paths([value]), (PurePosixPath("bin"),)
                )

    def test_absolute_scope_is_refused_not_relativised(self):
        """The regression this test exists for.

        A first draft normalised with `value.strip("/")` to drop the trailing
        slash a directory scope carries. `strip` is symmetric, so it also ate
        the LEADING slash and silently promoted the absolute `/bin` into the
        repo-relative `bin` -- a scope that then matched real in-repo commits.
        """
        for value in ("/bin", "/", "//etc", "/scripts/python"):
            with self.subTest(value=value):
                self.assertEqual(pib.declared_scope_paths([value]), ())

    def test_parent_escape_is_refused(self):
        for value in ("../etc", "../../etc/passwd", "scripts/../../out", ".."):
            with self.subTest(value=value):
                self.assertEqual(pib.declared_scope_paths([value]), ())

    def test_unusable_scope_declarations_normalise_to_nothing(self):
        # A scope we cannot read must narrow what counts as landed, never widen
        # it, so every one of these yields the unsatisfiable empty scope.
        for value in (
            None,
            [],
            "",
            "bin",
            4,
            [4],
            [None],
            [""],
            ["   "],
            ["."],
            ["./"],
            ["././"],
            {"a": 1},
        ):
            with self.subTest(value=value):
                self.assertEqual(pib.declared_scope_paths(value), ())

    def test_duplicate_scope_entries_collapse_and_order_is_kept(self):
        self.assertEqual(
            pib.declared_scope_paths(["src/", "docs", "src", "docs/"]),
            (PurePosixPath("src"), PurePosixPath("docs")),
        )

    def test_containment_matches_the_root_itself_and_paths_under_it(self):
        scopes = pib.declared_scope_paths(["src", "docs/standards/one.md"])
        for path in ("src", "src/a.py", "src/deep/nested/b.py"):
            with self.subTest(inside=path):
                self.assertTrue(pib._within_scope(path, scopes))
        for path in ("srcx/a.py", "src2", "other/src/a.py", "docs/standards"):
            with self.subTest(outside=path):
                self.assertFalse(pib._within_scope(path, scopes))
        # A file-form scope matches itself and nothing else.
        self.assertTrue(pib._within_scope("docs/standards/one.md", scopes))
        self.assertFalse(pib._within_scope("docs/standards/two.md", scopes))
        self.assertFalse(pib._within_scope("src ", scopes))


class _RepoCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.repo = _Repo(self.root)
        self.base = self.repo.commit("base", {"src/main.py": "x = 1\n"})

    def tearDown(self):
        self.temporary.cleanup()

    def landed(self, scope, task_id=TASK):
        return pib.landed_commits(
            task_id, repo_root=self.root, git_ref="HEAD", write_scope=scope
        )


class LandingWitnessTests(_RepoCase):
    """Both directions: naming the task is not the same as doing it."""

    def test_a_commit_that_changed_the_scope_witnesses(self):
        landing = self.repo.commit(f"board integrate {TASK}", {"src/main.py": "x = 2\n"})
        self.assertEqual(self.landed(["src"]), [landing])

    def test_an_empty_commit_naming_the_task_does_not_witness(self):
        empty = self.repo.commit(f"board integrate {TASK}")
        self.assertEqual(
            pib.commit_changed_paths(empty, repo_root=self.root), ()
        )
        self.assertEqual(self.landed(["src"]), [])

    def test_a_bookkeeping_commit_naming_the_task_does_not_witness(self):
        # The class, not just the instance. This commit is NOT empty -- it
        # changes a real file -- and it still must not witness, because the file
        # is outside the territory the task was authorised to change.
        self.repo.commit(f"docs: note {TASK} in the ledger", {"docs/log.md": "note\n"})
        self.assertEqual(self.landed(["src"]), [])

    def test_a_bookkeeping_commit_does_not_ride_along_with_a_real_one(self):
        landing = self.repo.commit(f"board integrate {TASK}", {"src/main.py": "x = 2\n"})
        self.repo.commit(f"docs: note {TASK}", {"docs/log.md": "note\n"})
        self.repo.commit(f"chore: mention {TASK}")
        self.assertEqual(self.landed(["src"]), [landing])

    def test_a_commit_that_does_not_name_the_task_never_witnesses(self):
        self.repo.commit("unrelated work", {"src/main.py": "x = 2\n"})
        self.assertEqual(self.landed(["src"]), [])

    def test_a_landing_for_another_task_does_not_witness_this_one(self):
        self.repo.commit(f"board integrate {OTHER_TASK}", {"src/main.py": "x = 2\n"})
        self.assertEqual(self.landed(["src"]), [])

    def test_a_task_id_prefix_collision_does_not_witness(self):
        self.repo.commit(
            f"board integrate {TASK}-extra", {"src/main.py": "x = 2\n"}
        )
        self.assertEqual(self.landed(["src"]), [])

    def test_an_unreachable_commit_does_not_witness(self):
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.commit(f"board integrate {TASK}", {"src/main.py": "x = 9\n"})
        self.repo.git("checkout", "-q", "main")
        self.assertEqual(self.landed(["src"]), [])

    def test_a_deletion_inside_scope_still_witnesses(self):
        # A task authorised to remove a path landed work when it removed it.
        self.repo.commit("add", {"src/gone.py": "y = 1\n"})
        (self.root / "src" / "gone.py").unlink()
        self.repo.git("add", "-A")
        self.repo.git("commit", "-q", "-m", f"board integrate {TASK}")
        head = self.repo.git("rev-parse", "HEAD")
        self.assertEqual(self.landed(["src"]), [head])

    def test_a_root_commit_reports_its_whole_tree(self):
        # Its own directory, never nested inside `self.root`: a repo inside a
        # repo would be swept into the outer `git add -A`.
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        fresh = Path(holder.name).resolve()
        repo = _Repo(fresh)
        root_commit = repo.commit(f"board integrate {TASK}", {"src/main.py": "x = 1\n"})
        self.assertIn(
            "src/main.py", pib.commit_changed_paths(root_commit, repo_root=fresh)
        )
        self.assertEqual(
            pib.landed_commits(
                TASK, repo_root=fresh, git_ref="HEAD", write_scope=["src"]
            ),
            [root_commit],
        )

    def test_no_declared_scope_witnesses_nothing(self):
        self.repo.commit(f"board integrate {TASK}", {"src/main.py": "x = 2\n"})
        for scope in (None, [], ["/src"], ["../src"]):
            with self.subTest(scope=scope):
                self.assertEqual(self.landed(scope), [])

    def test_git_failure_is_indeterminate_not_an_empty_result(self):
        with self.assertRaisesRegex(
            pib.PlanItemBindingError, "could not determine commit ancestry"
        ):
            pib.landed_commits(
                TASK,
                repo_root=self.root,
                git_ref="refs/heads/does-not-exist",
                write_scope=["src"],
            )


class BoardCommitShapeTests(_RepoCase):
    """The three shapes `integrate_worktree_commits` actually produces."""

    def test_fast_forward_shape_has_no_integrate_commit_and_still_witnesses(self):
        """When the target did not advance, `integration_commit = worker_head`.

        There is no `board integrate` commit at all in this shape, so a rule
        that demanded one would fail every fast-forwarded task.
        """
        residue = self.repo.commit(
            f"board: worker residue for {TASK} (d-{'a' * 32})",
            {"src/main.py": "x = 2\n"},
        )
        self.assertEqual(self.landed(["src"]), [residue])

    def test_merge_shape_witnesses_both_the_residue_and_the_integrate_commit(self):
        """The live shape from 2026-08-13, rebuilt.

        Both commits genuinely landed the work and either is a correct witness:
        the residue commit is where the content was authored, the merge is where
        it reached the mainline. Demanding one specific shape would be brittle,
        because which one exists depends on whether the target happened to
        advance concurrently.
        """
        self.repo.git("checkout", "-q", "-b", "worker")
        residue = self.repo.commit(
            f"board: worker residue for {TASK} (d-{'a' * 32})",
            {"src/main.py": "x = 2\n"},
        )
        self.repo.git("checkout", "-q", "main")
        mainline = self.repo.commit("unrelated advance", {"other/tool.sh": "echo\n"})
        merge = self.repo.integrate_merge(TASK, mainline, residue)

        self.assertEqual(self.repo.git("rev-parse", "HEAD^{commit}"), merge)
        self.assertEqual(sorted(self.landed(["src"])), sorted([merge, residue]))

    def test_merge_is_credited_only_for_what_it_brought_onto_the_mainline(self):
        """The union pin, and the sharpest test in this file.

        `git diff-tree -m --first-parent` does NOT restrict the diff to the
        first parent: it emits one diff per parent, and `--no-commit-id` strips
        the headers that separated them, so a merge comes back as the UNION
        across its parents. Here the worker side is OUT of scope and the
        mainline side is IN scope. Under the union the merge would be credited
        for `src/main.py`, which the mainline contributed and the worker never
        touched -- completion forged out of somebody else's commit. Against the
        first parent, the merge landed only `notes/w.txt`, and witnesses nothing.
        """
        self.repo.git("checkout", "-q", "-b", "worker")
        residue = self.repo.commit(
            f"board: worker residue for {TASK} (d-{'a' * 32})",
            {"notes/w.txt": "worker\n"},
        )
        self.repo.git("checkout", "-q", "main")
        # The mainline advance touches the scope, and does NOT name the task.
        mainline = self.repo.commit("unrelated advance", {"src/main.py": "x = 3\n"})
        merge = self.repo.integrate_merge(TASK, mainline, residue)

        self.assertEqual(
            pib.commit_changed_paths(merge, repo_root=self.root), ("notes/w.txt",)
        )
        self.assertEqual(self.landed(["src"]), [])
        # ...and it does witness the territory it actually landed.
        self.assertEqual(sorted(self.landed(["notes"])), sorted([merge, residue]))

    def test_an_empty_integrate_merge_over_a_real_advance_does_not_witness(self):
        """A merge that brought nothing, over a mainline that changed the scope.

        This is the reported finding in its most dangerous form: the merge looks
        like a landing, sits at the head of the branch, names the task, and has
        a real in-scope diff on one side -- and it landed nothing.
        """
        self.repo.git("checkout", "-q", "-b", "worker")
        residue = self.repo.commit(f"board: worker residue for {TASK}")
        self.repo.git("checkout", "-q", "main")
        mainline = self.repo.commit("unrelated advance", {"src/main.py": "x = 3\n"})
        merge = self.repo.integrate_merge(TASK, mainline, residue)

        self.assertEqual(pib.commit_changed_paths(merge, repo_root=self.root), ())
        self.assertEqual(self.landed(["src"]), [])


class DecideAncestryLegTests(_RepoCase):
    """The leg as `decide` sees it: done, held, and the unmeasurable case."""

    def setUp(self):
        super().setUp()
        self.attempt = "d-" + "c" * 32
        # OUTSIDE the repo working tree, on purpose. Written inside it, the
        # harness's own `git add -A` commits the receipt onto whichever branch
        # is checked out, and the next `checkout` of a branch that never had it
        # deletes it -- which reads as `receipt_missing` and quietly tests the
        # wrong thing.
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.receipt = Path(holder.name).resolve() / "receipt.json"
        self.receipt.write_text(
            json.dumps(
                {
                    "schema": "board-dispatch-receipt/v2",
                    "task_id": TASK,
                    "attempt_id": self.attempt,
                    "generation": 1,
                    "terminal_outcome": "complete",
                    "plan_item_ids": ["P4.4"],
                }
            ),
            encoding="utf-8",
        )

    def entry(self, **overrides) -> dict:
        entry = {
            "status": "complete",
            "to_model": "claude",
            "author_family": "claude",
            "review_model": "gpt-codex",
            "delivery_attempt_id": self.attempt,
            "delivery_generation": 1,
            "terminal_receipt_path": str(self.receipt),
            "review_settled_by": "chrono-explicit",
            "cross_family_review_ref": f"departments/coding/outbox/{TASK}-review.md",
            "verdict": "APPROVE",
            "write_scope": ["src"],
        }
        entry.update(overrides)
        return entry

    def decide(self, entry) -> pib.Decision:
        return pib.decide(
            "P4.4", TASK, entry, repo_root=self.root, git_ref="HEAD"
        )

    def test_full_evidence_with_a_real_landing_marks_done(self):
        landing = self.repo.commit(f"board integrate {TASK}", {"src/main.py": "x = 2\n"})
        decision = self.decide(self.entry())
        self.assertTrue(decision.done, decision.missing)
        self.assertEqual(decision.missing, [])
        self.assertEqual(decision.evidence["commit"], landing)

    def test_a_bookkeeping_only_commit_leaves_the_item_open(self):
        # The load-bearing assertion of this whole file. Every other leg of the
        # gate is satisfied; only the landing is fake, and the item stays open.
        self.repo.commit(f"docs: note {TASK}", {"docs/log.md": "note\n"})
        decision = self.decide(self.entry())
        self.assertFalse(decision.done)
        self.assertIn("commit_ancestry_missing", decision.missing)
        self.assertNotIn("commit", decision.evidence)

    def test_an_empty_commit_leaves_the_item_open(self):
        self.repo.commit(f"board integrate {TASK}")
        decision = self.decide(self.entry())
        self.assertFalse(decision.done)
        self.assertIn("commit_ancestry_missing", decision.missing)

    def test_an_undeclared_write_scope_is_unmeasurable_not_satisfied(self):
        """Fail closed, and say which thing was missing.

        `integrate_worktree_commits` refuses an empty integration scope outright,
        so a task with no declared write scope structurally cannot have landed
        anything. The distinct reason keeps that legible: nothing was measurable,
        as against measured and absent.
        """
        self.repo.commit(f"board integrate {TASK}", {"src/main.py": "x = 2\n"})
        for scope in (None, [], ["/src"]):
            with self.subTest(scope=scope):
                entry = self.entry()
                if scope is None:
                    entry.pop("write_scope")
                else:
                    entry["write_scope"] = scope
                decision = self.decide(entry)
                self.assertFalse(decision.done)
                self.assertIn("commit_ancestry_unscoped", decision.missing)
                self.assertNotIn("commit_ancestry_missing", decision.missing)

    def test_a_landing_outside_the_declared_scope_leaves_the_item_open(self):
        # The task landed real code -- just not in the territory it declared.
        self.repo.commit(f"board integrate {TASK}", {"elsewhere/x.py": "x = 2\n"})
        decision = self.decide(self.entry())
        self.assertFalse(decision.done)
        self.assertIn("commit_ancestry_missing", decision.missing)

    def test_git_failure_is_reported_as_unknown(self):
        decision = pib.decide(
            "P4.4",
            TASK,
            self.entry(),
            repo_root=self.root,
            git_ref="refs/heads/does-not-exist",
        )
        self.assertFalse(decision.done)
        self.assertIn("commit_ancestry_unknown", decision.missing)
        self.assertNotIn("commit_ancestry_missing", decision.missing)

    def test_the_board_merge_shape_marks_done_end_to_end(self):
        self.repo.git("checkout", "-q", "-b", "worker")
        residue = self.repo.commit(
            f"board: worker residue for {TASK} ({self.attempt})",
            {"src/main.py": "x = 2\n"},
        )
        self.repo.git("checkout", "-q", "main")
        mainline = self.repo.commit("unrelated advance", {"other/tool.sh": "echo\n"})
        merge = self.repo.integrate_merge(TASK, mainline, residue)

        decision = self.decide(self.entry())
        self.assertTrue(decision.done, decision.missing)
        self.assertEqual(decision.evidence["commit"], merge)


if __name__ == "__main__":
    unittest.main()
