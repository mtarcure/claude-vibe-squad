"""The response envelope has two parsers. This pins them to one contract.

`bin/outbox-watcher.sh::frontmatter_field` reads the envelope after promotion;
`dispatch_context_builder._parse_response_envelope` reads it before. A shape one
accepts and the other rejects is a silent inconsistency, and a rejection message
that names no key is unactionable -- a worker cannot repair output it is only
told is "invalid".

Two classes here:

* diagnostics -- the pre-promotion parser must name the offending key and line.
* parity -- the shipped awk program and the Python parser must agree on which
  shapes are malformed, and must say the same sentence about them.

The parity class drives the REAL awk program, extracted from the shipped
watcher, rather than a transcription of it: a transcription would agree with
itself forever.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402


WATCHER = ROOT / "bin" / "outbox-watcher.sh"

# Line 1 is the opening fence, so the first key sits on line 2. Every fixture
# below states its own line numbers in the expected message; they are counted
# against these rows.
BASE_ROWS = [
    "id: TASK-0590-response",
    "in_response_to: TASK-0590",
    "from: claude",
    "to: chrono",
    "type: RESULT",
]


def _envelope(rows: list[str], *, summary: str = "finished work.") -> str:
    return "---\n" + "\n".join(rows) + f"\n---\n\n{summary}\n"


def _extract_frontmatter_field() -> str:
    """Lift the shipped `frontmatter_field` definition out of the watcher.

    Anchored on a column-0 opening line and a column-0 closing brace. If the
    function is renamed or reshaped this raises rather than silently testing an
    empty program, which is the failure mode that would make this whole class
    vacuous.
    """

    text = WATCHER.read_text(encoding="utf-8")
    opener = "\nfrontmatter_field() {\n"
    start = text.find(opener)
    if start < 0:
        raise AssertionError(
            f"{WATCHER}: no column-0 `frontmatter_field() {{` definition found; "
            "the parity harness cannot drive the shipped parser"
        )
    end = text.find("\n}\n", start + len(opener))
    if end < 0:
        raise AssertionError(f"{WATCHER}: `frontmatter_field` has no column-0 close")
    block = text[start + 1 : end + 3]
    if "flat scalar values are required" not in block:
        raise AssertionError(
            f"{WATCHER}: extracted `frontmatter_field` carries no flat-scalar "
            "diagnostics; extraction is wrong or the parser regressed"
        )
    return block


class EnvelopeDiagnosticTests(unittest.TestCase):
    """The pre-promotion parser must say what is wrong, not merely that it is."""

    def _reject(self, text: str) -> str:
        with self.assertRaises(dcb.DispatchContextError) as caught:
            dcb._parse_response_envelope(text.encode("utf-8"))
        return str(caught.exception)

    def test_nested_mapping_names_the_key_and_both_lines(self) -> None:
        # This is the exact shape that destroyed a 33,636-byte deliverable on
        # 2026-08-11: a lane emitted `reviews:` as a nested mapping.
        message = self._reject(
            _envelope(
                BASE_ROWS
                + [
                    "status: complete",
                    "reviews:",
                    "  reviewer: approve",
                    "return_artifact: result.md",
                ]
            )
        )

        self.assertIn("'reviews'", message)
        self.assertIn("at line 8", message)
        self.assertIn("nested content at line 9", message)
        self.assertIn("flat scalar values are required", message)

    def test_duplicate_key_names_both_declarations(self) -> None:
        message = self._reject(
            _envelope(
                BASE_ROWS
                + [
                    "status: complete",
                    "status: blocked",
                    "return_artifact: result.md",
                ]
            )
        )

        self.assertIn("'status' is duplicated at line 8", message)
        self.assertIn("first declared at line 7", message)

    def test_colon_bearing_scalar_is_preserved_not_rejected(self) -> None:
        fields, summary = dcb._parse_response_envelope(
            _envelope(
                BASE_ROWS
                + [
                    "note: status: blocked: still scalar",
                    "status: complete",
                    "return_artifact: result.md",
                ]
            ).encode("utf-8")
        )

        self.assertEqual(fields["note"], "status: blocked: still scalar")
        self.assertEqual(fields["status"], "complete")
        self.assertEqual(summary, "finished work.")

    def test_stray_indented_line_names_its_line(self) -> None:
        message = self._reject(
            _envelope(
                BASE_ROWS
                + [
                    "status: complete",
                    "  orphaned: indent",
                    "return_artifact: result.md",
                ]
            )
        )

        self.assertIn("line 8 is indented", message)
        self.assertIn("top-level flat scalar key/value pairs are required", message)

    def test_row_without_a_separator_names_its_line(self) -> None:
        message = self._reject(
            _envelope(BASE_ROWS + ["status complete", "return_artifact: result.md"])
        )

        self.assertIn("line 7 is not a top-level key/value pair", message)
        self.assertIn("flat scalar values are required", message)

    def test_unclosed_frontmatter_says_so(self) -> None:
        # No closing fence at all, so every row is frontmatter and the file ends
        # mid-block. A body line here would be rejected as a non-pair row first
        # -- which is correct, and is why this fixture carries only key rows.
        message = self._reject("---\nid: TASK-0590-response\nstatus: complete\n")

        self.assertIn("frontmatter is unclosed", message)
        self.assertIn("an exact --- delimiter is required", message)

    def test_blank_and_comment_rows_are_tolerated(self) -> None:
        # The watcher skips both, and `_parse_task_text` already skips both.
        # Rejecting them here would strand a finished run on whitespace.
        fields, _ = dcb._parse_response_envelope(
            _envelope(
                BASE_ROWS
                + [
                    "",
                    "# a worker comment",
                    "status: complete",
                    "return_artifact: result.md",
                ]
            ).encode("utf-8")
        )

        self.assertEqual(fields["status"], "complete")


class WatcherParityTests(unittest.TestCase):
    """Both parsers must call the same shapes malformed, in the same words."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.driver_dir = tempfile.TemporaryDirectory(prefix="envelope-parity-")
        driver = Path(cls.driver_dir.name) / "frontmatter-field.sh"
        driver.write_text(
            "#!/bin/bash\n" + _extract_frontmatter_field() + '\nfrontmatter_field "$1" status\n',
            encoding="utf-8",
        )
        cls.driver = driver

    @classmethod
    def tearDownClass(cls) -> None:
        cls.driver_dir.cleanup()

    def _watcher(self, text: str) -> tuple[bool, str]:
        """Return (accepted, stderr) from the shipped awk parser."""

        with tempfile.TemporaryDirectory(prefix="envelope-parity-case-") as tmp:
            target = Path(tmp) / "envelope.md"
            target.write_text(text, encoding="utf-8")
            result = subprocess.run(
                ["bash", str(self.driver), str(target)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        return result.returncode == 0, result.stderr

    def _python(self, text: str) -> tuple[bool, str]:
        try:
            dcb._parse_response_envelope(text.encode("utf-8"))
        except dcb.DispatchContextError as exc:
            return False, str(exc)
        return True, ""

    def test_extraction_drives_the_shipped_parser(self) -> None:
        accepted, stderr = self._watcher(
            _envelope(BASE_ROWS + ["status: complete", "return_artifact: result.md"])
        )

        self.assertTrue(accepted, stderr)

    def test_both_parsers_agree_on_every_shape(self) -> None:
        cases: list[tuple[str, str, bool]] = [
            (
                "flat envelope",
                _envelope(BASE_ROWS + ["status: complete", "return_artifact: r.md"]),
                True,
            ),
            (
                "colon-bearing scalar",
                _envelope(
                    BASE_ROWS
                    + ["note: status: blocked: still scalar", "status: complete"]
                ),
                True,
            ),
            (
                "blank and comment rows",
                _envelope(BASE_ROWS + ["", "# comment", "status: complete"]),
                True,
            ),
            (
                "capitalised and hyphenated keys",
                _envelope(BASE_ROWS + ["Reviewed-By: codex", "status: complete"]),
                True,
            ),
            (
                # awk splits records on \n alone. `str.splitlines` also splits on
                # \v, \f, \x1c-\x1e, \x85 and the Unicode separators, which would
                # shift every line number after this row in one parser only.
                "vertical tab inside a scalar",
                _envelope(BASE_ROWS + ["status: comp\x0blete"]),
                True,
            ),
            (
                # KNOWN LIMIT, pinned so it cannot drift into a disagreement:
                # neither parser rejects nesting expressed inline. The contract
                # is enforced against indentation, not against YAML flow syntax.
                "inline flow mapping",
                _envelope(BASE_ROWS + ["reviews: {reviewer: approve}", "status: ok"]),
                True,
            ),
            (
                "CRLF line endings",
                _envelope(BASE_ROWS + ["status: complete"]).replace("\n", "\r\n"),
                False,
            ),
            (
                "nested mapping",
                _envelope(
                    BASE_ROWS + ["status: complete", "reviews:", "  reviewer: approve"]
                ),
                False,
            ),
            (
                "duplicate key",
                _envelope(BASE_ROWS + ["status: complete", "status: blocked"]),
                False,
            ),
            (
                "stray indent",
                _envelope(BASE_ROWS + ["status: complete", "  orphaned: indent"]),
                False,
            ),
            (
                "row without a separator",
                _envelope(BASE_ROWS + ["status complete"]),
                False,
            ),
            (
                "unclosed frontmatter",
                "---\nid: TASK-0590-response\nstatus: complete\n",
                False,
            ),
            (
                "body after a missing closing fence",
                "---\nstatus: complete\n\nfinished work.\n",
                False,
            ),
            (
                "missing opening fence",
                "status: complete\n---\n\nfinished work.\n",
                False,
            ),
        ]

        for label, text, expected in cases:
            with self.subTest(case=label):
                watcher_ok, watcher_error = self._watcher(text)
                python_ok, python_error = self._python(text)
                self.assertEqual(
                    watcher_ok,
                    python_ok,
                    f"{label}: watcher accepted={watcher_ok} "
                    f"({watcher_error.strip()}), python accepted={python_ok} "
                    f"({python_error})",
                )
                self.assertEqual(watcher_ok, expected, f"{label}: {watcher_error}")

    def test_both_parsers_say_the_same_sentence(self) -> None:
        cases = [
            (
                _envelope(
                    BASE_ROWS
                    + ["status: complete", "reviews:", "  reviewer: approve"]
                ),
                "frontmatter key 'reviews' at line 8 has nested content at line 9; "
                "flat scalar values are required",
            ),
            (
                _envelope(BASE_ROWS + ["status: complete", "status: blocked"]),
                "frontmatter key 'status' is duplicated at line 8 (first declared "
                "at line 7); one flat scalar per key is required",
            ),
            (
                _envelope(BASE_ROWS + ["status: complete", "  orphaned: indent"]),
                "frontmatter line 8 is indented; top-level flat scalar key/value "
                "pairs are required",
            ),
            (
                _envelope(BASE_ROWS + ["status complete"]),
                "frontmatter line 7 is not a top-level key/value pair; flat "
                "scalar values are required",
            ),
            (
                "---\nid: TASK-0590-response\nstatus: complete\n",
                "frontmatter is unclosed; an exact --- delimiter is required",
            ),
            (
                "status: complete\n---\n\nfinished work.\n",
                "frontmatter must begin with an exact --- delimiter at line 1",
            ),
        ]

        for text, sentence in cases:
            with self.subTest(sentence=sentence):
                _, watcher_error = self._watcher(text)
                _, python_error = self._python(text)
                self.assertIn(sentence, watcher_error)
                self.assertIn(sentence, python_error)


if __name__ == "__main__":
    unittest.main()
