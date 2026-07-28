#!/usr/bin/env python3
"""V2 trusted-launch-path — Rule-6 held-action authorization boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import held_action_gate as gate  # noqa: E402


SIGNING_KEY = b"supervisor-held-action-signing-key-material-32b"


def _mint(**overrides) -> gate.HeldActionToken:
    defaults = dict(
        category="public-push",
        target="origin/v2",
        task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
        attempt_id="d-" + "a" * 32,
        issued_at=1_000,
        expires_at=1_300,
        signing_key=SIGNING_KEY,
    )
    defaults.update(overrides)
    return gate.mint_token(**defaults)


class HeldCategoriesTests(unittest.TestCase):
    def test_the_eight_named_categories_are_exactly_the_held_set(self) -> None:
        self.assertEqual(
            gate.HELD_CATEGORIES,
            frozenset(
                {
                    "delete-from-main",
                    "public-push",
                    "spend",
                    "outreach",
                    "prod-mutation",
                    "credential-change",
                    "release",
                    "default-cutover",
                }
            ),
        )


class TokenMintAndVerifyTests(unittest.TestCase):
    def test_a_freshly_minted_token_verifies_against_its_own_exact_fields(self) -> None:
        token = _mint()
        claims = gate.verify_token(
            token,
            signing_key=SIGNING_KEY,
            expected_category="public-push",
            expected_target="origin/v2",
            expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
            expected_attempt_id="d-" + "a" * 32,
            now=1_100,
        )
        self.assertEqual(claims.category, "public-push")

    def test_minting_for_a_category_outside_the_held_set_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _mint(category="local-git-v2")

    def test_wrong_target_is_denied_even_with_a_correctly_signed_token(self) -> None:
        token = _mint(target="origin/v2")
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public-push",
                expected_target="origin/main",  # a DIFFERENT target than minted
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )

    def test_wrong_category_is_denied(self) -> None:
        token = _mint(category="public-push")
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=SIGNING_KEY,
                expected_category="spend",
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
                expected_category="public-push",
                expected_target="origin/v2",
                expected_task_id="TASK-DIFFERENT-TASK",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                token,
                signing_key=SIGNING_KEY,
                expected_category="public-push",
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
                expected_category="public-push",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_301,
            )

    def test_tampered_field_is_denied(self) -> None:
        from dataclasses import replace

        token = _mint()
        tampered = replace(token, target="origin/main")
        with self.assertRaises(gate.HeldActionDenied):
            gate.verify_token(
                tampered,
                signing_key=SIGNING_KEY,
                expected_category="public-push",
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
                expected_category="public-push",
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
                expected_category="public-push",
                expected_target="origin/v2",
                expected_task_id="TASK-2026-07-22-0565-v2-trusted-launch-path",
                expected_attempt_id="d-" + "a" * 32,
                now=1_100,
            )
            with self.assertRaisesRegex(gate.HeldActionDenied, "replay|consumed"):
                store.check_and_consume(
                    token,
                    signing_key=SIGNING_KEY,
                    expected_category="public-push",
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
                expected_category="public-push",
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
                    expected_category="public-push",
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
                    expected_category="public-push",
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
                expected_category="public-push",
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
                        expected_category="public-push",
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


class AuthorizeEntrypointTests(unittest.TestCase):
    def test_authorize_succeeds_with_a_valid_matching_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = gate.HeldActionStore(Path(directory))
            token = _mint(category="spend", target="anthropic-api:budget-increase")
            gate.authorize(
                category="spend",
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
                    category="delete-from-main",
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
