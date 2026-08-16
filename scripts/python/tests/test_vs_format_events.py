#!/usr/bin/env python3
"""Tests for bin/vs-format-events.py — the board spawn transcript viewer.

RED→GREEN: the Claude Agent SDK stream-json schema (`assistant`/`user` lines
carrying a `message.content` list of blocks) rendered blank before this fix,
because emit() only understood the Codex/Gemini flat "item" schema. These tests
pin both schemas so the Claude path renders and the Codex/Gemini path never
regresses.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
FORMATTER = ROOT / "bin" / "vs-format-events.py"


def run_formatter(lines: list[str]) -> str:
    """Feed newline-joined log lines on stdin, return rendered stdout."""
    proc = subprocess.run(
        [sys.executable, str(FORMATTER)],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"formatter exited {proc.returncode}: {proc.stderr}"
    return proc.stdout


class ClaudeStreamJsonSchema(unittest.TestCase):
    """The Claude Agent SDK schema must render (was blank before the fix)."""

    def test_assistant_text_tool_use_and_tool_result_render(self):
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "planning the read"},
                    {"type": "text", "text": "Reading the target file now."},
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": "ls -la /tmp/widgets"}},
                ]},
            }),
            json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Read",
                     "input": {"file_path": "/repo/bin/vs-format-events.py"}},
                ]},
            }),
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "tool_result",
                     "content": [{"type": "text", "text": "total 8\ndrwxr-xr-x"}]},
                ]},
            }),
        ]
        out = run_formatter(lines)
        self.assertTrue(out.strip(), "Claude stream-json rendered BLANK (the bug)")
        # Agent message text is surfaced.
        self.assertIn("Reading the target file now.", out)
        # Tool calls surface the tool name and the command / file_path hint.
        self.assertIn("Bash", out)
        self.assertIn("ls -la /tmp/widgets", out)
        self.assertIn("Read", out)
        self.assertIn("/repo/bin/vs-format-events.py", out)
        # Tool result content is surfaced (first line).
        self.assertIn("total 8", out)

    def test_tool_result_string_content_renders(self):
        # tool_result.content is polymorphic: bare string OR list of text blocks.
        lines = [json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "single string result body"},
            ]},
        })]
        out = run_formatter(lines)
        self.assertIn("single string result body", out)

    def test_empty_thinking_block_is_skipped(self):
        # Real logs carry many empty thinking blocks (signature-only); skip them.
        lines = [json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "", "signature": "abc"},
            ]},
        })]
        out = run_formatter(lines)
        self.assertEqual(out.strip(), "")

    def test_tool_use_falls_back_to_first_input_value(self):
        # No file_path/command/path → use the first input value as the hint.
        lines = [json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Grep",
                 "input": {"pattern": "needle-in-haystack"}},
            ]},
        })]
        out = run_formatter(lines)
        self.assertIn("Grep", out)
        self.assertIn("needle-in-haystack", out)

    def test_claude_noise_lines_do_not_crash_and_are_skipped(self):
        # system/thinking_tokens, rate_limit_event, fallback blocks are noise.
        lines = [
            json.dumps({"type": "system", "subtype": "thinking_tokens",
                        "estimated_tokens": 50}),
            json.dumps({"type": "rate_limit_event",
                        "rate_limit_info": {"status": "allowed"}}),
            json.dumps({"type": "assistant", "message": {"role": "assistant",
                        "content": [{"type": "fallback",
                                     "from": {"model": "claude-fable-5"}}]}}),
        ]
        out = run_formatter(lines)  # must not raise / non-zero exit
        self.assertEqual(out.strip(), "")

    def test_malformed_claude_block_does_not_crash(self):
        # A content list holding a non-dict block must not kill the viewer.
        lines = [json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": ["oops-not-a-dict", 42]},
        })]
        out = run_formatter(lines)  # returncode==0 asserted in run_formatter
        self.assertEqual(out.strip(), "")


class CodexGeminiItemSchema(unittest.TestCase):
    """Regression guard: the existing flat item schema must still render."""

    def test_item_schema_still_renders(self):
        lines = [
            json.dumps({"type": "thread.started"}),
            json.dumps({"type": "item.completed",
                        "item": {"type": "agent_message",
                                 "text": "Done with the analysis."}}),
            json.dumps({"type": "item.completed",
                        "item": {"type": "command_execution",
                                 "command": "pytest -q"}}),
            json.dumps({"type": "item.completed",
                        "item": {"type": "file_change",
                                 "path": "src/main.rs"}}),
            json.dumps({"type": "turn.completed",
                        "usage": {"input_tokens": 10, "output_tokens": 20}}),
        ]
        out = run_formatter(lines)
        self.assertIn("session started", out)
        self.assertIn("Done with the analysis.", out)
        self.assertIn("pytest -q", out)
        self.assertIn("src/main.rs", out)

    def test_plain_text_passthrough_preserved(self):
        out = run_formatter(["just a plain human line"])
        self.assertIn("just a plain human line", out)

    def test_kimi_role_schema_renders_tool_calls(self):
        """Kimi emits no `type` key at all -- role/content/tool_calls instead.

        Before this branch existed the formatter dispatched purely on `type`, so
        a kimi lane rendered as blank while running dozens of calls (44 measured
        on a live lane). `content` and `tool_calls` arrive as Python reprs, not
        JSON, which is why literal_eval is in the path.
        """
        lines = [
            json.dumps({
                "role": "assistant",
                "content": "[{'type': 'think', 'think': 'Parsing the task now'}]",
                "tool_calls": "[{'type': 'function', 'id': 'x1', 'function':"
                              " {'name': 'Shell', 'arguments':"
                              ' \'{"command": "pwd && ls -la"}\'}}]',
            }),
            json.dumps({"role": "tool", "tool_call_id": "x1",
                        "content": "total 8\ndrwxr-xr-x"}),
        ]
        out = run_formatter(lines)
        self.assertIn("Parsing the task now", out)
        self.assertIn("Shell", out)
        self.assertIn("pwd && ls -la", out)
        self.assertIn("total 8", out)

    def test_kimi_truncated_arguments_still_render(self):
        """Kimi truncates long argument strings in the log.

        26 of 48 calls on a measured lane carried unparseable JSON such as
        '{"command": "ls -'. Every call id appears exactly once, so these are
        distinct calls rather than partial duplicates -- dropping them would lose
        more than half the transcript. The hint is salvaged and marked lossy.
        """
        line = json.dumps({
            "role": "assistant",
            "tool_calls": "[{'type': 'function', 'id': 'x2', 'function':"
                          " {'name': 'Shell', 'arguments':"
                          ' \'{"command": "ls -\'}}]',
        })
        out = run_formatter([line])
        self.assertIn("Shell", out)
        self.assertIn("ls -", out)
        self.assertNotIn('{"command"', out)  # raw JSON must not leak to the viewer


if __name__ == "__main__":
    unittest.main()
