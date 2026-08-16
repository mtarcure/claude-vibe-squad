#!/usr/bin/env python3
"""P3.7b: the admitted swarm child-vector publication window in `bin/send-task.sh`.

This seam publishes every admitted child packet into
``departments/<namespace>/inbox/`` and only then calls
``registry-reconciler.sh --register-swarm``. Until this file existed the only
concurrency evidence for P3.7b was a 50-repetition race against
``dispatch_context_builder._atomic_publish`` -- the *output bridge* primitive,
which this seam does not call. A green test on the wrong seam is worse than no
test, because it retires the question. These tests drive the real
``bin/send-task.sh`` at the real seam.

Note on what is and is not asserted here. The output-bridge race asserts that a
losing writer's staged bytes survive, because there the loser is a worker's only
copy of its result. That invariant does not transfer to this seam: a losing
child-vector writer is republishing a *freshly generated, unadmitted duplicate*
whose source of truth is still its own ``_state/board-dispatch/<task>.swarm.*``
build directory, and retaining rejected packet bytes inside a watched inbox
would be a leak rather than a durability guarantee. What must hold here is
no-replace, no-tear, no-partial-registration, no staging residue, and
publish-before-register.

Every packet carries an absolute ``return_artifact`` and the vault omits
``bin/board-supervisor.sh``, so each dispatch dies deterministically after
registration and no model CLI is ever launched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
SCRIPTS = REPO / "scripts" / "python"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scripts.python.tests.test_sendtask_hardening_r2 import (  # noqa: E402
    SendTaskFixture,
)
import registry_reconciler as rr  # noqa: E402

SEND_TASK = REPO / "bin" / "send-task.sh"
LANES = ("gpt-codex", "claude")
# Two concurrent dispatches per repetition. Raise for a stress run:
#   SWARM_VECTOR_RACE_REPETITIONS=25 python3 -m unittest \
#     scripts.python.tests.test_swarm_child_vector_publish
REPETITIONS = int(os.environ.get("SWARM_VECTOR_RACE_REPETITIONS", "3"))

CONFLICT_REFUSAL = "refusing to replace conflicting swarm child packet"


class SwarmChildVectorPublishTests(SendTaskFixture):
    """Concurrency and no-replace behaviour of the real publication window."""

    def make_swarm_vault(self) -> Path:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        specialists = vault / "departments/coding/specialists"
        specialists.mkdir()
        shutil.copy2(
            REPO / "departments/coding/specialists/code-reviewer.md",
            specialists / "code-reviewer.md",
        )
        return vault

    @staticmethod
    def swarm_fields(run_id: str) -> dict[str, str]:
        return {
            "specialist": "code-reviewer",
            "to_model": "gpt-codex",
            "mode": "bounty",
            "run_id": run_id,
            "result_type": "dry_run",
            "mandatory_review": "true",
            "review_model": "claude",
            "review_class": "security-finding",
            "direct_lane_work_allowed": "false",
        }

    def child_packet(self, vault: Path, child_id: str) -> Path | None:
        for mailbox in ("inbox", "archive"):
            candidate = vault / "departments/coding" / mailbox / f"{child_id}.md"
            if candidate.is_file():
                return candidate
        return None

    def assert_packet_is_whole(self, path: Path, child_id: str) -> bytes:
        """A published child packet is never a partially written file."""

        data = path.read_bytes()
        text = data.decode("utf-8")
        self.assertTrue(text.startswith("---\n"), msg=f"{child_id}: no frontmatter")
        self.assertIn(f"id: {child_id}\n", text, msg=f"{child_id}: wrong or torn id")
        self.assertIn(
            "## Swarm-v1 member contract",
            text,
            msg=f"{child_id}: truncated before the member contract",
        )
        self.assertIn(
            "verification_contract_sha256:",
            text,
            msg=f"{child_id}: truncated frontmatter",
        )
        return data

    def assert_no_staging_residue(self, vault: Path, task_id: str) -> None:
        """The seam stages inside the watched inbox, so residue is observable.

        A leaked ``.<child>.tmp.XXXXXX`` is not merely untidy: the inbox
        ``.gitignore`` rule matches ``*.md`` only, so a staging orphan is a
        tracked-by-default file inside a mailbox namespace.
        """

        inbox = vault / "departments/coding/inbox"
        residue = sorted(
            path.name for path in inbox.glob(f".{task_id}-swarm-*.tmp.*")
        )
        self.assertEqual(residue, [], msg="staging temp left inside the watched inbox")

    def assert_registration_is_all_or_nothing(self, vault: Path, task_id: str) -> None:
        registry_path = vault / "_state/active-tasks.json"
        if not registry_path.is_file():
            return
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        expected = {task_id, *(f"{task_id}-swarm-{lane}" for lane in LANES)}
        self.assertEqual(
            set(registry) & expected,
            expected,
            msg="registry holds a partial swarm vector",
        )
        # Publish-before-register: nothing may be registered whose packet is
        # not already on disk.
        for lane in LANES:
            child_id = f"{task_id}-swarm-{lane}"
            self.assertIsNotNone(
                self.child_packet(vault, child_id),
                msg=f"{child_id} registered without a published packet",
            )

    def dispatch_review_class_probe(
        self, *, task_id: str, run_id: str
    ) -> tuple[Path, subprocess.CompletedProcess]:
        """Drive the real sender through registration but never launch a CLI."""

        vault = self.make_swarm_vault()
        completed = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact="_state/review-class-probe/out.md",
            extra_fields=self.swarm_fields(run_id),
            extra_env={
                "SQUAD_TEST_ISOLATION": "1",
                "UV_CACHE_DIR": str(vault.parent / "uv-cache"),
            },
            dispatch_args=("--swarm", ",".join(LANES)),
        )
        return vault, completed

    def raw_member_entries(self, vault: Path, task_id: str) -> dict[str, dict]:
        candidates = list(
            (vault / "_state" / "board-dispatch").glob(
                f"{task_id}.swarm.*/member-entries.json"
            )
        )
        self.assertEqual(
            len(candidates),
            1,
            msg=f"expected one retained pre-registration member vector: {candidates}",
        )
        return json.loads(candidates[0].read_text(encoding="utf-8"))

    def test_security_finding_class_propagates_through_real_swarm_registration(
        self,
    ) -> None:
        """Request, packet, controller, member, and settlement all keep the class."""

        task_id = "TASK-2026-08-11-0531-review-class-e2e"
        vault, completed = self.dispatch_review_class_probe(
            task_id=task_id,
            run_id="BTY-P37D-REVIEW-CLASS-E2E-2026-08-11",
        )
        output = completed.stdout + completed.stderr

        # The missing supervisor is a deterministic post-registration sentinel:
        # this fixture cannot launch a model CLI, but it exercises the real sender,
        # child packet publication, and --register-swarm boundary first.
        self.assertNotEqual(completed.returncode, 0, msg=output[-4000:])
        self.assertIn("missing board supervisor", output)
        self.assertNotIn("atomic swarm registry registration failed", output)

        registry = json.loads(
            (vault / "_state" / "active-tasks.json").read_text(encoding="utf-8")
        )
        children = [f"{task_id}-swarm-{lane}" for lane in LANES]
        self.assertEqual(registry[task_id]["review_class"], "security-finding")
        self.assertEqual(
            {registry[child_id]["review_class"] for child_id in children},
            {"security-finding"},
        )
        self.assertEqual(
            {rr._review_class(registry[child_id]) for child_id in children},
            {"security-finding"},
        )
        for child_id in children:
            packet = self.child_packet(vault, child_id)
            self.assertIsNotNone(packet, msg=f"missing published packet for {child_id}")
            self.assertIn(
                "review_class: security-finding\n",
                packet.read_text(encoding="utf-8"),
            )

    def test_member_constructor_is_explicit_and_generic_registration_refuses_omission(
        self,
    ) -> None:
        """Generic registration refuses a constructed member after class removal."""

        task_id = "TASK-2026-08-11-0532-review-class-refusal"
        vault, completed = self.dispatch_review_class_probe(
            task_id=task_id,
            run_id="BTY-P37D-REVIEW-CLASS-REFUSAL-2026-08-11",
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, msg=output[-4000:])

        members = self.raw_member_entries(vault, task_id)
        self.assertEqual(
            {entry.get("review_class") for entry in members.values()},
            {"security-finding"},
            msg="the member constructor must carry the validated parent class",
        )

        missing_id, missing_entry = next(iter(members.items()))
        missing_id += "-missing-class"
        missing_entry = dict(missing_entry)
        missing_entry.pop("review_class")
        registry_path = vault / "_state" / "active-tasks.json"
        before = registry_path.read_bytes()
        refused = subprocess.run(
            [
                str(vault / "bin" / "registry-reconciler.sh"),
                "--register-task",
                missing_id,
                "--entry-json",
                json.dumps(missing_entry, separators=(",", ":")),
            ],
            env={
                **os.environ,
                "VAULT_ROOT": str(vault),
                "SQUAD_TEST_ISOLATION": "1",
                "SKIP_NUDGE": "1",
                "UV_CACHE_DIR": str(vault.parent / "uv-cache"),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(refused.returncode, 3, msg=refused.stdout + refused.stderr)
        self.assertIn("missing an explicit review_class", refused.stderr)
        self.assertEqual(
            registry_path.read_bytes(),
            before,
            msg="a refused member must not mutate the registry",
        )

    def test_concurrent_dispatch_never_replaces_or_tears_a_published_child(
        self,
    ) -> None:
        """Two real senders race the same vector; the seam holds every time."""

        observed: list[dict[str, object]] = []
        for repetition in range(REPETITIONS):
            with self.subTest(repetition=repetition):
                vault = self.make_swarm_vault()
                task_id = f"TASK-2026-08-11-050{repetition}-vector-race"
                fields = self.swarm_fields(f"BTY-P37B-RACE-{repetition}-2026-08-11")
                results: dict[int, subprocess.CompletedProcess] = {}
                start = threading.Barrier(2)

                def contender(index: int) -> None:
                    start.wait(timeout=30)
                    results[index] = self.dispatch(
                        vault,
                        task_id=task_id,
                        return_artifact="_state/vector-race/out.md",
                        extra_fields=fields,
                        dispatch_args=("--swarm", ",".join(LANES)),
                    )

                threads = [
                    threading.Thread(target=contender, args=(index,))
                    for index in range(2)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=240)
                    self.assertFalse(thread.is_alive(), msg="dispatch thread hung")
                self.assertEqual(len(results), 2)

                outputs = {
                    index: done.stdout + done.stderr
                    for index, done in results.items()
                }
                # No model CLI may ever be launched from this fixture.
                for index, output in outputs.items():
                    self.assertNotEqual(
                        results[index].returncode, 0, msg=output[-2000:]
                    )

                # Whatever landed is one complete admitted packet, and it is
                # still there: no writer replaced another writer's destination.
                published: dict[str, bytes] = {}
                for lane in LANES:
                    child_id = f"{task_id}-swarm-{lane}"
                    path = self.child_packet(vault, child_id)
                    if path is not None:
                        published[child_id] = self.assert_packet_is_whole(
                            path, child_id
                        )

                self.assert_no_staging_residue(vault, task_id)
                self.assert_registration_is_all_or_nothing(vault, task_id)

                # A sender that lost the window says so explicitly rather than
                # overwriting; it never reports a successful publication of a
                # child it did not create.
                for index, output in outputs.items():
                    if CONFLICT_REFUSAL in output:
                        self.assertNotIn(
                            "atomic swarm registry registration failed", output
                        )

                observed.append(
                    {
                        "repetition": repetition,
                        "published_children": sorted(published),
                        # The seam's own losing-writer signals. `File exists` is
                        # the raw `ln` failure the loser falls through on;
                        # `Reused exact swarm child` is the pre-loop branch.
                        "lost_publish_window": sum(
                            "File exists" in output or "Reused exact swarm child" in output
                            for output in outputs.values()
                        ),
                        "refusals": sum(
                            CONFLICT_REFUSAL in output for output in outputs.values()
                        ),
                        "registry": (vault / "_state/active-tasks.json").is_file(),
                    }
                )

        # A race that never raced is a green test that proves nothing, which is
        # the exact failure mode this file exists to correct. Report the
        # observed interleavings and fail loudly if none of them contended.
        print(f"\nchild-vector race outcomes: {json.dumps(observed, sort_keys=True)}")
        self.assertGreater(
            sum(int(entry["lost_publish_window"]) for entry in observed),
            0,
            msg=(
                "no repetition actually contended for the publication window; "
                "this run proves nothing about the seam -- raise "
                "SWARM_VECTOR_RACE_REPETITIONS and re-measure"
            ),
        )

    def test_concurrent_senders_build_byte_identical_child_packets(self) -> None:
        """Why concurrent reuse is safe, pinned rather than assumed.

        The loser of the publication window keeps the winner's packet only
        because `cmp -s` proves the two are the same admitted bytes. Child
        packet generation is therefore required to be deterministic: the
        per-attempt identifiers and timestamps live in the registry entry, not
        in the packet. If that ever stopped being true, every concurrent
        dispatch would start refusing instead of reusing, and this test says so
        before the board does.
        """

        vault = self.make_swarm_vault()
        task_id = "TASK-2026-08-11-0508-vector-determinism"
        fields = self.swarm_fields("BTY-P37B-DETERMINISM-2026-08-11")
        first = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact="_state/vector-determinism/out.md",
            extra_fields=fields,
            dispatch_args=("--swarm", ",".join(LANES)),
        )
        self.assertNotEqual(first.returncode, 0, msg=(first.stdout + first.stderr)[-2000:])
        published = {}
        for lane in LANES:
            child_id = f"{task_id}-swarm-{lane}"
            path = self.child_packet(vault, child_id)
            self.assertIsNotNone(path, msg=f"{child_id} was never published")
            published[child_id] = path.read_bytes()

        second = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact="_state/vector-determinism/out.md",
            extra_fields=fields,
            dispatch_args=("--swarm", ",".join(LANES)),
        )
        output = second.stdout + second.stderr
        self.assertNotIn(CONFLICT_REFUSAL, output, msg=output[-2000:])
        for child_id, data in published.items():
            path = self.child_packet(vault, child_id)
            self.assertIsNotNone(path, msg=f"{child_id} disappeared on replay")
            self.assertEqual(path.read_bytes(), data, msg=f"{child_id} was rewritten")

    def test_a_conflicting_destination_is_refused_and_left_byte_exact(self) -> None:
        """Deterministic negative control for the no-replace assertion above.

        Without this, a concurrent test that never actually collides would pass
        for the wrong reason. A foreign packet already at a child destination
        must survive byte-exact, and registration must not happen.
        """

        vault = self.make_swarm_vault()
        task_id = "TASK-2026-08-11-0509-vector-noreplace"
        inbox = vault / "departments/coding/inbox"
        squatted = inbox / f"{task_id}-swarm-{LANES[0]}.md"
        foreign = b"---\nid: someone-elses-packet\n---\n\nnot the admitted vector\n"
        squatted.write_bytes(foreign)

        done = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact="_state/vector-noreplace/out.md",
            extra_fields=self.swarm_fields("BTY-P37B-NOREPLACE-2026-08-11"),
            dispatch_args=("--swarm", ",".join(LANES)),
        )
        output = done.stdout + done.stderr
        self.assertNotEqual(done.returncode, 0, msg=output[-2000:])
        self.assertIn(CONFLICT_REFUSAL, output)
        self.assertEqual(squatted.read_bytes(), foreign)
        self.assertFalse(
            (vault / "_state/active-tasks.json").is_file(),
            msg="a refused vector must not reach registry publication",
        )
        self.assert_no_staging_residue(vault, task_id)

    def test_publication_precedes_registration_in_the_sender_source(self) -> None:
        """The ordering P3.7b names, pinned against the literal seam.

        `test_sendtask_hardening_r2` proves the replay/reuse behaviour of this
        window; this pins the one thing that makes the window safe at all --
        the complete vector is on disk before any of it is registered.
        """

        sender = SEND_TASK.read_text(encoding="utf-8")
        publish_marker = "Publish the complete admitted packet vector before registering"
        self.assertIn(publish_marker, sender)
        publish_at = sender.index(publish_marker)
        register_at = sender.index('--register-swarm "$TASK_ID"')
        self.assertLess(publish_at, register_at)
        # Every child is re-verified against its admitted bytes after the whole
        # vector is published and before registration.
        revalidate_at = sender.index(
            "swarm candidate vector changed before registry publication"
        )
        self.assertLess(publish_at, revalidate_at)
        self.assertLess(revalidate_at, register_at)
