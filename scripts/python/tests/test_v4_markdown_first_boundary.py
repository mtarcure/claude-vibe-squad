from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
VERIFICATION_ONLY_MODULES: frozenset[str] = frozenset()
VERIFICATION_ONLY_FILES = frozenset(
    ROOT / "scripts" / "python" / f"{name}.py"
    for name in VERIFICATION_ONLY_MODULES
)
EXCLUDED_TOP_LEVEL = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".superpowers",
        ".venv",
        "_archive",
        "_state",
        "assets",
        "docs",
        "runs",
        "tests",
    }
)
CODE_SUFFIXES = frozenset(
    {
        "",
        ".bash",
        ".cjs",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".plist",
        ".py",
        ".sh",
        ".toml",
        ".ts",
        ".tsv",
        ".txt",
        ".yaml",
        ".yml",
        ".zsh",
    }
)


def production_code_files() -> list[Path]:
    files: list[Path] = []
    for candidate in ROOT.rglob("*"):
        if not candidate.is_file() or candidate.suffix not in CODE_SUFFIXES:
            continue
        relative = candidate.relative_to(ROOT)
        if relative.parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        if candidate in VERIFICATION_ONLY_FILES:
            continue
        if any(
            part in {"__pycache__", "fixtures", "node_modules", "tests", "worktrees"}
            or part.startswith("test_")
            for part in relative.parts
        ):
            continue
        # The canonical test runner is verification infrastructure rather
        # than a model/runtime entrypoint.
        if relative == Path("bin/test"):
            continue
        files.append(candidate)
    return sorted(files)


class MarkdownFirstBoundaryTests(unittest.TestCase):
    def test_verification_modules_are_absent_from_runtime_graph(self) -> None:
        references: list[str] = []
        for code_path in production_code_files():
            try:
                source = code_path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            for module in sorted(VERIFICATION_ONLY_MODULES):
                if module in source:
                    references.append(f"{code_path.relative_to(ROOT)} -> {module}")

        self.assertEqual(
            references,
            [],
            "P2 verification machinery entered the production import/invocation graph",
        )


if __name__ == "__main__":
    unittest.main()
