"""A published file must not link to a path the export strips.

README.md linked to `docs/standards/settlement-guard-coverage.md` and to
`docs/probes/`. Both are denied by tools/export/policy/path-policy.json, and
`docs/probes/` held exactly one tracked file -- the denied one -- so the
directory would not exist at all in the public repository. Every stranger who
cloned it hit two dead links, one of them in the paragraph offering evidence for
a claim the README makes about itself.

Nothing caught it. The projector classifies paths and the content scanner reads
file bodies, but neither reads a Markdown link and asks whether its target
survives publication. This gate does, using the same policy module the projector
uses, so the two can never disagree about what is public.

The rule: for a link target inside the repository, at least one tracked file at
or under it must classify public. A directory whose every tracked file is denied
is a dead link, not a private link.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "export"))

from path_policy import load_policy  # noqa: E402

POLICY = ROOT / "tools" / "export" / "policy" / "path-policy.json"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True, check=True,
    ).stdout
    return {p.decode() for p in out.split(b"\0") if p}


class PublicExportLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy(POLICY)
        cls.tracked = _tracked()
        cls.public_docs = sorted(
            p for p in cls.tracked
            if p.endswith(".md") and cls.policy.classify(p) == "public"
        )

    def _dead_links(self, document: str) -> list[tuple[str, str]]:
        """Link targets under this repo whose every tracked file is denied."""
        dead: list[tuple[str, str]] = []
        text = (ROOT / document).read_text(encoding="utf-8", errors="replace")
        for raw in sorted(set(LINK.findall(text))):
            target = raw.split("#", 1)[0].rstrip("/")
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            # Resolve relative to the linking document's directory.
            base = Path(document).parent
            resolved = str((base / target).as_posix()).replace("./", "")
            under = [
                p for p in self.tracked
                if p == resolved or p.startswith(resolved + "/")
            ]
            if not under:
                continue  # untracked target -- a different problem, not this gate's
            if all(self.policy.classify(p) != "public" for p in under):
                dead.append((raw, f"{len(under)} tracked file(s), none public"))
        return dead

    def test_the_scan_actually_reaches_the_documents(self) -> None:
        """Negative control: a gate that scans nothing passes trivially."""
        self.assertIn("README.md", self.public_docs)
        self.assertGreater(
            len(self.public_docs), 10,
            f"only {len(self.public_docs)} public documents found -- the policy "
            "or the tracked-file listing is not being read correctly",
        )
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertGreater(
            len(set(LINK.findall(text))), 10,
            "no links parsed out of README.md -- the link regex is not matching",
        )

    def test_the_policy_really_denies_something(self) -> None:
        """Negative control: prove classify() can return non-public at all."""
        self.assertNotEqual(
            self.policy.classify("docs/standards/settlement-guard-coverage.md"),
            "public",
            "the export policy no longer denies the guard census; if that is "
            "deliberate, this control needs a different denied path",
        )

    def test_no_published_document_links_to_a_stripped_path(self) -> None:
        failures = {
            document: dead
            for document in self.public_docs
            if (dead := self._dead_links(document))
        }
        self.assertEqual(
            failures, {},
            "these links are dead in the public repository -- the target is "
            "stripped by tools/export/policy/path-policy.json:\n"
            + "\n".join(
                f"  {doc}: {target} ({why})"
                for doc, items in failures.items()
                for target, why in items
            ),
        )


if __name__ == "__main__":
    unittest.main()
