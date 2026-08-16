"""A5 mode consolidation: every retired domain-mode capability id still resolves.

Stage-1 is resolve-only — the content/outreach/research/maintenance cards were
folded into `project/`, and legacy ids must keep dispatching to their canonical
project home with identical gates. These tests pin that contract.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PY = REPO_ROOT / "scripts" / "python"
if str(PY) not in sys.path:
    sys.path.insert(0, str(PY))

from validate_capabilities import CAPABILITY_ALIASES, resolve_capability_alias  # noqa: E402
from capability_dispatch import resolve_snapshot  # noqa: E402


class TestCapabilityAliasResolution(unittest.TestCase):
    def test_every_legacy_id_maps_to_an_existing_project_card(self) -> None:
        for legacy_id, canonical in CAPABILITY_ALIASES.items():
            with self.subTest(legacy_id=legacy_id):
                self.assertTrue(
                    canonical.startswith("project/"),
                    f"{canonical} is not a project id",
                )
                card = REPO_ROOT / "shared" / "capabilities" / f"{canonical}.md"
                self.assertTrue(card.is_file(), f"{legacy_id} -> {canonical}: {card} missing")

    def test_resolver_full_id(self) -> None:
        self.assertEqual(
            resolve_capability_alias("content", "content/image"),
            ("project", "project/image", True),
        )

    def test_resolver_bare_slug_keyed_by_packet_mode(self) -> None:
        self.assertEqual(
            resolve_capability_alias("maintenance", "memory-vault-hygiene"),
            ("project", "project/memory-vault-hygiene", True),
        )

    def test_retired_capability_ids_are_not_aliased(self) -> None:
        # P13.64 roster consolidation retired the study-coaching and personal-
        # operations roles along with their capability cards. An alias whose
        # target card no longer exists is worse than no alias: it resolves to a
        # missing file instead of failing where the packet is authored. Pin the
        # removal so neither id can be re-added without its card.
        for retired in ("research/learning-study", "maintenance/personal-operations"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, CAPABILITY_ALIASES)

    def test_resolver_passes_non_legacy_through_unchanged(self) -> None:
        self.assertEqual(
            resolve_capability_alias("project", "project/web-app"),
            ("project", "project/web-app", False),
        )
        self.assertEqual(
            resolve_capability_alias("bounty", "bounty/web-api-saas"),
            ("bounty", "bounty/web-api-saas", False),
        )

    def test_resolver_rejects_mode_prefix_mismatch(self) -> None:
        # A5-review P1: a packet mode that disagrees with the reference's prefix must be
        # REJECTED, not silently aliased into a different mode.
        with self.assertRaises(ValueError):
            resolve_capability_alias("bounty", "content/image")
        with self.assertRaises(ValueError):
            resolve_capability_alias("project", "content/image")

    def test_resolver_missing_mode_with_prefixed_reference_still_resolves(self) -> None:
        # No declared mode + a self-describing prefixed legacy id → resolves by its prefix.
        self.assertEqual(
            resolve_capability_alias("", "content/image"),
            ("project", "project/image", True),
        )

    def test_snapshot_resolves_legacy_and_preserves_gates(self) -> None:
        snap = resolve_snapshot(REPO_ROOT, "content", "content/image")
        self.assertEqual(snap["capability_id"], "project/image")
        self.assertEqual(snap["capability_card_path"], "shared/capabilities/project/image.md")
        # Gate re-anchoring keeps the pre-fold gates intact through resolution.
        self.assertIn("paid_media", snap["capability_gates"])
        self.assertIn("public_release", snap["capability_gates"])

    def test_every_legacy_id_resolves_via_dispatch(self) -> None:
        for legacy_id, canonical in CAPABILITY_ALIASES.items():
            with self.subTest(legacy_id=legacy_id):
                legacy_mode = legacy_id.split("/", 1)[0]
                snap = resolve_snapshot(REPO_ROOT, legacy_mode, legacy_id)
                self.assertEqual(snap["capability_id"], canonical)


if __name__ == "__main__":
    unittest.main()
