#!/usr/bin/env python3
"""V2 trusted-launch-path — Rule-6 held-action authorization boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import os
import re
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import held_action_gate as gate  # noqa: E402


_SNAKE_CASE = re.compile(r"[a-z]+(?:_[a-z]+)*")

SIGNING_KEY = b"supervisor-held-action-signing-key-material-32b"


def _mint(**overrides) -> gate.HeldActionToken:
    defaults = dict(
        category="public_release",
        target="origin/v2",
        task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
        attempt_id="d-" + "a" * 32,
        issued_at=1_000,
        expires_at=1_300,
        signing_key=SIGNING_KEY,
    )
    defaults.update(overrides)
    return gate.mint_token(**defaults)


def _verify(token: object, **overrides) -> gate.HeldActionToken:
    defaults = dict(
        signing_key=SIGNING_KEY,
        expected_category="public_release",
        expected_target="origin/v2",
        expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
        expected_attempt_id="d-" + "a" * 32,
        now=1_100,
    )
    defaults.update(overrides)
    return gate.verify_token(token, **defaults)  # type: ignore[arg-type]


class HeldCategoriesTests(unittest.TestCase):
    def test_policy_vocabulary_and_hard_rule_match_the_controller_set(self) -> None:
        """The machine vocabulary and human policy cannot drift from admission."""

        policy = ROOT / "shared/lane-policy.tsv"
        declarable = {
            row[2]
            for row in (
                line.rstrip("\n").split("\t")
                for line in policy.read_text(encoding="utf-8").splitlines()
            )
            if len(row) > 2 and row[0] == "vocabulary" and row[1] == "operator_gate"
        }

        self.assertTrue(declarable, "lane-policy declares no operator_gate vocabulary")
        self.assertEqual(
            gate.HELD_CATEGORIES,
            declarable,
            "lane-policy operator_gate vocabulary must equal controller-held categories",
        )

        hard_rule = next(
            line
            for line in (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("6. These held categories require explicit operator approval as policy:")
        )
        policy_clause = hard_rule.split(":", 1)[1].split(". ", 1)[0]
        hard_rule_categories = frozenset(re.findall(r"`([a-z_]+)`", policy_clause))
        self.assertEqual(
            gate.HELD_CATEGORIES,
            hard_rule_categories,
            "Hard Rule 6 must list exactly the controller-held categories",
        )

    def test_an_obviously_synthetic_controller_only_category_is_not_declarable(
        self,
    ) -> None:
        """The subset model still handles a controller-only synthetic token."""

        policy = ROOT / "shared/lane-policy.tsv"
        declarable = {
            row[2]
            for row in (
                line.rstrip("\n").split("\t")
                for line in policy.read_text(encoding="utf-8").splitlines()
            )
            if len(row) > 2 and row[0] == "vocabulary" and row[1] == "operator_gate"
        }
        controller_with_synthetic = gate.HELD_CATEGORIES | {
            "obviously_synthetic_controller_only"
        }
        self.assertEqual(set(), declarable - controller_with_synthetic)
        self.assertNotIn("obviously_synthetic_controller_only", declarable)

    def test_the_held_vocabulary_uses_one_spelling_convention(self) -> None:
        """Hyphen/underscore drift is what let the two vocabularies diverge."""
        self.assertEqual(
            [],
            sorted(c for c in gate.HELD_CATEGORIES if not _SNAKE_CASE.fullmatch(c)),
        )


class LifecycleMemoryPolicyTests(unittest.TestCase):
    def test_generic_recall_guidance_defers_to_the_dispatch_aperture(self) -> None:
        lifecycle = (ROOT / "shared/lifecycle.md").read_text(encoding="utf-8")
        section = lifecycle.split(
            "## 10. Knowledge-layer checks obey the memory aperture", 1
        )[1].split("## 11.", 1)[0]

        self.assertIn("binding memory policy", section)
        self.assertIn("`rich`, `default`, and `focused`", section)
        self.assertIn("`cold` and `pool_blind`", section)
        self.assertIn("`none`", section)
        self.assertIn("do not call `recall`", section)
        self.assertNotIn("list_attempts", section)

        # `default` joined the read-permitting bullet on 2026-08-17 with the
        # dispatch default (memory-loop spec §4). §10 is the rule a worker
        # reads to learn whether it may recall, so the aperture that an
        # omitted field now resolves to has to appear in it -- otherwise the
        # doc and the enforced launch prompt disagree, which is the split
        # this plan exists to close.
        #
        # The negative half is what makes this a guard rather than a rubber
        # stamp: the read-denying bullets must still deny, and must not
        # quietly acquire `default`.
        bullets = [line for line in section.splitlines() if line.startswith("- `")]
        permitting = [b for b in bullets if "call `chrono-vault` `recall` once" in b]
        denying = [b for b in bullets if "do not call" in b]
        self.assertEqual(len(permitting), 1)
        self.assertEqual(len(denying), 2)
        for aperture in ("rich", "default", "focused"):
            self.assertIn(f"`{aperture}`", permitting[0])
        for aperture in ("cold", "pool_blind", "none"):
            self.assertTrue(
                any(f"`{aperture}`" in bullet for bullet in denying),
                f"`{aperture}` must stay in a read-denying bullet",
            )
        for bullet in denying:
            self.assertNotIn("`default`", bullet)


class TokenMintAndVerifyTests(unittest.TestCase):
    def test_a_freshly_minted_token_verifies_against_its_own_exact_fields(self) -> None:
        token = _mint()
        claims = gate.verify_token(
            token,
            signing_key=SIGNING_KEY,
            expected_category="public_release",
            expected_target="origin/v2",
            expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
            expected_attempt_id="d-" + "a" * 32,
            now=1_100,
        )
        self.assertEqual(claims.category, "public_release")

    def test_minting_rejects_invalid_target_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid target"):
            _mint(target="origin/\nmain")

    def test_minting_rejects_a_short_signing_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 16 bytes"):
            _mint(signing_key=b"short")

    def test_minting_for_a_category_outside_the_held_set_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _mint(category="local-git-v2")

    def test_minting_rejects_malformed_task_and_attempt_ids(self) -> None:
        cases = (
            ("task", {"task_id": "not-a-task"}, "invalid task id"),
            ("attempt", {"attempt_id": "d-" + "A" * 32}, "invalid attempt id"),
        )
        for label, overrides, message in cases:
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, message):
                _mint(**overrides)

    def test_minting_rejects_invalid_timestamp_values(self) -> None:
        cases = (
            ("boolean issued_at", {"issued_at": True}),
            ("negative expires_at", {"expires_at": -1}),
        )
        for label, overrides in cases:
            with self.subTest(label=label), self.assertRaisesRegex(
                ValueError, "must be a non-negative integer"
            ):
                _mint(**overrides)

    def test_minting_rejects_nonincreasing_validity_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "later than issued_at"):
            _mint(issued_at=1_300, expires_at=1_300)

    def test_verification_rejects_the_wrong_token_type_and_token_id(self) -> None:
        with self.subTest(row="HA-TOKEN-TYPE"), self.assertRaisesRegex(
            gate.HeldActionDenied, "wrong type"
        ):
            _verify(object())

        malformed_id = replace(_mint(), token_id="g" * 64)
        with self.subTest(row="HA-TOKEN-ID"), self.assertRaisesRegex(
            gate.HeldActionDenied, "invalid token id"
        ):
            _verify(malformed_id)

    def test_verification_normalizes_a_short_key_to_held_action_denied(self) -> None:
        with self.assertRaisesRegex(gate.HeldActionDenied, "at least 16 bytes"):
            _verify(_mint(), signing_key=b"short")

    def test_verification_rejects_a_category_no_longer_held(self) -> None:
        token = _mint(category="cleanup")
        held_without_cleanup = gate.HELD_CATEGORIES - {"cleanup"}
        with mock.patch.object(gate, "HELD_CATEGORIES", held_without_cleanup):
            with self.assertRaisesRegex(
                gate.HeldActionDenied, "category is not a held category"
            ):
                _verify(token, expected_category="cleanup")

    def test_wrong_target_is_denied_even_with_a_correctly_signed_token(self) -> None:
        token = _mint(target="origin/v2")
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public_release",
                expected_target="origin/main",  # a DIFFERENT target than minted
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )

    def test_wrong_category_is_denied(self) -> None:
        token = _mint(category="public_release")
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=SIGNING_KEY,
                expected_category="paid_media",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )

    def test_wrong_task_or_attempt_is_denied(self) -> None:
        token = _mint()
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public_release",
                expected_target="origin/v2",
                expected_task_id="TASK-DIFFERENT-TASK",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public_release",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "b" * 32,
                now=1_100,
            )

    def test_expired_token_is_denied(self) -> None:
        token = _mint(issued_at=1_000, expires_at=1_300)
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public_release",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_301,
            )

    def test_not_yet_valid_token_is_denied(self) -> None:
        token = _mint(issued_at=1_000, expires_at=1_300)
        with self.assertRaisesRegex(gate.HeldActionDenied, "not yet valid"):
            _verify(token, now=999)

    def test_boolean_verification_time_is_denied(self) -> None:
        with self.assertRaisesRegex(
            gate.HeldActionDenied, "verification time must be an integer"
        ):
            _verify(_mint(), now=True)

    def test_tampered_field_is_denied(self) -> None:
        token = _mint()
        tampered = replace(token, target="origin/main")
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                tampered,
                signing_key=SIGNING_KEY,
                expected_category="public_release",
                expected_target="origin/main",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )

    def test_wrong_signing_key_is_denied(self) -> None:
        token = _mint()
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=b"a-completely-different-supervisor-key-material!",
                expected_category="public_release",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )


class HeldActionStoreTests(unittest.TestCase):
    def test_a_valid_token_authorizes_exactly_once_then_is_denied_on_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = gate.HeldActionStore(Path(directory))
            token = _mint()
            store.check_and_consume(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public_release",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )
            with self.assertRaisesRegex(gate.HeldActionDenied, "replay|consumed"):
                store.check_and_consume(
                    token,
                    signing_key=SIGNING_KEY,
                    expected_category="public_release",
                    expected_target="origin/v2",
                    expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                    expected_attempt_id="d-" + "a" * 32,
                    now=1_150,
                )

    def test_consumption_is_durable_across_a_fresh_store_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            token = _mint()
            gate.HeldActionStore(state_dir).check_and_consume(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public_release",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )
            fresh_store = gate.HeldActionStore(state_dir)
            with self.assertRaises(gate.HeldActionDenied):
                fresh_store.check_and_consume(
                    token,
                    signing_key=SIGNING_KEY,
                    expected_category="public_release",
                    expected_target="origin/v2",
                    expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                    expected_attempt_id="d-" + "a" * 32,
                    now=1_150,
                )

    def test_an_invalid_token_is_never_marked_consumed(self) -> None:
        # A denied verification must not burn the token's one-shot slot --
        # otherwise a caller who typos the target on their first try would
        # permanently lose a legitimately-issued token on a mistake.
        with tempfile.TemporaryDirectory() as directory:
            store = gate.HeldActionStore(Path(directory))
            token = _mint(target="origin/v2")
            with self.assertRaises(gate.HeldActionDenied):
                store.check_and_consume(
                    token,
                    signing_key=SIGNING_KEY,
                    expected_category="public_release",
                    expected_target="origin/main",  # wrong on purpose
                    expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                    expected_attempt_id="d-" + "a" * 32,
                    now=1_100,
                )
            # Now use it correctly -- must still succeed, since the failed
            # attempt above must not have consumed it.
            store.check_and_consume(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public_release",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )

    def test_concurrent_consumption_attempts_of_the_same_token_serialize_to_exactly_one_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            token = _mint()

            def attempt(_: int) -> bool:
                try:
                    gate.HeldActionStore(state_dir).check_and_consume(
                        token,
                        signing_key=SIGNING_KEY,
                        expected_category="public_release",
                        expected_target="origin/v2",
                        expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                        expected_attempt_id="d-" + "a" * 32,
                        now=1_100,
                    )
                    return True
                except gate.HeldActionDenied:
                    return False

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(attempt, range(8)))
            self.assertEqual(sum(results), 1)

    def test_live_lock_owner_times_out_without_losing_exclusivity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            lock_dir = state_dir / ".held-action.lockdir"
            lock_dir.mkdir()
            (lock_dir / "owner.pid").write_text(str(os.getpid()), encoding="utf-8")

            store = gate.HeldActionStore(state_dir)
            with (
                mock.patch.object(gate.time, "monotonic", side_effect=(0.0, 11.0)),
                mock.patch.object(gate.time, "sleep"),
                self.assertRaisesRegex(gate.HeldActionDenied, "timed out acquiring"),
            ):
                store.check_and_consume(
                    _mint(),
                    signing_key=SIGNING_KEY,
                    expected_category="public_release",
                    expected_target="origin/v2",
                    expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                    expected_attempt_id="d-" + "a" * 32,
                    now=1_100,
                )


class AuthorizeEntrypointTests(unittest.TestCase):
    def test_authorize_succeeds_with_a_valid_matching_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = gate.HeldActionStore(Path(directory))
            token = _mint(category="paid_media", target="anthropic-api:budget-increase")
            gate.authorize(
                category="paid_media",
                target="anthropic-api:budget-increase",
                task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                attempt_id="d-" + "a" * 32,
                token=token,
                store=store,
                signing_key=SIGNING_KEY,
                now=1_100,
            )

    def test_authorize_denies_a_held_action_with_no_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = gate.HeldActionStore(Path(directory))
            with self.assertRaises(gate.HeldActionDenied):
                gate.authorize(
                    category="delete",
                    target="departments/security/specialists/scout.md",
                    task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                    attempt_id="d-" + "a" * 32,
                    token=None,
                    store=store,
                    signing_key=SIGNING_KEY,
                    now=1_100,
                )

    def test_authorize_rejects_a_non_held_category_as_a_caller_bug(self) -> None:
        # Trusted in-scope work should never call authorize() at all -- if a
        # caller does anyway with a category outside the held set, that is a
        # programming mistake, not something to silently wave through.
        with tempfile.TemporaryDirectory() as directory:
            store = gate.HeldActionStore(Path(directory))
            with self.assertRaises(ValueError):
                gate.authorize(
                    category="run-tests",
                    target="scripts/python/tests/",
                    task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                    attempt_id="d-" + "a" * 32,
                    token=None,
                    store=store,
                    signing_key=SIGNING_KEY,
                    now=1_100,
                )


if __name__ == "__main__":
    unittest.main()
