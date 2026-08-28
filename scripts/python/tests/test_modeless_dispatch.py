#!/usr/bin/env python3
"""The modeless third state must fail closed on every authority axis.

A packet may declare no `mode`. The controller translates that single absence,
at one site, into the affirmative token `modeless`. From there the launch
boundary treats `modeless` as a real third state whose authority is the
INTERSECTION of the typed modes: on every axis where `project` and `bounty`
disagree, `modeless` gets the narrower value.

This suite is the fail-closed rail. Every test here asserts the same shape:
`modeless` is denied an authority wherever EITHER named mode denies it. If a
future edit lets a modeless packet obtain something a project OR a bounty packet
would be refused, one of these tests goes red. The clearance write-floor test
(`test_modeless_memory_write_floor_is_the_strict_intersection`) is the one the
task singled out as the deliverable to protect.

The three owners under test:
  * scripts/python/verification_contract.py -- the contract the dispatcher pins
  * plugins/chrono-vault/clearance.py       -- the memory write floor / clearance
  * bin/board-supervisor.sh                 -- the launch budget ceiling
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
CHRONO_VAULT = ROOT / "plugins" / "chrono-vault"
for entry in (str(PYTHON_SCRIPTS), str(CHRONO_VAULT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import clearance  # noqa: E402
from verification_contract import (  # noqa: E402
    MODELESS_MODE,
    SUPPORTED_MODES,
    SUPPORTED_TYPED_MODES,
    ContractError,
    derive_verification_contract,
    validate_verification_contract,
    verification_contract_sha256,
)


def _admission(
    *,
    mode: object,
    result_type: str = "normal",
    to_model: str = "claude",
    capability: object = None,
) -> dict[str, object]:
    """A minimal, ordinary-internal-work admission (no capability card, no gates)."""
    admission: dict[str, object] = {
        "task_id": "TASK-TEST-MODELESS",
        "run_id": "MDL-TEST-001",
        "mode": mode,
        "result_type": result_type,
        "to_model": to_model,
        "dispatch_kind": "single",
    }
    if capability is not None:
        admission["capability"] = capability
    return admission


class ModelessContractTests(unittest.TestCase):
    """verification_contract.py: modeless is accepted, project-shaped, and narrower."""

    def test_modeless_is_a_supported_but_distinct_mode(self) -> None:
        self.assertIn(MODELESS_MODE, SUPPORTED_MODES)
        # It is NOT a typed mode and NOT an alias for project/bounty: a reader
        # can tell it apart from an explicit choice.
        self.assertNotIn(MODELESS_MODE, SUPPORTED_TYPED_MODES)
        self.assertEqual(MODELESS_MODE, "modeless")

    def test_modeless_derives_the_project_shaped_body_tagged_modeless(self) -> None:
        contract = derive_verification_contract(_admission(mode="modeless"))
        # The ONE field that distinguishes the third state, present and explicit.
        self.assertEqual(contract["mode"], "modeless")
        # Body is the ordinary internal-work shape (same as project)...
        self.assertEqual(
            contract["required_verification_kinds"],
            ["project_tests", "recipient_contract"],
        )
        self.assertEqual(
            contract["memory_policy"], {"recall": "required", "record": "required"}
        )
        # ...but it is NOT the bounty body: no offensive-scope authority.
        self.assertIsNone(contract["bounty_policy"])
        # And it round-trips through the validator unchanged.
        self.assertEqual(validate_verification_contract(contract), contract)

    def test_modeless_is_denied_dry_run_exactly_as_project_is(self) -> None:
        # Anti-widening (result_type latitude): `dry_run` is bounty-only. project
        # denies it; the intersection therefore denies it; modeless must too.
        with self.assertRaisesRegex(ContractError, "modeless result_type"):
            derive_verification_contract(
                _admission(mode="modeless", result_type="dry_run")
            )
        # bounty is the only mode that MAY carry dry_run -- proves the denial
        # above is a real divergence, not a blanket rejection.
        bounty = derive_verification_contract(
            {
                **_admission(mode="bounty", result_type="dry_run"),
                "run_id": "BTY-TEST-001",
            }
        )
        self.assertEqual(bounty["result_type"], "dry_run")

    def test_modeless_accepts_only_the_project_result_type_set(self) -> None:
        for result_type in ("normal", "review", "verification"):
            with self.subTest(result_type=result_type):
                # review/verification need typed-review evidence; deriving with a
                # bare admission raises a DIFFERENT error than the mode gate, so
                # the mode itself is what we assert is accepted here.
                admission = _admission(mode="modeless", result_type=result_type)
                try:
                    derive_verification_contract(admission)
                except ContractError as exc:
                    self.assertNotIn("result_type must be", str(exc))

    def test_modeless_may_not_carry_a_capability_card(self) -> None:
        # Anti-widening (tool projection): capability cards live under
        # shared/capabilities/<mode>/ and grant mode-specific tool authority. A
        # modeless packet has no <mode> namespace, so the intersection of card
        # authority is empty -- it may resolve none.
        card = {"id": "project/web-app", "card_sha256": "a" * 64, "derived_state": "live"}
        with self.assertRaisesRegex(ContractError, "modeless dispatch cannot carry"):
            derive_verification_contract(_admission(mode="modeless", capability=card))
        # The very same card is legitimate under its own typed mode: proves the
        # refusal is modeless-specific, not a broken capability path.
        project = derive_verification_contract(
            {**_admission(mode="project"), "capability": card, "run_id": "PRJ-TEST-001"}
        )
        self.assertEqual(project["capability"]["id"], "project/web-app")

    def test_modeless_contract_carries_no_gates_by_default(self) -> None:
        # Held-category authority is denied uniformly at admission (Hard Rule 6),
        # not granted by mode. A modeless packet with no gate inputs derives an
        # empty gate list, exactly like project -- it cannot mint held authority.
        contract = derive_verification_contract(_admission(mode="modeless"))
        self.assertEqual(contract["expected_gates"], [])

    def test_unhashable_modes_raise_the_domain_error(self) -> None:
        for bad in ([], {}):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ContractError, "unsupported mode"):
                    derive_verification_contract(_admission(mode=bad))


class ModelessClearanceTests(unittest.TestCase):
    """clearance.py: the memory write floor is the strict intersection."""

    def setUp(self) -> None:
        self._saved = os.environ.get(clearance.CONTEXT_ENV)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(clearance.CONTEXT_ENV, None)
        else:
            os.environ[clearance.CONTEXT_ENV] = self._saved

    @contextmanager
    def _engagement(self, *, mode: str, aperture: str):
        start = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        context = {
            "schema": clearance.CONTEXT_SCHEMA,
            "task_id": "TASK-2026-08-28-2210-u3",
            "attempt_id": "d-" + "0" * 32,
            "generation": 1,
            "mode": mode,
            "aperture": aperture,
            # `focused` is the one aperture that requires an exact focus target;
            # every other aperture requires focus to be absent.
            "focus": "shared/protocol.md" if aperture == "focused" else None,
            "engagement_start": start,
        }
        os.environ[clearance.CONTEXT_ENV] = json.dumps(context)
        try:
            yield
        finally:
            os.environ.pop(clearance.CONTEXT_ENV, None)

    def _record_sensitivity(self, *, mode: str, aperture: str) -> object:
        with self._engagement(mode=mode, aperture=aperture):
            result = clearance.apply_record_policy("learning", {"title": "t", "body": "b"})
        return result.get("sensitivity")

    def _record_allowing_apertures(self) -> list[str]:
        policies = clearance.memory_policies()
        return [name for name, row in policies.items() if row["record"] == "allow"]

    def test_modeless_memory_write_floor_is_the_strict_intersection(self) -> None:
        # THE deliverable. For every aperture that permits a write, a modeless
        # note must be forced to the strictest sensitivity any typed mode
        # imposes -- and must NEVER be allowed a sensitivity a named mode would
        # have denied. project permits `internal`; bounty forces `restricted`;
        # the intersection is `restricted`. So a note project would leave
        # `internal` must, under modeless, come out `restricted`.
        policies = clearance.memory_policies()
        for aperture in self._record_allowing_apertures():
            with self.subTest(aperture=aperture):
                project_floor = policies[aperture]["project_write_floor"]
                bounty_floor = policies[aperture]["bounty_write_floor"]
                strictest = (
                    clearance.RESTRICTED
                    if clearance.RESTRICTED in {project_floor, bounty_floor}
                    else clearance.INTERNAL
                )
                modeless = self._record_sensitivity(mode="modeless", aperture=aperture)
                # `None` means "not forced up" (stays at/below internal). We
                # model the effective floor a `None` result represents so the
                # comparison is apples to apples.
                effective = modeless if modeless == clearance.RESTRICTED else clearance.INTERNAL
                self.assertEqual(
                    effective,
                    strictest,
                    f"modeless floor under {aperture!r} is not the strict intersection",
                )
                # The concrete anti-widening claim, stated directly: wherever a
                # bonded bounty note is forced restricted, a modeless note is too.
                bounty = self._record_sensitivity(mode="bounty", aperture=aperture)
                self.assertEqual(modeless, bounty)

    def test_modeless_never_writes_more_broadly_than_the_stricter_named_mode(
        self,
    ) -> None:
        # Restated as a pure inequality over disclosure breadth: restricted is
        # narrower than internal. modeless must never be broader (== internal /
        # None) on any aperture where a named mode is narrow (== restricted).
        rank = {clearance.RESTRICTED: 1, clearance.INTERNAL: 0, None: 0}
        for aperture in self._record_allowing_apertures():
            with self.subTest(aperture=aperture):
                project = self._record_sensitivity(mode="project", aperture=aperture)
                bounty = self._record_sensitivity(mode="bounty", aperture=aperture)
                modeless = self._record_sensitivity(mode="modeless", aperture=aperture)
                self.assertGreaterEqual(
                    rank[modeless],
                    max(rank[project], rank[bounty]),
                    "modeless disclosure is broader than the strictest named mode",
                )

    def test_dropped_or_unknown_mode_fails_closed_at_the_memory_boundary(self) -> None:
        # Distinguishing the intentional third state from a LOST field. Only the
        # affirmative `modeless` token is admitted. None, "", and an unknown
        # string are all rejected -- a dropped mode can never silently become
        # modeless (or anything else).
        for bad in (None, "", "project ", "ambient", "none", "MODELESS"):
            with self.subTest(bad=bad):
                context = {
                    "schema": clearance.CONTEXT_SCHEMA,
                    "task_id": "TASK-2026-08-28-2210-u3",
                    "attempt_id": "d-" + "0" * 32,
                    "generation": 1,
                    "mode": bad,
                    "aperture": "cold",
                    "focus": None,
                    "engagement_start": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
                with self.assertRaises(clearance.ClearanceError):
                    clearance.validate_memory_context(context)

    def test_modeless_is_admitted_when_the_token_is_affirmative(self) -> None:
        # The mirror of the test above: the exact `modeless` token IS accepted,
        # so the fail-closed rejection above is about the value, not a blanket ban.
        context = {
            "schema": clearance.CONTEXT_SCHEMA,
            "task_id": "TASK-2026-08-28-2210-u3",
            "attempt_id": "d-" + "0" * 32,
            "generation": 1,
            "mode": "modeless",
            "aperture": "cold",
            "focus": None,
            "engagement_start": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        self.assertEqual(
            clearance.validate_memory_context(context)["mode"], "modeless"
        )

    def test_unhashable_modes_raise_the_clearance_domain_error(self) -> None:
        for bad in ([], {}):
            with self.subTest(bad=bad):
                context = {
                    "schema": clearance.CONTEXT_SCHEMA,
                    "task_id": "TASK-2026-08-28-2210-u3",
                    "attempt_id": "d-" + "0" * 32,
                    "generation": 1,
                    "mode": bad,
                    "aperture": "cold",
                    "focus": None,
                    "engagement_start": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
                with self.assertRaisesRegex(
                    clearance.ClearanceError,
                    "unsupported memory engagement mode",
                ):
                    clearance.validate_memory_context(context)


class ModelessEntryPointTests(unittest.TestCase):
    """The prepared-packet and generating-wrapper contracts are asymmetric."""

    def test_protocol_states_one_asymmetric_mode_contract(self) -> None:
        protocol = (ROOT / "shared/protocol.md").read_text(encoding="utf-8")
        self.assertEqual(protocol.count("This is the single mode contract."), 1)
        self.assertIn(
            "mode: bounty | project | modeless | <field absent → modeless>",
            protocol,
        )
        self.assertIn(
            "scripts/send-task.sh ... --mode <project|bounty|modeless>",
            protocol,
        )
        self.assertIn(
            "translates an absent prepared-packet `mode` field to `modeless`",
            protocol,
        )
        self.assertIn(
            "For project, bounty, and modeless engagements", protocol
        )
        self.assertNotIn(
            "new V4 Markdown uses exactly `project` or `bounty`", protocol
        )
        self.assertNotIn("For Project and Bounty,", protocol)

    def _prepared_packet(self, task_id: str, run_id: str) -> str:
        return f"""---
id: {task_id}
run_id: {run_id}
to_model: gpt-codex
specialist: none
source_namespace: shared
compatibility_namespace: coding
write_scope: []
parallel_safe: false
direct_lane_work_allowed: true
mandatory_review: false
review_model: none
review_triggers: []
return_artifact: departments/coding/outbox/{task_id}-response.md
---

Exercise the prepared-packet modeless path.
"""

    def test_prepared_packet_without_mode_dry_runs_as_modeless_with_contract(
        self,
    ) -> None:
        task_id = "TASK-2026-08-29-0011-modeless-dry-run"
        run_id = "MODELLESS-DISPATCH-TEST"
        with tempfile.TemporaryDirectory(prefix="modeless-dispatch-") as directory:
            root = Path(directory)
            packet = root / "packet.md"
            packet.write_text(
                self._prepared_packet(task_id, run_id), encoding="utf-8"
            )
            environment = {
                **os.environ,
                "VAULT_ROOT": str(root),
                "SQUAD_BASE_BRANCH": "v2",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            environment.pop("SQUAD_DISPATCH_MODE", None)

            result = subprocess.run(
                ["bash", str(ROOT / "bin/send-task.sh"), str(packet), "--dry-run"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            emitted = re.search(
                r"Verification contract: version=verification-contract/v1 "
                r"sha256=([0-9a-f]{64})",
                result.stdout,
            )
            self.assertIsNotNone(emitted, result.stdout + result.stderr)
            expected = derive_verification_contract(
                {
                    "task_id": task_id,
                    "run_id": run_id,
                    "mode": "modeless",
                    "result_type": "normal",
                    "to_model": "gpt-codex",
                    "dispatch_kind": "single",
                    "capability": None,
                    "runtime_map_gates": [],
                    "review_required": False,
                }
            )
            self.assertEqual(
                emitted.group(1), verification_contract_sha256(expected)
            )
            self.assertFalse(
                (root / f"departments/coding/inbox/{task_id}.md").exists()
            )

    def test_generating_wrapper_requires_mode_but_accepts_explicit_modeless(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="modeless-wrapper-") as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (root / "shared").mkdir()
            (root / "bin").mkdir()
            body = root / "body.md"
            body.write_text("Exercise the generating wrapper.\n", encoding="utf-8")
            packet_capture = root / "packet-capture.md"
            (root / "shared/lead-windows.sh").write_text(
                "COMPATIBILITY_NAMESPACES=(coding security content sysmgmt research)\n"
                'is_compatibility_namespace() { [[ "$1" == coding ]]; }\n',
                encoding="utf-8",
            )
            runtime_fields = ["sol", "shared", "judgment", "medium"]
            runtime_fields.extend(
                ["x", "x", "claude", "x", "x", "x", "x", "x", "x", "gpt-codex"]
            )
            (root / "shared/specialist-runtime-map.tsv").write_text(
                "\t".join(runtime_fields) + "\n", encoding="utf-8"
            )
            hardened = root / "bin/send-task.sh"
            hardened.write_text(
                "#!/bin/bash\n"
                'cp "$1" "$PACKET_CAPTURE"\n',
                encoding="utf-8",
            )
            hardened.chmod(0o755)
            uuidgen = tools / "uuidgen"
            uuidgen.write_text(
                "#!/bin/sh\nprintf '12345678-1234-1234-1234-123456789abc\\n'\n",
                encoding="utf-8",
            )
            uuidgen.chmod(0o755)
            environment = {
                **os.environ,
                "PACKET_CAPTURE": str(packet_capture),
                "PATH": f"{tools}:/usr/bin:/bin",
                "VAULT_ROOT": str(root),
            }
            command = [
                "bash",
                str(ROOT / "scripts/send-task.sh"),
                "coding",
                str(body),
                "sol",
                "claude",
            ]

            omitted = subprocess.run(
                command,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(omitted.returncode, 1, omitted.stderr)
            self.assertIn("missing required --mode", omitted.stdout)
            self.assertFalse(packet_capture.exists())

            explicit = subprocess.run(
                [*command, "--mode", "modeless"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(explicit.returncode, 0, explicit.stderr)
            self.assertIn(
                "mode: modeless\n", packet_capture.read_text(encoding="utf-8")
            )


class ModelessSupervisorBudgetTests(unittest.TestCase):
    """bin/board-supervisor.sh: the extended launch budget is bounty-only."""

    def _budget_block(self) -> str:
        source = (ROOT / "bin" / "board-supervisor.sh").read_text(encoding="utf-8")
        anchor = 'authority["budgets"]'
        start = source.index(anchor)
        end = source.index("authenticated launch budget is invalid", start)
        # Executable lines only: a comment may legitimately quote the `!= project`
        # denylist anti-pattern it warns against, so the shape check must inspect
        # the CODE, not the prose around it.
        return "\n".join(
            line
            for line in source[start:end].splitlines()
            if not line.strip().startswith("#")
        )

    def test_extended_budget_is_allowlisted_to_bounty_not_denylisted_from_project(
        self,
    ) -> None:
        block = self._budget_block()
        # Anti-widening (launch timeout): project caps at 2700s, bounty may reach
        # 3600s. The intersection is 2700s. modeless gets 2700s because the
        # extension is gated on the exact `== "bounty"` token (an ALLOWLIST). A
        # `!= "project"` denylist would silently hand modeless the 3600s ceiling.
        self.assertIn('authority["mode_profile"] == "bounty"', block)
        self.assertNotIn('!= "project"', block)
        self.assertNotIn('!= \'project\'', block)
        # The base 2700s cap that modeless (and project) live under is present.
        self.assertIn("2700", block)


if __name__ == "__main__":
    unittest.main()
