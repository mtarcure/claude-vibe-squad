"""Blindness must survive forgetfulness.

After the dispatch default flipped from `cold` to `default` on 2026-08-17
(memory-loop spec §4), a bounty rediscovery packet that simply omits an
aperture would otherwise be silently contaminated: until that flip, an
omitted field *was* the protection, by accident.

The floor keys on the `_blind/` directory the dossier layout already uses
rather than on a packet field, because a path cannot drift from the
evidence layout the way a field drifts from author intent. It is applied
where the aperture is *resolved* -- once, at admission in
`build_context` -- so it reaches both the authenticated envelope the
broker enforces and the `reads_allowed` branch of the launch prompt,
without becoming a seventh site that encodes aperture policy.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))
# `unittest discover` puts this directory on sys.path, so the sibling test
# module is importable by plain name. It is imported for its repository
# fixture only: duplicating that 160-line builder here would be a second
# copy that ages independently (CLAUDE.md rule 10).
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import dispatch_context_builder as dcb  # noqa: E402
from dispatch_context_builder import enforce_blind_floor  # noqa: E402
# Imported as a MODULE, never `from ... import DispatchContextBuilderTests`:
# a TestCase subclass bound in this namespace is collected here as well, and
# `discover` would then run that whole 40-test suite a second time.
import test_dispatch_context_builder as tdcb  # noqa: E402

DISCOVERY_ROLE = "scout"
VERIFY_ROLE = "impact-validator"
RUNTIME_MAP = ROOT / "shared" / "specialist-runtime-map.tsv"


def _vault_with_blind(target: str) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "Chrono" / "dossiers" / target / "_blind").mkdir(parents=True)
    return root


def _brief(**fields: str) -> str:
    """A specialist brief carrying exactly the frontmatter fields given."""

    body = "".join(f"{key}: {value}\n" for key, value in fields.items())
    return f"---\n{body}---\n\n# brief\n"


def _brief_repo(briefs: dict[str, str]) -> Path:
    """A repo holding nothing but specialist briefs -- all the floor reads."""

    root = Path(tempfile.mkdtemp())
    directory = root / "departments" / "security" / "specialists"
    directory.mkdir(parents=True)
    for name, text in briefs.items():
        (directory / f"{name}.md").write_text(text, encoding="utf-8")
    return root


class BlindFloorTests(unittest.TestCase):
    def test_discovery_role_on_blind_target_is_forced_cold(self):
        root = _vault_with_blind("acme")
        self.assertEqual(
            enforce_blind_floor("default", "acme", DISCOVERY_ROLE, root), "cold"
        )

    def test_floor_overrides_an_explicit_rich_request(self):
        root = _vault_with_blind("acme")
        self.assertEqual(
            enforce_blind_floor("rich", "acme", DISCOVERY_ROLE, root), "cold"
        )

    def test_verification_role_is_not_floored(self):
        root = _vault_with_blind("acme")
        self.assertEqual(
            enforce_blind_floor("default", "acme", VERIFY_ROLE, root), "default"
        )

    def test_target_without_blind_path_is_not_floored(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(
            enforce_blind_floor("default", "acme", DISCOVERY_ROLE, root), "default"
        )

    def test_a_packet_that_declares_no_target_cannot_be_floored(self):
        # Documented residual: the floor is target-scoped, so it has nothing
        # to key on without one. It stays open rather than flooring every
        # discovery dispatch anywhere, which would make `scout` permanently
        # memory-blind on every unrelated engagement.
        root = _vault_with_blind("acme")
        self.assertEqual(
            enforce_blind_floor("default", "", DISCOVERY_ROLE, root), "default"
        )

    def test_absent_vault_root_leaves_the_aperture_alone(self):
        # An unset `CHRONO_VAULT_ROOT` is not a bypass: the controller then
        # projects no vault path to the worker at all (`clearance.
        # project_worker_vault_environment`), so recall has nothing to open
        # and there is no prior work to be contaminated by.
        self.assertEqual(
            enforce_blind_floor("default", "acme", DISCOVERY_ROLE, None), "default"
        )
        self.assertEqual(
            enforce_blind_floor("rich", "acme", DISCOVERY_ROLE, ""), "rich"
        )

    def test_a_blind_target_never_widens_an_already_blind_aperture(self):
        # `cold` and `pool_blind` already deny reads, and `none` denies
        # strictly more than `cold` does -- it forbids `record` too. Rewriting
        # any of them to `cold` would widen a packet that was already blinder
        # than the floor requires.
        root = _vault_with_blind("acme")
        for aperture in ("cold", "pool_blind", "none"):
            with self.subTest(aperture=aperture):
                self.assertEqual(
                    enforce_blind_floor(aperture, "acme", DISCOVERY_ROLE, root),
                    aperture,
                )

    def test_the_read_permitting_set_matches_the_policy_registry(self):
        # The floor and the launch prompt share one answer to "does this
        # aperture return notes?". The registry owns it.
        rows = (
            (ROOT / "shared" / "registries" / "memory-apertures.tsv")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        header = rows[0].split("\t")
        columns = {name: index for index, name in enumerate(header)}
        reading = set()
        for line in rows[1:]:
            if not line.strip():
                continue
            cells = line.split("\t")
            if cells[columns["recall"]] == "allow":
                self.assertEqual(cells[columns["get_note"]], "allow")
                reading.add(cells[columns["aperture"]])
        self.assertEqual(reading, set(dcb.READ_PERMITTING_APERTURES))


class FlooredRoleVocabularyTests(unittest.TestCase):
    """Pin the floored set against the real specialist roster.

    The set is now derived from the shipped briefs rather than declared in
    Python, so a role name cannot be typed wrong here -- but a brief could
    still be marked for a role that no longer routes, and a silently empty
    derivation would switch the floor off for everyone.
    """

    @classmethod
    def setUpClass(cls) -> None:
        rows = RUNTIME_MAP.read_text(encoding="utf-8").splitlines()
        cls.specialists = {line.split("\t", 1)[0] for line in rows[1:] if line.strip()}
        cls.floored = dcb.blind_discovery_roles()

    def test_every_floored_role_is_a_real_specialist(self):
        self.assertTrue(
            self.floored <= self.specialists,
            sorted(self.floored - self.specialists),
        )

    def test_later_stage_roles_are_real_and_deliberately_unfloored(self):
        # Absent by design (spec §5): a skeptic, impact-validator, or
        # technical-writer cannot do its job blind. Chrono opens their
        # aperture deliberately, with a reason recorded in the packet.
        later_stage = {"skeptic", "impact-validator", "technical-writer"}
        self.assertTrue(later_stage <= self.specialists)
        self.assertEqual(later_stage & self.floored, set())

    def test_the_shipped_briefs_actually_declare_a_floor(self):
        # A derivation that silently returned nothing would leave every
        # assertion above trivially true while the floor never fired.
        self.assertTrue(self.floored)

    def test_every_shipped_brief_parses(self):
        # An unparseable brief fails closed, which is safe but silent: the
        # role loses its memory and nothing says why. The pre-commit
        # validator is the loud half of this; this is the pin.
        declarations = dcb.blind_discovery_declarations()
        briefs = {
            path.stem
            for pattern in dcb._SPECIALIST_BRIEF_GLOBS
            for path in ROOT.glob(pattern)
        }
        self.assertEqual(briefs - set(declarations), set())


class BriefDerivedFloorTests(unittest.TestCase):
    """The floored set is read from the specialist briefs, not compiled in.

    Until 2026-08-17 this was a `frozenset` literal in
    `dispatch_context_builder`: a judgment about which roles must rediscover
    blind, encoded in Python, in a system CLAUDE.md opens by calling
    markdown-first. These tests are the property that replaced it -- marking
    a brief `blind_discovery: true` floors that role with no Python change,
    and unmarking one unfloors it.

    Every failure direction is deliberately asymmetric. A brief that cannot
    be read floors its role, because a contaminated rediscovery scout
    destroys the work it was dispatched to do, while a needlessly blinded
    role merely does that work with less context.
    """

    def setUp(self) -> None:
        self.vault = _vault_with_blind("acme")

    def _floor(self, role: str, repo: Path, aperture: str = "default") -> str:
        return enforce_blind_floor(
            aperture, "acme", role, self.vault, repo_root=repo
        )

    def test_marking_a_brief_floors_a_role_with_no_python_change(self):
        # `mystery-role` appears in no Python file anywhere. Its brief is the
        # only thing that says it must run blind.
        repo = _brief_repo(
            {"mystery-role": _brief(specialist="mystery-role", blind_discovery="true")}
        )
        self.assertEqual(self._floor("mystery-role", repo), "cold")

    def test_an_unmarked_brief_keeps_its_memory(self):
        repo = _brief_repo({"ordinary-role": _brief(specialist="ordinary-role")})
        self.assertEqual(self._floor("ordinary-role", repo), "default")

    def test_an_explicit_false_keeps_its_memory(self):
        repo = _brief_repo(
            {"ordinary-role": _brief(specialist="ordinary-role", blind_discovery="false")}
        )
        self.assertEqual(self._floor("ordinary-role", repo), "default")

    def test_unmarking_the_shipped_scout_brief_unfloors_it(self):
        # The other half of the property, and the one that proves the runtime
        # is genuinely reading the markdown rather than a hidden fallback:
        # take the real brief, delete the one line, and the floor lifts.
        shipped = ROOT / "departments" / "security" / "specialists" / "scout.md"
        original = shipped.read_text(encoding="utf-8")
        self.assertIn("blind_discovery: true\n", original)
        repo = _brief_repo(
            {"scout": original.replace("blind_discovery: true\n", "", 1)}
        )
        self.assertEqual(self._floor("scout", repo), "default")
        # ...and the untouched brief still floors, so the difference is the
        # marker and not the copying.
        self.assertEqual(self._floor("scout", _brief_repo({"scout": original})), "cold")

    def test_a_role_with_no_brief_at_all_is_floored(self):
        repo = _brief_repo({"someone-else": _brief(specialist="someone-else")})
        self.assertEqual(self._floor("absent-role", repo), "cold")

    def test_an_empty_repo_floors_every_role(self):
        # The failure that would otherwise be worst: no briefs found, so no
        # role is "known blind", so every rediscovery lane reads freely.
        empty = Path(tempfile.mkdtemp())
        for role in ("scout", "impact-validator", "anything-at-all"):
            with self.subTest(role=role):
                self.assertEqual(self._floor(role, empty), "cold")

    def test_an_unreadable_brief_is_floored_not_permitted(self):
        # A directory where a file belongs: `read_text` raises, and the
        # naive implementation of this feature treats the raise as "no
        # declaration found" and lets the scout read everything.
        repo = _brief_repo({})
        (repo / "departments" / "security" / "specialists" / "broken.md").mkdir()
        self.assertEqual(self._floor("broken", repo), "cold")

    def test_malformed_frontmatter_is_floored_not_permitted(self):
        cases = {
            "no-frontmatter": "# brief with no frontmatter at all\n",
            "unterminated": "---\nspecialist: unterminated\nblind_discovery: true\n",
            "not-a-boolean": _brief(specialist="not-a-boolean", blind_discovery="yes"),
            "empty-value": _brief(specialist="empty-value", blind_discovery=""),
            "list-value": _brief(specialist="list-value", blind_discovery="[true]"),
            "null-value": _brief(specialist="null-value", blind_discovery="null"),
            "duplicated": (
                "---\nspecialist: duplicated\nblind_discovery: true\n"
                "blind_discovery: false\n---\n\n# brief\n"
            ),
        }
        repo = _brief_repo(cases)
        for role in cases:
            with self.subTest(role=role):
                self.assertEqual(self._floor(role, repo), "cold")

    def test_a_malformed_brief_does_not_floor_its_neighbours(self):
        # Fail closed, but scoped: one broken brief must not blind the whole
        # roster, or a stray edit silently degrades every later-stage role.
        repo = _brief_repo(
            {
                "broken": "not frontmatter\n",
                "healthy": _brief(specialist="healthy"),
            }
        )
        self.assertEqual(self._floor("broken", repo), "cold")
        self.assertEqual(self._floor("healthy", repo), "default")

    def test_a_marked_brief_still_cannot_floor_an_unblinded_target(self):
        # Deriving the roster from markdown must not widen the floor: it is
        # still scoped to a target under active blind work.
        repo = _brief_repo(
            {"mystery-role": _brief(specialist="mystery-role", blind_discovery="true")}
        )
        self.assertEqual(
            enforce_blind_floor(
                "default", "", "mystery-role", self.vault, repo_root=repo
            ),
            "default",
        )
        self.assertEqual(
            enforce_blind_floor(
                "default", "acme", "mystery-role", None, repo_root=repo
            ),
            "default",
        )
        self.assertEqual(
            enforce_blind_floor(
                "none", "acme", "mystery-role", self.vault, repo_root=repo
            ),
            "none",
        )

    def test_shared_specialists_are_read_too(self):
        repo = Path(tempfile.mkdtemp())
        directory = repo / "shared" / "specialists"
        directory.mkdir(parents=True)
        (directory / "shared-role.md").write_text(
            _brief(specialist="shared-role", blind_discovery="true"), encoding="utf-8"
        )
        self.assertEqual(self._floor("shared-role", repo), "cold")


class BlindFloorAdmissionTests(unittest.TestCase):
    """The floor has to sit on the admission path, not on a caller's goodwill.

    Every assertion below fails if the `enforce_blind_floor` call is removed
    from `build_context`. Two of them check different consumers on purpose:
    the authenticated envelope the broker reads, and the launch prompt's
    `reads_allowed` branch, which is what the worker actually obeys.
    """

    def _context(self, *, aperture: str | None, target: str, specialist: str):
        directory = tempfile.mkdtemp()
        root, packet = tdcb.DispatchContextBuilderTests._fake_repo_for_lane(
            None, Path(directory), lane="codex", model="gpt-codex",
            specialist=specialist,
        )
        extra = f"target: {target}\n"
        if aperture is not None:
            extra += f"memory_aperture: {aperture}\n"
        if aperture == "focused":
            extra += "memory_focus: exact-prior-finding\n"
        packet.write_text(
            packet.read_text(encoding="utf-8").replace(
                "\n---\n\nWrite the result.", "\n" + extra + "---\n\nWrite the result."
            ),
            encoding="utf-8",
        )
        vault = _vault_with_blind("acme")
        with (
            mock.patch.dict(dcb.LANE_CLI_PATHS, {"codex": Path("/bin/sh")}, clear=True),
            mock.patch.dict(os.environ, {"CHRONO_VAULT_ROOT": str(vault)}),
        ):
            return dcb.build_context(
                root,
                packet,
                attempt_id="d-" + "7" * 32,
                generation=1,
                now=1_784_800_000,
                nonce="8" * 64,
            )

    def test_omitted_aperture_on_a_blind_target_is_floored_in_the_envelope(self):
        context = self._context(
            aperture=None, target="acme", specialist=DISCOVERY_ROLE
        )
        self.assertEqual(context["authority"]["memory_context"]["aperture"], "cold")

    def test_the_launch_prompt_forbids_recall_for_a_floored_dispatch(self):
        context = self._context(
            aperture=None, target="acme", specialist=DISCOVERY_ROLE
        )
        self.assertIn("Do not call recall or get_note", context["task_prompt"])
        self.assertNotIn("Recall prior context ONCE", context["task_prompt"])

    def test_an_explicit_rich_packet_is_floored_at_admission(self):
        context = self._context(
            aperture="rich", target="acme", specialist=DISCOVERY_ROLE
        )
        self.assertEqual(context["authority"]["memory_context"]["aperture"], "cold")

    def test_a_later_stage_role_on_the_same_blind_target_keeps_its_memory(self):
        context = self._context(
            aperture=None, target="acme", specialist=VERIFY_ROLE
        )
        self.assertEqual(context["authority"]["memory_context"]["aperture"], "default")
        self.assertIn("Recall prior context ONCE", context["task_prompt"])

    def test_a_discovery_role_on_an_unblinded_target_keeps_its_memory(self):
        context = self._context(
            aperture=None, target="not-under-blind-work", specialist=DISCOVERY_ROLE
        )
        self.assertEqual(context["authority"]["memory_context"]["aperture"], "default")

    def test_a_floored_focused_packet_drops_its_now_illegal_focus(self):
        # `focused` is the only aperture allowed to carry a focus, and the
        # supervisor refuses the mismatch (`clearance.validate_memory_context`).
        # Flooring without clearing the focus would produce a dead dispatch
        # rather than a blind one -- protection that destroys the work it
        # protects is not protection.
        context = self._context(
            aperture="focused", target="acme", specialist=DISCOVERY_ROLE
        )
        memory = context["authority"]["memory_context"]
        self.assertEqual(memory["aperture"], "cold")
        self.assertIsNone(memory["focus"])

    def test_the_live_target_convention_still_dispatches(self):
        """`target` predates this floor and is free text in practice.

        An earlier version refused anything that was not a bare slug, from
        `build_context` -- the single path `bin/send-task.sh` takes for
        every dispatch. These four mirror the SHAPES of real values from this repo's own
        archived packets and outbox envelopes -- each shape killed the
        dispatch. Identifiers are neutral fixtures: the public export scan
        refuses engagement targets and dated campaign paths by shape.
        """
        for live in (
            "examplechain/example-gateway-contracts"
            "@80f7a208bcd484601a86d55e5a3891727e7f0ef9",
            "shared/specialists/ (8 files)",
            "contracts/example-gateway @ 5a23518e934cae186c3929f5e5bb736e7e11b574",
            "workspace/example/repo @ 5a23518e934cae186c",
        ):
            with self.subTest(target=live):
                context = self._context(
                    aperture=None, target=live, specialist=DISCOVERY_ROLE
                )
                self.assertEqual(
                    context["authority"]["memory_context"]["aperture"], "default"
                )

    def test_a_blind_slug_inside_a_live_shaped_target_still_floors(self):
        """The floor must survive the field's actual vocabulary.

        Not refusing a non-slug target is only safe if a blind target that
        arrives inside one is still recognised. `acme` is the blinded
        dossier in this fixture; each value below carries it.
        """
        for shaped in (
            "acme",
            "Acme",
            "acme @ 0648551",
            "acme / example-chain-node @ 1111bbbb",
            "examplechain/acme@0000aaaa",
        ):
            with self.subTest(target=shaped):
                context = self._context(
                    aperture=None, target=shaped, specialist=DISCOVERY_ROLE
                )
                self.assertEqual(
                    context["authority"]["memory_context"]["aperture"], "cold"
                )

    def test_no_candidate_can_escape_the_dossiers_directory(self):
        # Every candidate matches IDENTIFIER_RE by construction, so a
        # traversal-shaped target yields path segments, never a traversal.
        for hostile in ("../../etc", "..", "a/../../b", "acme/_blind", "/etc/passwd"):
            with self.subTest(target=hostile):
                for slug in dcb._dossier_slug_candidates(hostile):
                    self.assertRegex(slug, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                    self.assertNotIn("/", slug)
                    self.assertNotIn(".", slug)

    def test_candidate_derivation_is_bounded(self):
        many = " ".join(f"seg{index}" for index in range(100))
        self.assertLessEqual(
            len(dcb._dossier_slug_candidates(many)),
            dcb.MAX_BLIND_TARGET_CANDIDATES,
        )
        self.assertEqual(dcb._dossier_slug_candidates(""), ())


if __name__ == "__main__":
    unittest.main()
