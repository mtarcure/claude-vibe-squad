#!/usr/bin/env python3
"""CC-04 regression coverage for task-frontmatter -> Python boundaries.

The real dispatcher runs only against an isolated ``VAULT_ROOT``.  Its board
supervisor is deliberately absent, so every fixture stops after active-registry
construction and no model CLI can launch.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shutil
# Fixed local test executable; no attacker-selected command or shell.
import subprocess  # nosec B404
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
SEND_TASK = REPO / "bin" / "send-task.sh"
LINKED_SUBTREES = ("shared", "model-lanes")
MAILBOXES = ("inbox", "active", "outbox", "archive")


def packet_bytes(fields: dict[str, str], body: str = "CC-04 fixture") -> bytes:
    rows = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"---\n{rows}\n---\n\n{body}\n".encode()


class SendTaskFrontmatterInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cc04-sendtask-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        for name in LINKED_SUBTREES:
            (self.vault / name).symlink_to(REPO / name)
        scripts = self.vault / "scripts"
        scripts.mkdir()
        for entry in (REPO / "scripts").iterdir():
            if entry.name != "python":
                (scripts / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
        python_dir = scripts / "python"
        python_dir.mkdir()
        for entry in (REPO / "scripts" / "python").iterdir():
            if entry.name != "host_admission.py":
                (python_dir / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
        (python_dir / "host_admission.py").write_text(
            "import json, sys\n"
            "args = sys.argv[1:]\n"
            "vector = args[args.index('--vector-sha256') + 1]\n"
            "print(json.dumps({'admitted': True, 'action': 'admit', "
            "'candidate_vector_sha256': vector}))\n",
            encoding="utf-8",
        )

        # Link every dispatcher helper except the board supervisor.  The missing
        # executable is a deterministic post-registration stop: the vulnerable
        # registry builder runs, but no child process or model CLI can launch.
        (self.vault / "bin").mkdir()
        for entry in (REPO / "bin").iterdir():
            if entry.name != "board-supervisor.sh":
                (self.vault / "bin" / entry.name).symlink_to(entry)

        state = self.vault / "_state"
        state.mkdir()
        # An existing registry makes non-empty scopes traverse the conflict
        # checker before they reach active-registry construction.
        (state / "active-tasks.json").write_text("{}\n", encoding="utf-8")
        for mailbox in MAILBOXES:
            (self.vault / "departments" / "coding" / mailbox).mkdir(parents=True)

    def fields(self, **overrides: str) -> dict[str, str]:
        # No `mode:` field means `modeless`, which derives a verification
        # contract like any other mode, so `run_id` is required to get past
        # admission and reach the frontmatter boundaries this suite is about.
        fields = {
            "id": "TASK-2026-07-27-0400-cc04fixture",
            "to_model": "claude",
            "specialist": "none",
            "source_namespace": "coding",
            "compatibility_namespace": "coding",
            "run_id": "CC04-FRONTMATTER-INJECTION",
            "parallel_safe": "true",
            "direct_lane_work_allowed": "true",
            "write_scope": "[_state/cc04/out.md]",
            "return_artifact": "_state/cc04/out.md",
        }
        fields.update(overrides)
        return fields

    def dispatch(self, content: bytes) -> subprocess.CompletedProcess[str]:
        task = self.root / "task.md"
        task.write_bytes(content)
        # Fixed argv to the local dispatcher; shell execution is disabled.
        return subprocess.run(  # nosec B603
            [str(SEND_TASK), str(task)],
            env={
                **os.environ,
                "VAULT_ROOT": str(self.vault),
                "SKIP_NUDGE": "1",
                "UV_CACHE_DIR": str(self.root / "uv-cache"),
                # self.vault is a plain directory, not a git checkout, so
                # send-task.sh cannot derive a branch and now refuses to guess
                # one -- correct for a real checkout in detached HEAD, but
                # irrelevant to what this fixture exercises. Supply it
                # explicitly rather than weakening the production guard.
                "SQUAD_BASE_BRANCH": "v2",
            },
            capture_output=True,
            text=True,
            timeout=180,
        )

    def output(self, completed: subprocess.CompletedProcess[str]) -> str:
        return completed.stdout + completed.stderr

    def registry_entry(self, task_id: str) -> dict:
        registry = json.loads(
            (self.vault / "_state" / "active-tasks.json").read_text(encoding="utf-8")
        )
        self.assertIn(task_id, registry)
        return registry[task_id]

    def test_old_closing_triple_quote_scope_payload_is_rejected_as_data(self) -> None:
        marker = self.root / "scope-code-executed"
        payload = (
            '[]"""; __import__("pathlib").Path("'
            f"{marker}"
            '").write_text("owned"); scope_raw = """[`ticks`$()]'
        )

        # This is not merely suspicious text: splicing it into the old
        # ``scope_raw = triple-quoted packet value`` statement produces a real
        # top-level __import__ call in the Python AST.
        old_source = f'scope_raw = """{payload}"""\n'
        old_tree = ast.parse(old_source)
        self.assertTrue(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                for node in ast.walk(old_tree)
            ),
            msg=old_source,
        )

        completed = self.dispatch(packet_bytes(self.fields(write_scope=payload)))
        output = self.output(completed)
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("invalid write_scope", output)
        self.assertFalse(marker.exists(), msg=output)

    def test_other_frontmatter_metacharacters_remain_registry_data(self) -> None:
        marker = self.root / "metadata-code-executed"
        payload = (
            'true", "injected": __import__("pathlib").Path("'
            f"{marker}"
            '").write_text("owned"), "tail": "`ticks`$()'
        )
        old_source = f'entry = {{"parallel_safe": "{payload}"}}\n'
        old_tree = ast.parse(old_source)
        self.assertTrue(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                for node in ast.walk(old_tree)
            ),
            msg=old_source,
        )

        fields = self.fields(parallel_safe=payload)
        completed = self.dispatch(packet_bytes(fields))
        output = self.output(completed)
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("write_scope: no conflicts", output)
        self.assertIn("missing board supervisor", output)
        self.assertFalse(marker.exists(), msg=output)
        entry = self.registry_entry(fields["id"])
        self.assertEqual(entry["parallel_safe"], payload)

    def test_multiline_frontmatter_values_are_rejected_before_use(self) -> None:
        marker = self.root / "newline-code-executed"
        multiline_scope = (
            "[_state/cc04/,\n"
            f'  __import__("pathlib").Path("{marker}").write_text("owned")]'
        )
        completed = self.dispatch(
            packet_bytes(self.fields(write_scope=multiline_scope))
        )
        output = self.output(completed)
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("must be one top-level key/value pair", output)
        self.assertFalse(marker.exists(), msg=output)

    def test_nul_bytes_in_scope_or_other_fields_are_rejected_from_raw_bytes(self) -> None:
        for field_name in ("write_scope", "parallel_safe"):
            with self.subTest(field=field_name):
                marker = self.root / f"nul-{field_name}-code-executed"
                fields = self.fields()
                fields[field_name] = (
                    f'prefix\0__import__("pathlib").Path("{marker}")'
                    '.write_text("owned")'
                )
                completed = self.dispatch(packet_bytes(fields))
                output = self.output(completed)
                self.assertNotEqual(completed.returncode, 0, msg=output)
                self.assertIn("contains a NUL byte", output)
                self.assertFalse(marker.exists(), msg=output)

    def test_memory_aperture_contract_rejects_before_registration(self) -> None:
        cases = (
            ({"memory_aperture": "wide-open"}, "invalid memory_aperture"),
            ({"memory_aperture": "focused"}, "focused memory requires"),
            (
                {"memory_aperture": "cold", "memory_focus": "campaign-a"},
                "memory_focus is valid only",
            ),
        )
        for index, (overrides, expected) in enumerate(cases):
            with self.subTest(overrides=overrides):
                task_id = f"TASK-2026-07-27-041{index}-memoryfixture"
                completed = self.dispatch(
                    packet_bytes(self.fields(id=task_id, **overrides))
                )
                output = self.output(completed)
                self.assertNotEqual(completed.returncode, 0, msg=output)
                self.assertIn(expected, output)
                registry = json.loads(
                    (self.vault / "_state" / "active-tasks.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertNotIn(task_id, registry)

    def test_every_python_heredoc_is_literal_and_packet_is_snapshotted_once(self) -> None:
        source = SEND_TASK.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"python3?[^\n]*<<PY[A-Z_]*")
        self.assertNotIn('scope_raw = """${WRITE_SCOPE_RAW}"""', source)
        self.assertEqual(source.count('parse_task_frontmatter "$TASK_FILE"'), 1)
        self.assertNotRegex(
            source,
            r'frontmatter_(?:field|has_field) "\$TASK_FILE"',
        )

        python_bodies = re.findall(
            r"<<'PYEOF'\n(.*?)\nPYEOF",
            source,
            flags=re.DOTALL,
        )
        self.assertGreaterEqual(len(python_bodies), 10)
        for body in python_bodies:
            self.assertNotRegex(body, r"\$\{[A-Z_][A-Z0-9_]*\}")
            self.assertNotIn("$(", body)


if __name__ == "__main__":
    unittest.main()
