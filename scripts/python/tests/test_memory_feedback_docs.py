"""The apply-feedback rule has one home, and the copies must point at it.

Between 2026-07-25 and 2026-08-17, `shared/protocol.md` and `chrono/CLAUDE.md`
both described `record_usage` as an "available, opt-in tool" while the prompt
every dispatched worker actually received said *"Do not call record_usage or
set_status."* Nothing compared the two, so the contradiction survived 23 days
and every usage row in them.

CLAUDE.md hard rule 10: a duplicate is legitimate only when a validator
enforces the identity and a named file states the winner. `shared/protocol.md`
§ Memory Apply Citations is the named winner; this is the validator. It
deliberately checks agreement in *direction* — expected vs forbidden — rather
than pinning prose, so the documents stay editable but cannot drift back into
contradicting the enforced prompt.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402

ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])
sys.path.insert(0, str(ROOT / "scripts" / "python"))
from dispatch_context_builder import assemble_trusted_launch_prompt  # noqa: E402

PROTOCOL = ROOT / "shared" / "protocol.md"
CONTROLLER = ROOT / "chrono" / "CLAUDE.md"
PLUGIN_README = ROOT / "plugins" / "chrono-vault" / "README.md"
COPIES = (CONTROLLER, PLUGIN_README)


class MemoryApplyFeedbackDocsTests(unittest.TestCase):
    def test_protocol_is_the_named_home_and_the_copies_point_at_it(self) -> None:
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("Memory Apply Citations", protocol)
        self.assertIn("home of the apply-feedback rule", protocol)
        for path in COPIES:
            with self.subTest(path=path.name):
                self.assertIn(
                    "shared/protocol.md",
                    path.read_text(encoding="utf-8"),
                    f"{path} restates the apply-feedback rule without citing its home",
                )

    def test_no_document_still_calls_record_usage_opt_in(self) -> None:
        """The exact wording that contradicted the prompt for 23 days.

        Block quotes are exempt: `protocol.md` quotes the old wording in a `>`
        note recording what went wrong, and a document must be able to say what
        it used to say without that reading as a live claim.
        """
        for path in (PROTOCOL, *COPIES):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if line.lstrip().startswith(">"):
                        continue
                    if "record_usage" in line and "opt-in" in line:
                        self.fail(f"{path} still calls record_usage opt-in: {line}")

    def test_documents_and_the_enforced_prompt_agree_that_usage_is_expected(
        self,
    ) -> None:
        """Direction, not prose: docs and prompt must not disagree again.

        The prompt is the artifact that actually reaches a worker, so it is the
        side that decides who is lying when these two diverge.
        """
        prompt = assemble_trusted_launch_prompt(
            "packet body",
            task_id="TASK-2026-08-17-0001-docs",
            attempt_id="d-" + "0" * 32,
            generation=1,
            memory_aperture="rich",
        )
        self.assertNotIn("Do not call record_usage", prompt)
        self.assertIn("record_usage(recall_id=", prompt)
        for path in (PROTOCOL, *COPIES):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("record_usage", text)
                self.assertIn("expected", text)

    def test_documents_still_say_feedback_never_gates_settlement(self) -> None:
        """Expected is not gating, and that distinction is why the emergency
        prohibition landed in the first place: a memory call that could block a
        task took the whole task down with it."""
        for path in (PROTOCOL, CONTROLLER):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8").lower()
                self.assertTrue(
                    "never a settlement gate" in text or "never a gate" in text,
                    f"{path} no longer says apply-feedback cannot gate settlement",
                )


if __name__ == "__main__":
    unittest.main()
