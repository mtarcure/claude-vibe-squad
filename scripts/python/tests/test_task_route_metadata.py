import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]


class _Router:
    def get(self, _path):
        return lambda function: function


fastapi = types.ModuleType("fastapi")
fastapi.APIRouter = _Router
fastapi.HTTPException = type("HTTPException", (Exception,), {})


class _YamlError(Exception):
    pass


def _safe_load(text):
    if text == "metadata: [unterminated\n":
        raise _YamlError("malformed fixture")
    return {}


yaml = types.ModuleType("yaml")
yaml.YAMLError = _YamlError
yaml.safe_load = _safe_load
spec = importlib.util.spec_from_file_location(
    "task_route_metadata_under_test",
    ROOT / "daemon" / "routes" / "task.py",
)
assert spec is not None and spec.loader is not None
task = importlib.util.module_from_spec(spec)
with mock.patch.dict(sys.modules, {"fastapi": fastapi, "yaml": yaml}):
    spec.loader.exec_module(task)


class TaskRouteMetadataTests(unittest.TestCase):
    def test_malformed_yaml_returns_default_metadata_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_file = root / "active" / "kimi" / "TASK-malformed.md"
            task_file.parent.mkdir(parents=True)
            task_file.write_text("metadata: [unterminated\n", encoding="utf-8")

            with mock.patch.dict(
                task.os.environ,
                {"VIBESQUAD_STATE_DIR": str(root)},
            ):
                result = task.list_tasks()
            expected_mtime = int(task_file.stat().st_mtime)

        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["tokens_used"], 0)
        self.assertEqual(
            result["tasks"][0]["started_at_epoch"],
            expected_mtime,
        )

    def test_unexpected_yaml_exception_is_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_file = Path(directory) / "TASK-unexpected.md"
            task_file.write_text("metadata: valid\n", encoding="utf-8")

            with mock.patch.object(
                task.yaml,
                "safe_load",
                side_effect=RuntimeError("unexpected parser defect"),
            ), self.assertRaisesRegex(RuntimeError, "unexpected parser defect"):
                task._read_task_meta(task_file)


if __name__ == "__main__":
    unittest.main()
