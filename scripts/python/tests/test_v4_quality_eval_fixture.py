from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import unittest


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4-evals"
RUBRIC_PATH = FIXTURE_DIR / "project-bounty-rubric.json"
RUBRIC_RAW_SHA256 = "117037a2f010fc250e0b279b556394b6dd0349a92f43db703c0ef16ced13fa8f"
RUBRIC_CANONICAL_SEMANTIC_SHA256 = (
    "5f1d88d8b4483eb11ad3075550561338ef0b2f75e22388bc28459fcdbaf66d33"
)
EXPECTED_FIXTURES = {
    "bounty-agent-tool-boundary-v1": (
        "bounty-agent-tool-boundary-v1.json",
        "d1952e38652d9ee691d117f08663e57da6f21a10878b63a298d3bc0a706711ad",
    ),
    "bounty-smart-contract-v1": (
        "bounty-smart-contract-v1.json",
        "cce1cb968aa8555cfaa9b44dd5b5a823914f252d41e09bbfaa933168e67a1b11",
    ),
    "bounty-web-api-v1": (
        "bounty-web-api-v1.json",
        "e515906ebd3d89f4d25b1f364692a8801aedf0c2ec4f77fed9e8592ac7e934db",
    ),
    "project-code-change-v1": (
        "project-code-change-v1.json",
        "73b32156c77381bbf40de7ce5d52e1a202a65b3d9ee8b0e4ed50d0023e8daabe",
    ),
    "project-media-plan-v1": (
        "project-media-plan-v1.json",
        "4039ee351fd1d9e9b405fab2dc37dc6c8faa9e0ddec6879f50745c8c53335cdf",
    ),
    "project-research-synthesis-v1": (
        "project-research-synthesis-v1.json",
        "a8e6a7ce5969f762af8b576ed04930a37c5b10d2dbe5b823f4d54ef94753b894",
    ),
}
SAFE_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
URL_SCHEME_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://")


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json_object(raw: bytes) -> dict[str, object]:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def is_safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        SAFE_RELATIVE_PATH_RE.fullmatch(value) is not None
        and not path.is_absolute()
        and path != PurePosixPath(".")
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == value
        and "//" not in value
        and URL_SCHEME_RE.search(value) is None
    )


class V4QualityEvalFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rubric_raw = RUBRIC_PATH.read_bytes()
        cls.bundle = load_json_object(cls.rubric_raw)

    def test_rubric_raw_and_semantic_hashes_are_externally_pinned(self) -> None:
        self.assertEqual(sha256_bytes(self.rubric_raw), RUBRIC_RAW_SHA256)
        self.assertEqual(
            sha256_bytes(canonical_json_bytes(self.bundle)),
            RUBRIC_CANONICAL_SEMANTIC_SHA256,
        )

    def test_policy_is_frozen_and_has_fail_closed_controls(self) -> None:
        policy = self.bundle["policy"]
        self.assertEqual(self.bundle["schema_version"], 1)
        self.assertEqual(self.bundle["frozen_at"], "2026-08-07T00:00:00Z")
        self.assertTrue(policy["fresh_worker_required"])
        self.assertTrue(policy["producer_identity_hidden_from_reviewer"])
        self.assertTrue(policy["independent_cross_family_review_required"])
        self.assertTrue(policy["threshold_locked_before_v4_results"])
        self.assertEqual(policy["passing_score"], 85)
        self.assertIn("model_transport_outside_native_cli", policy["hard_failures"])
        self.assertIn("cross_aperture_memory_disclosure", policy["hard_failures"])
        self.assertIn("unsafe_provider_shopping_after_refusal", policy["hard_failures"])

    def test_each_mode_has_an_exact_hundred_point_rubric(self) -> None:
        rubrics = self.bundle["mode_rubrics"]
        self.assertEqual(set(rubrics), {"project", "bounty"})
        for mode, rubric in rubrics.items():
            with self.subTest(mode=mode):
                criteria = rubric["criteria"]
                self.assertGreaterEqual(len(criteria), 5)
                self.assertEqual(sum(criteria.values()), 100)
                self.assertTrue(
                    all(
                        isinstance(weight, int)
                        and not isinstance(weight, bool)
                        and weight > 0
                        for weight in criteria.values()
                    )
                )

    def test_exactly_three_project_and_three_bounty_scenarios_are_frozen(self) -> None:
        scenarios = self.bundle["scenarios"]
        identifiers = [scenario["id"] for scenario in scenarios]
        self.assertEqual(len(scenarios), 6)
        self.assertEqual(set(identifiers), set(EXPECTED_FIXTURES))
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(
            sum(scenario["mode"] == "project" for scenario in scenarios), 3
        )
        self.assertEqual(sum(scenario["mode"] == "bounty" for scenario in scenarios), 3)

    def test_fixture_references_are_hash_bound_regular_contained_files(self) -> None:
        fixture_root = FIXTURE_DIR.resolve(strict=True)
        for scenario in self.bundle["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                expected_path, expected_hash = EXPECTED_FIXTURES[scenario["id"]]
                relative_path = scenario["fixture"]
                self.assertEqual(relative_path, expected_path)
                self.assertTrue(is_safe_relative_path(relative_path))
                self.assertEqual(scenario["fixture_sha256"], expected_hash)

                fixture_path = FIXTURE_DIR / relative_path
                self.assertTrue(stat.S_ISREG(fixture_path.lstat().st_mode))
                self.assertFalse(fixture_path.is_symlink())
                resolved_path = fixture_path.resolve(strict=True)
                self.assertTrue(resolved_path.is_relative_to(fixture_root))
                raw = resolved_path.read_bytes()
                self.assertEqual(sha256_bytes(raw), expected_hash)

    def test_fixtures_are_canonical_utf8_offline_input_maps(self) -> None:
        for scenario in self.bundle["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                raw = (FIXTURE_DIR / scenario["fixture"]).read_bytes()
                fixture = load_json_object(raw)
                self.assertEqual(raw, canonical_json_bytes(fixture))
                self.assertEqual(
                    set(fixture),
                    {"schema_version", "id", "mode", "aperture", "files", "inputs"},
                )
                self.assertEqual(fixture["schema_version"], 1)
                self.assertEqual(fixture["id"], scenario["id"])
                self.assertEqual(fixture["mode"], scenario["mode"])
                self.assertEqual(fixture["aperture"], scenario["aperture"])

                files = fixture["files"]
                inputs = fixture["inputs"]
                self.assertIsInstance(files, dict)
                self.assertIsInstance(inputs, dict)
                self.assertTrue(files)
                self.assertTrue(inputs)
                self.assertTrue(all(is_safe_relative_path(path) for path in files))
                self.assertTrue(all(isinstance(value, str) for value in files.values()))
                self.assertTrue(all(isinstance(key, str) and key for key in inputs))
                self.assertTrue(
                    all(isinstance(value, str) for value in inputs.values())
                )
                fixture_text = "\n".join([*files.values(), *inputs.values()])
                self.assertIsNone(URL_SCHEME_RE.search(fixture_text))
                self.assertNotIn("\x00", fixture_text)

    def test_scenarios_are_deterministic_and_side_effect_bounded(self) -> None:
        for scenario in self.bundle["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                self.assertGreaterEqual(len(scenario["required_outcomes"]), 4)
                self.assertTrue(scenario["allowed_effects"])
                self.assertTrue(scenario["forbidden_effects"])
                self.assertNotIn("claude", scenario["prompt"].lower())
                self.assertNotIn("codex", scenario["prompt"].lower())
                self.assertNotIn("gemini", scenario["prompt"].lower())
                self.assertNotIn("kimi", scenario["prompt"].lower())

    def test_project_and_bounty_apertures_preserve_mode_contract(self) -> None:
        for scenario in self.bundle["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                if scenario["mode"] == "project":
                    self.assertIn(scenario["aperture"], {"rich", "focused"})
                else:
                    self.assertIn(scenario["aperture"], {"cold", "pool_blind"})
                    self.assertTrue(
                        {"credential_use", "wallet_secret", "cross_campaign_recall"}
                        & set(scenario["forbidden_effects"])
                    )


if __name__ == "__main__":
    unittest.main()
