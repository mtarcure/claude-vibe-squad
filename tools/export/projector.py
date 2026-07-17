#!/usr/bin/env python3
"""Deterministically project one committed private tree into a public candidate tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from path_policy import Policy, PolicyError, load_policy


class ProjectorError(RuntimeError):
    """Projection cannot continue without weakening a release invariant."""


@dataclass(frozen=True)
class ProjectionResult:
    source_sha: str
    candidate_tree: str
    public_tip: str
    public_export_ref: str
    policy_sha256: str
    candidate_root: str
    gate_report: str


def _run(
    root: Path,
    arguments: list[str],
    *,
    environment: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.run(
        arguments,
        cwd=root,
        env=environment,
        input=input_bytes,
        capture_output=True,
    )
    if check and process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        raise ProjectorError(f"command failed ({process.returncode}): {' '.join(arguments)}: {stderr}")
    return process


def _git(
    root: Path,
    arguments: list[str],
    *,
    environment: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> bytes:
    return _run(
        root,
        ["git", *arguments],
        environment=environment,
        input_bytes=input_bytes,
    ).stdout


def _resolve_commit(root: Path, revision: str) -> str:
    return _git(root, ["rev-parse", "--verify", f"{revision}^{{commit}}"]).decode().strip()


def _require_clean_source(root: Path) -> None:
    status = _git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if status:
        paths = []
        for entry in status.split(b"\0"):
            if entry:
                paths.append(entry.decode("utf-8", errors="surrogateescape"))
        preview = ", ".join(repr(item) for item in paths[:5])
        raise ProjectorError(f"private source is dirty; commit or remove changes first: {preview}")


def _tree_entries(root: Path, treeish: str) -> list[tuple[str, str, str, str]]:
    raw = _git(root, ["ls-tree", "-r", "-z", treeish])
    entries: list[tuple[str, str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode, object_type, object_sha = metadata.decode("ascii").split(" ")
        except ValueError as error:
            raise ProjectorError("git ls-tree returned a malformed record") from error
        path = encoded_path.decode("utf-8", errors="surrogateescape")
        entries.append((mode, object_type, object_sha, path))
    return entries


def _symlink_escapes(path: str, target: str) -> bool:
    if not target or PurePosixPath(target).is_absolute():
        return True
    combined = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    return combined == ".." or combined.startswith("../")


def _classify_source(
    root: Path,
    source_sha: str,
    policy: Policy,
) -> tuple[list[str], list[str]]:
    denied: list[str] = []
    public: list[str] = []
    unknown: list[str] = []
    for mode, object_type, object_sha, path in _tree_entries(root, source_sha):
        if mode == "160000" or object_type == "commit":
            raise ProjectorError(f"submodules are not exportable: {path!r}")
        if mode == "120000":
            target_bytes = _git(root, ["cat-file", "blob", object_sha])
            target = target_bytes.decode("utf-8", errors="surrogateescape")
            if _symlink_escapes(path, target):
                raise ProjectorError(f"symlink escapes candidate root: {path!r} -> {target!r}")
        classification = policy.classify(path)
        if classification == "private":
            denied.append(path)
        elif classification == "public":
            public.append(path)
        else:
            unknown.append(path)
    if unknown:
        preview = ", ".join(repr(item) for item in unknown[:10])
        raise ProjectorError(f"source contains unknown paths: {preview}")
    return denied, public


def _read_last_ledger_entry(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        entry = json.loads(lines[-1])
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectorError(f"cannot read export ledger {path}: {error}") from error
    if not isinstance(entry, dict) or not isinstance(entry.get("public_tip"), str):
        raise ProjectorError(f"last export-ledger entry is malformed: {path}")
    return entry


def _verify_public_rail(
    root: Path,
    *,
    public_ref: str,
    public_export_ref: str,
    expected_public_tip: str,
    ledger_path: Path,
) -> tuple[str, str]:
    public_tip = _resolve_commit(root, public_ref)
    expected_tip = _resolve_commit(root, expected_public_tip)
    export_tip = _resolve_commit(root, public_export_ref)
    if public_tip != expected_tip:
        raise ProjectorError(
            f"public tip mismatch: {public_ref}={public_tip}, expected={expected_tip}"
        )
    if export_tip != public_tip:
        raise ProjectorError(
            f"public-export rail drift: {public_export_ref}={export_tip}, public={public_tip}"
        )
    last_entry = _read_last_ledger_entry(ledger_path)
    if last_entry is not None and last_entry["public_tip"] != public_tip:
        raise ProjectorError(
            f"ledger/public mismatch: ledger={last_entry['public_tip']}, public={public_tip}"
        )
    return public_tip, export_tip


def _prepare_candidate_root(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    if candidate.exists():
        if not candidate.is_dir():
            raise ProjectorError(f"candidate path is not a directory: {candidate}")
        if any(candidate.iterdir()):
            raise ProjectorError(f"candidate directory must be empty: {candidate}")
    else:
        candidate.mkdir(parents=True)
    return candidate.resolve()


def _append_ledger(path: Path, result: ProjectionResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "candidate_tree": result.candidate_tree,
        "policy_sha256": result.policy_sha256,
        "public_export_ref": result.public_export_ref,
        "public_parent": result.public_tip,
        "public_tip": result.public_tip,
        "source_sha": result.source_sha,
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise ProjectorError(f"cannot append export ledger {path}: {error}") from error


def project(
    *,
    root: Path,
    source: str,
    candidate_root: Path,
    policy_path: Path,
    identifier_denylist: Path,
    ledger_path: Path,
    gate_report: Path,
    public_ref: str,
    public_export_ref: str,
    expected_public_tip: str,
    environment: dict[str, str] | None = None,
) -> ProjectionResult:
    root = root.resolve(strict=True)
    _require_clean_source(root)
    source_sha = _resolve_commit(root, source)
    public_tip, export_tip = _verify_public_rail(
        root,
        public_ref=public_ref,
        public_export_ref=public_export_ref,
        expected_public_tip=expected_public_tip,
        ledger_path=ledger_path,
    )
    try:
        policy = load_policy(policy_path)
    except PolicyError as error:
        raise ProjectorError(str(error)) from error
    denied, _public = _classify_source(root, source_sha, policy)
    policy_sha256 = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    candidate = _prepare_candidate_root(candidate_root)
    gate_report.parent.mkdir(parents=True, exist_ok=True)
    git_dir = _git(root, ["rev-parse", "--absolute-git-dir"]).decode().strip()

    with tempfile.TemporaryDirectory(prefix="public-projector-") as temporary:
        index_path = str(Path(temporary) / "candidate.index")
        index_environment = os.environ.copy()
        if environment:
            index_environment.update(environment)
        index_environment["GIT_INDEX_FILE"] = index_path
        _git(root, ["read-tree", source_sha], environment=index_environment)
        if denied:
            encoded = b"\0".join(path.encode("utf-8", errors="surrogateescape") for path in denied)
            _git(
                root,
                ["update-index", "--force-remove", "-z", "--stdin"],
                environment=index_environment,
                input_bytes=encoded + b"\0",
            )
        candidate_tree = _git(root, ["write-tree"], environment=index_environment).decode().strip()
        remaining_denied, remaining_public = _classify_source(root, candidate_tree, policy)
        if remaining_denied:
            raise ProjectorError(f"candidate still contains denied paths: {remaining_denied!r}")
        if not remaining_public:
            raise ProjectorError("candidate tree is unexpectedly empty")
        _git(
            root,
            ["checkout-index", "--all", "--force", f"--prefix={candidate}/"],
            environment=index_environment,
        )

        gate_environment = index_environment.copy()
        gate_environment["GIT_DIR"] = git_dir
        gate_environment["GIT_WORK_TREE"] = str(candidate)
        gate_environment["GITLEAKS_CONFIG"] = str(
            candidate / "tools" / "export" / "policy" / "gitleaks.toml"
        )
        gate = _run(
            candidate,
            [
                "bash",
                str(candidate / "bin" / "product-hygiene.sh"),
                "--public-export",
                "--root",
                str(candidate),
                "--identifier-denylist",
                str(identifier_denylist.resolve(strict=True)),
                "--report",
                str(gate_report.resolve()),
            ],
            environment=gate_environment,
            check=False,
        )
        if gate.returncode != 0:
            stdout = gate.stdout.decode("utf-8", errors="replace").strip()
            stderr = gate.stderr.decode("utf-8", errors="replace").strip()
            raise ProjectorError(
                f"candidate gate failed ({gate.returncode}); report={gate_report}; "
                f"stdout={stdout!r}; stderr={stderr!r}; candidate_tree={candidate_tree}"
            )

    result = ProjectionResult(
        source_sha=source_sha,
        candidate_tree=candidate_tree,
        public_tip=public_tip,
        public_export_ref=export_tip,
        policy_sha256=policy_sha256,
        candidate_root=str(candidate),
        gate_report=str(gate_report.resolve()),
    )
    _append_ledger(ledger_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--source", default="HEAD")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--expected-public-tip", required=True)
    parser.add_argument("--public-ref", default="refs/remotes/public/main")
    parser.add_argument("--public-export-ref", default="refs/heads/public-export")
    parser.add_argument("--policy")
    parser.add_argument("--identifier-denylist")
    parser.add_argument("--ledger")
    parser.add_argument("--gate-report")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    state = root / "_state" / "repo-split-2026-07-16"
    try:
        result = project(
            root=root,
            source=args.source,
            candidate_root=Path(args.candidate),
            policy_path=Path(args.policy or root / "tools/export/policy/path-policy.json"),
            identifier_denylist=Path(
                args.identifier_denylist or state / "identifier-denylist.txt"
            ),
            ledger_path=Path(args.ledger or state / "export-ledger.jsonl"),
            gate_report=Path(args.gate_report or state / "candidate-gate.md"),
            public_ref=args.public_ref,
            public_export_ref=args.public_export_ref,
            expected_public_tip=args.expected_public_tip,
        )
    except (OSError, ProjectorError) as error:
        print(f"projector error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
