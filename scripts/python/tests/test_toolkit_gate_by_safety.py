"""Consumer oracle for the security-doctrine toolkit gate.

The parent change (TASK-2026-08-10-0750) gated ~8 KB of offensive-security +
research doctrine on the *mailbox namespace*. A cross-family review returned
REJECT: `source_namespace` is a storage location, never a risk signal (root
Hard Rule 3), so keying on it silently stripped the toolchain from every
high-safety or heightened-risk role that does not live in the `security`
mailbox -- `smart-contract-engineer` (coding, safety_level:high,
heightened_risk, dual-use/financial) foremost among them.

The parent's own tests proved only that the *renderer* behaved; nothing proved
a *specialist* still receives what it needs. This suite is that missing consumer
oracle. It does not reimplement the selector in Python -- it drives the real
`shared/dispatch-toolkit.sh` with real specialist names against the real
`shared/specialist-runtime-map.tsv`, which is the exact entry point production
takes (`bin/send-task.sh` calls the same script with `$SPECIALIST` as $4).

Every assertion here fails against the pre-fix (namespace-keyed) toolkit; see
`test_smart_contract_engineer_project_is_pinned` for the reviewer's demonstrated
failing path.
"""

from __future__ import annotations

import csv
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLKIT = ROOT / "shared" / "dispatch-toolkit.sh"
RUNTIME_MAP = ROOT / "shared" / "specialist-runtime-map.tsv"
SEND_TASK = ROOT / "bin" / "send-task.sh"

# Doctrine markers, verbatim from the toolkit's rendered output. These are the
# same strings the parent's renderer test pins, so a marker rename fails both.
SECURITY = "## Security toolchain available to this dispatch"
VERDICT = "## Verdict discipline"


def load_specialist_rows() -> list[dict[str, str]]:
    with RUNTIME_MAP.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle, delimiter="\t") if row["specialist"]]


def is_high_or_heightened(row: dict[str, str]) -> bool:
    """The exact predicate the corrected gate keys on: high safety OR heightened risk."""
    return row["safety_level"] == "high" or row["heightened_risk"] == "true"


def render(namespace: str, specialist: str, mode: str = "project", lane: str = "claude") -> str:
    """Render a dispatch brief through the REAL toolkit, the way production does.

    `bin/send-task.sh` invokes `bash "$TOOLKIT" "$COMPAT_NAMESPACE" "$TO_MODEL"
    "$MODE" "$SPECIALIST"`; this mirrors that argv exactly.
    """
    proc = subprocess.run(
        ["bash", str(TOOLKIT), namespace, lane, mode, specialist],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=180,
    )
    if proc.returncode != 0:
        raise AssertionError(f"toolkit render failed for {specialist!r}: {proc.stderr}")
    return proc.stdout


class ToolkitGateConsumerOracle(unittest.TestCase):
    """For every risky specialist, the RENDERED prompt must still carry doctrine."""

    def test_every_high_or_heightened_specialist_receives_doctrine(self) -> None:
        """The core oracle. Ordinary `project` mode (NOT bounty) — the very mode the
        parent selector wrongly stripped for a coding-namespace security role.

        Iterates every specialist the runtime map marks high-safety or
        heightened-risk, in that specialist's own source namespace, and asserts the
        offensive-security toolchain and the verdict-discipline rail are present in
        the prompt the specialist actually receives.
        """
        risky = [r for r in load_specialist_rows() if is_high_or_heightened(r)]
        self.assertGreater(len(risky), 0, "no risky specialists resolved — map read failed")
        for row in risky:
            specialist = row["specialist"]
            namespace = row["source_namespace"]
            with self.subTest(specialist=specialist, namespace=namespace):
                out = render(namespace, specialist, "project")
                self.assertIn(
                    SECURITY,
                    out,
                    f"{specialist} ({namespace}, safety_level={row['safety_level']}, "
                    f"heightened_risk={row['heightened_risk']}) lost the security toolchain",
                )
                self.assertIn(
                    VERDICT,
                    out,
                    f"{specialist} lost the verdict-discipline rail",
                )

    def test_smart_contract_engineer_project_is_pinned(self) -> None:
        """The path the reviewer demonstrated failing, pinned by name.

        `smart-contract-engineer` is canonically coding-namespace, safety_level:high,
        heightened_risk:true, tagged dual-use/financial. On the pre-fix toolkit,
        `coding × project` renders ZERO doctrine markers (the 4th arg is ignored and
        the gate keys on NAMESPACE==coding). This asserts the corrected behavior.
        """
        row = next(
            r for r in load_specialist_rows() if r["specialist"] == "smart-contract-engineer"
        )
        self.assertEqual(row["source_namespace"], "coding")
        self.assertEqual(row["safety_level"], "high")
        self.assertEqual(row["heightened_risk"], "true")
        out = render("coding", "smart-contract-engineer", "project")
        self.assertIn(SECURITY, out)
        self.assertIn(VERDICT, out)

    def test_non_security_risky_blast_radius_is_derived_from_runtime_map(self) -> None:
        """Derive the non-security risky blast radius from the canonical roster.

        Specialists outside the security mailbox that are high-safety or
        heightened-risk lost doctrine under the namespace selector.
        The literal command behind this claim is the DictReader over the runtime map
        plus the `is_high_or_heightened` predicate above.
        """
        rows = load_specialist_rows()
        non_security_risky = sorted(
            r["specialist"]
            for r in rows
            if is_high_or_heightened(r) and r["source_namespace"] != "security"
        )
        # Spot members the review named explicitly — each must be in the set.
        for named in (
            "smart-contract-engineer",
            "scraping-engineer",
            "asset-provenance-and-rights-auditor",
            "database-engineer",
            "devops-engineer",
            "mac-ops",
            "loop-operator",
        ):
            self.assertIn(named, non_security_risky)
        self.assertEqual(
            len(non_security_risky),
            sum(
                is_high_or_heightened(row)
                and row["source_namespace"] != "security"
                for row in rows
            ),
        )

    def test_every_security_namespace_specialist_still_receives_doctrine(self) -> None:
        """No regression for the mailbox the old selector protected. Every security
        specialist is safety_level:high, so the safety-keyed gate keeps them all —
        proving the corrected selector is a superset, not a swap.
        """
        security_rows = [
            r for r in load_specialist_rows() if r["source_namespace"] == "security"
        ]
        self.assertGreater(len(security_rows), 0)
        for row in security_rows:
            with self.subTest(specialist=row["specialist"]):
                self.assertEqual(
                    row["safety_level"],
                    "high",
                    "a non-high security specialist would need an explicit fallback",
                )
                out = render("security", row["specialist"], "project")
                self.assertIn(SECURITY, out)
                self.assertIn(VERDICT, out)

    def test_saving_survives_for_genuinely_low_risk_roles(self) -> None:
        """The feature is preserved where it is earned. A low/medium, non-heightened,
        non-bounty role still pays nothing for doctrine it will not use.
        """
        rows = load_specialist_rows()
        fixtures = []
        for namespace in ("content", "coding", "sysmgmt"):
            fixtures.append(
                next(
                    row
                    for row in sorted(rows, key=lambda item: item["specialist"])
                    if row["source_namespace"] == namespace
                    and row["safety_level"] in {"low", "medium"}
                    and row["heightened_risk"] == "false"
                )
            )
        for row in fixtures:
            namespace = row["source_namespace"]
            specialist = row["specialist"]
            with self.subTest(specialist=specialist):
                out = render(namespace, specialist, "project")
                self.assertNotIn(SECURITY, out)
                self.assertNotIn(VERDICT, out)

    def test_byte_saving_is_substantial_for_a_low_risk_role(self) -> None:
        """Within ONE specialist (identical mailbox roster), a medium-risk project
        task is at least ~8 KB lighter than the same specialist in bounty mode.
        """
        heavy = render("coding", "backend-engineer", "bounty")
        light = render("coding", "backend-engineer", "project")
        self.assertGreater(len(heavy) - len(light), 8000)

    def test_production_wires_specialist_into_both_toolkit_call_sites(self) -> None:
        """The oracle above renders through the toolkit directly; this proves that is
        the SAME argv production builds. Both `bin/send-task.sh` call sites (single
        dispatch and swarm child) must pass the specialist as the 4th argument, or the
        gate would silently fall back to fail-open in production.
        """
        sender = SEND_TASK.read_text(encoding="utf-8")
        self.assertIn(
            'bash "$TOOLKIT" "$COMPAT_NAMESPACE" "$TO_MODEL" "$MODE" "$SPECIALIST"',
            sender,
        )
        self.assertIn(
            'bash "$TOOLKIT" "$COMPAT_NAMESPACE" "$lane" "$MODE" "$SPECIALIST"',
            sender,
        )

    def test_selector_source_keys_on_safety_not_namespace(self) -> None:
        """The defect, pinned at the source. The security-doctrine gate must no longer
        key on the mailbox namespace; it must read the safety columns.
        """
        toolkit = TOOLKIT.read_text(encoding="utf-8")
        self.assertNotIn('"$NAMESPACE" == "security"', toolkit)
        self.assertIn('"$SAFETY_LEVEL" == "high"', toolkit)
        self.assertIn('"$HEIGHTENED_RISK" == "true"', toolkit)


if __name__ == "__main__":
    unittest.main()
