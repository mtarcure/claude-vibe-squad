#!/usr/bin/env python3
"""Provider-adapter secret non-observability tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from broker_adapters import build_adapter, materialize_adapter  # noqa: E402
from launch_hygiene import build_task_environment  # noqa: E402


OPAQUE_HANDLE = "cb1.opaque-handle.mac"
PROVIDER_SECRET = "real-provider-secret-must-never-appear"


class AdapterTests(unittest.TestCase):
    def test_claude_kimi_and_codex_configs_contain_only_broker_capability(self) -> None:
        for lane in ("claude", "kimi", "codex"):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                home = root / "home"
                home.mkdir()
                bundle = build_adapter(
                    lane=lane,
                    broker_url="http://127.0.0.1:43210",
                    opaque_handle=OPAQUE_HANDLE,
                    task_home=home,
                    executable=Path("/usr/bin/printenv"),
                )
                serialized = json.dumps(
                    {
                        "env": bundle.base_environment,
                        "files": {str(path): content for path, content in bundle.files.items()},
                        "argv": bundle.argv,
                    },
                    sort_keys=True,
                )
                self.assertIn(OPAQUE_HANDLE, serialized)
                self.assertIn("127.0.0.1:43210", serialized)
                self.assertNotIn(PROVIDER_SECRET, serialized)
                self.assertNotIn("https://", serialized)
                self.assertNotIn(OPAQUE_HANDLE, json.dumps(bundle.argv))

    def test_materialized_wrapper_produces_broker_only_model_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            base = build_task_environment(root)
            bundle = build_adapter(
                lane="claude",
                broker_url="http://127.0.0.1:43210",
                opaque_handle=OPAQUE_HANDLE,
                task_home=Path(base["HOME"]),
                executable=Path("/usr/bin/env"),
            )
            materialize_adapter(bundle)
            completed = subprocess.run(
                list(bundle.argv),
                env=base,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                close_fds=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            observed = dict(
                line.split("=", 1)
                for line in completed.stdout.splitlines()
                if "=" in line
            )
            self.assertEqual(observed["ANTHROPIC_BASE_URL"], "http://127.0.0.1:43210/v1/model/claude")
            self.assertEqual(observed["ANTHROPIC_API_KEY"], OPAQUE_HANDLE)
            self.assertNotIn(PROVIDER_SECRET, completed.stdout)
            self.assertNotIn("HTTPS_PROXY", observed)
            self.assertNotIn("SSH_AUTH_SOCK", observed)

    def test_adapter_rejects_non_loopback_url_handle_injection_and_symlink_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            home.mkdir()
            with self.assertRaisesRegex(ValueError, "loopback"):
                build_adapter("claude", "https://provider.example", OPAQUE_HANDLE, home, Path("/bin/true"))
            with self.assertRaisesRegex(ValueError, "handle"):
                build_adapter("claude", "http://127.0.0.1:1", "bad\nhandle", home, Path("/bin/true"))

            bundle = build_adapter("codex", "http://127.0.0.1:1", OPAQUE_HANDLE, home, Path("/bin/true"))
            first_path = next(iter(bundle.files))
            first_path.parent.mkdir(parents=True, exist_ok=True)
            first_path.symlink_to(root / "escape")
            with self.assertRaisesRegex(RuntimeError, "symlink|exclusive"):
                materialize_adapter(bundle)

    def test_worker_observation_surface_has_no_raw_provider_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            base = build_task_environment(root)
            home = Path(base["HOME"])
            bundle = build_adapter(
                "kimi", "http://127.0.0.1:43210", OPAQUE_HANDLE, home, Path(sys.executable)
            )
            materialize_adapter(bundle)
            probe = (
                "import json,os,sys; "
                "fds=[]; "
                "[(fds.append(os.readlink('/dev/fd/'+str(fd))) if os.path.exists('/dev/fd/'+str(fd)) else None) for fd in range(3,64)]; "
                "print(json.dumps({'environment':dict(os.environ),'argv':sys.argv,'config':[open(p).read() for p in sys.argv[1:]],'fds':fds},sort_keys=True))"
            )
            completed = subprocess.run(
                [*bundle.argv, "-c", probe, *(str(path) for path in bundle.files)],
                env=base,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                close_fds=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            observed = completed.stdout
            self.assertIn(OPAQUE_HANDLE, observed)
            self.assertNotIn(PROVIDER_SECRET, observed)

    def test_materialization_rejects_preexisting_ancestor_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            escape = root / "escape"
            home.mkdir()
            escape.mkdir()
            (home / ".broker-adapter").symlink_to(escape, target_is_directory=True)
            bundle = build_adapter(
                "claude", "http://127.0.0.1:43210", OPAQUE_HANDLE, home, Path("/bin/true")
            )
            with self.assertRaises(OSError):
                materialize_adapter(bundle)
            self.assertEqual(list(escape.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
