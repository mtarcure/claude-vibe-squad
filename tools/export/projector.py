#!/usr/bin/env python3
"""Deterministically project one committed private tree into a public candidate tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import target_scan
from path_policy import Policy, PolicyError, load_policy


TRUSTED_TOOL_ROOT = Path(__file__).resolve().parents[2]

#: Where the publish line actually keeps its state, relative to the repo root.
#: The date is when the export line was established, not staleness -- renaming
#: it would orphan the tracked ledger below.
EXPORT_STATE_DIR = PurePosixPath("_state/public-export-2026-07-21")

#: The append-only publish history. This is the one file here that is git-tracked,
#: and it is the reason these defaults are constants rather than an expression
#: inside main(): a default pointing anywhere else does not fail, it forks. Until
#: 2026-08-24 the rail-continuity check in _verify_public_rail read an absent
#: ledger as "no prior entry to disagree with" and passed, so a wrong path both
#: skipped that guard and started a second history that aged independently (Hard
#: Rule 10). _authorize_missing_ledger now refuses that, and this constant is how
#: it knows which history the repository actually keeps.
DEFAULT_LEDGER_PATH = EXPORT_STATE_DIR / "export-ledger.jsonl"

#: What the rail-continuity check actually did, carried in the result and in the
#: ledger entry the run appends. `target_scan_files` below exists for the same
#: reason: a check that did not run and a check that found nothing must not
#: leave the same record. "unrecorded-first-run" is self-limiting -- the entry it
#: writes is what makes every later run on that rail "verified".
LEDGER_CONTINUITY_VERIFIED = "verified"
LEDGER_CONTINUITY_FIRST_RUN = "unrecorded-first-run"

#: Where the embedded product-hygiene gate is told to write its report, which
#: this module then reads back and requires to be passing. Regenerated per run,
#: so a wrong path only strands a file -- but it shares the directory because
#: the gate report is the evidence for the ledger entry written beside it.
DEFAULT_GATE_REPORT_PATH = EXPORT_STATE_DIR / "candidate-gate.md"


class ProjectorError(RuntimeError):
    """Projection cannot continue without weakening a release invariant."""


@dataclass(frozen=True)
class ProjectionResult:
    source_sha: str
    candidate_tree: str
    public_tip: str
    public_export_ref: str
    #: LEDGER_CONTINUITY_VERIFIED when a recorded public tip was compared against
    #: the live rail, LEDGER_CONTINUITY_FIRST_RUN when the operator explicitly
    #: authorised starting a history that had none.
    ledger_continuity: str
    policy_sha256: str
    candidate_root: str
    gate_report: str
    #: Every source path refused by policy. This is deliberately named in the
    #: result rather than inferred from the candidate: default-deny is only
    #: auditable when an unclassified path leaves a receipt.
    paths_refused: tuple[str, ...]
    #: The refused subset for which no rule made an explicit public/private
    #: decision. These paths are denied by default and require a public permit
    #: before a later projection can include them.
    unclassified_paths_refused: tuple[str, ...]
    #: How many files the engagement-target scan actually read. Recorded in the
    #: ledger because "no findings" and "never ran" are otherwise the same
    #: entry, and this rail's whole failure mode is checks that were never asked.
    target_scan_files: int
    #: Advisory signal only. Path policy, not this recognizer, owns publication
    #: authority; findings remain visible for investigation and defense in depth.
    target_scan_findings: tuple[str, ...]
    target_scan_paths_skipped: tuple[str, ...]
    #: Honest public bounty capability state derived from the same policy that
    #: withholds the named private components.
    public_bounty_capability_status: str
    public_bounty_withheld: tuple[str, ...]


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
) -> tuple[list[str], list[str], list[str]]:
    refused: list[str] = []
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
            refused.append(path)
        elif classification == "public":
            public.append(path)
        else:
            unknown.append(path)
            refused.append(path)
    return refused, public, unknown


def _read_last_ledger_entry(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        # The ledger is append-only and carries two record kinds: projection
        # records (which own `public_tip`) and publish records (`event`:
        # "publish", which own `published_tip`). Only projection records
        # describe the rail this check verifies, so scan back past any publish
        # records rather than assuming the last line is a projection.
        entry = None
        for line in reversed(lines):
            candidate = json.loads(line)
            if not isinstance(candidate, dict):
                continue
            # Publish records name the tip they pushed as `published_tip`;
            # projection records name the tip they projected onto as
            # `public_tip`. Both describe where the public rail stood, so the
            # continuity check honours whichever kind is most recent. Reading
            # only projection records silently ignores every publish since.
            tip = candidate.get("public_tip") or candidate.get("published_tip")
            if isinstance(tip, str):
                entry = dict(candidate)
                entry["public_tip"] = tip
                break
        if entry is None:
            return None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectorError(f"cannot read export ledger {path}: {error}") from error
    return entry


def _authorize_missing_ledger(
    root: Path,
    *,
    ledger_path: Path,
    allow_missing_ledger: Path | None,
) -> None:
    """Refuse a history-less projection unless the operator named the history it starts.

    An absent ledger is the one input that makes the continuity check vacuous,
    so it must not be allowed to look like agreement. The dangerous case is not
    "the ledger is missing", it is "the ledger is missing and was not meant to
    be" -- a typo'd --ledger, a wrong --root, a resurrected retired directory.
    Two separate things therefore have to hold.

    First, and not overridable: the repository must not already keep a publish
    history somewhere else. DEFAULT_LEDGER_PATH is that history, and
    scripts/python/tests/test_export_projector.py pins the constant to the one
    git-tracked ledger, so it is a real oracle rather than a second guess at the
    same answer. If that file exists and is not the one asked for, the ledger is
    not missing, it is elsewhere -- which makes this a fork, not a first run, and
    a flag must not be able to authorise it.

    Second: the opt-out is answered in the currency of the mistake it guards,
    which is a path. `--allow-missing-ledger <path>` has to name the ledger this
    run will create. A bare yes/no is what an operator pastes back out of the
    error without rereading it; naming the file makes the assertion about one
    specific history.
    """
    tracked = (root / DEFAULT_LEDGER_PATH).resolve()
    requested = ledger_path.resolve()
    reason = (
        f"export ledger {ledger_path} exists but records no public tip"
        if ledger_path.exists()
        else f"export ledger {ledger_path} does not exist"
    )
    if tracked != requested and tracked.is_file():
        raise ProjectorError(
            f"{reason}, but this repository already keeps its publish history at "
            f"{tracked}. That is a second history, not a first run; point "
            "--ledger at the tracked ledger."
        )
    if allow_missing_ledger is None:
        raise ProjectorError(
            f"{reason}, so the public-rail continuity check has nothing to "
            "compare against and would pass without looking. If this really is "
            "the first projection onto this rail, authorise it explicitly with "
            f"--allow-missing-ledger {ledger_path}"
        )
    if allow_missing_ledger.resolve() != requested:
        raise ProjectorError(
            f"--allow-missing-ledger names {allow_missing_ledger}, but this run "
            f"would write {ledger_path}; the opt-out must name the ledger it "
            "authorises"
        )


def _verify_public_rail(
    root: Path,
    *,
    public_ref: str,
    public_export_ref: str,
    expected_public_tip: str,
    ledger_path: Path,
    allow_missing_ledger: Path | None,
) -> tuple[str, str, str]:
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
    if last_entry is None:
        # Absent, empty, or carrying no record that names a public tip: all three
        # leave this check with nothing to compare, and all three must be said
        # out loud rather than inferred as agreement.
        _authorize_missing_ledger(
            root,
            ledger_path=ledger_path,
            allow_missing_ledger=allow_missing_ledger,
        )
        return public_tip, export_tip, LEDGER_CONTINUITY_FIRST_RUN
    if last_entry["public_tip"] != public_tip:
        raise ProjectorError(
            f"ledger/public mismatch: ledger={last_entry['public_tip']}, public={public_tip}"
        )
    return public_tip, export_tip, LEDGER_CONTINUITY_VERIFIED


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


def _annotate_public_bounty_mode(
    root: Path,
    source_sha: str,
    policy: Policy,
    *,
    environment: dict[str, str],
) -> bool:
    """Make a retained public interface state its intentionally missing parts.

    The private source stays unchanged. The candidate tree gets a deterministic
    notice derived from path-policy.json, which is also the canonical record of
    the withheld components. This keeps a method-only public bounty document
    useful without silently claiming that its private implementation ships.
    """
    path = "shared/modes/bounty.md"
    object_name = f"{source_sha}:{path}"
    exists = _run(root, ["git", "cat-file", "-e", object_name], check=False)
    if exists.returncode != 0:
        return False
    if policy.classify(path) != "public":
        raise ProjectorError(f"public bounty capability interface is not permitted: {path!r}")
    try:
        text = _git(root, ["cat-file", "blob", object_name]).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectorError(f"public bounty capability interface is not UTF-8: {path!r}") from error

    marker = "> **Public capability boundary (generated by the projector).**"
    if marker not in text:
        heading = "# Mode: Bounty\n"
        if heading not in text:
            raise ProjectorError(f"public bounty capability interface has no canonical heading: {path!r}")
        items = "\n".join(f"> - `{item}`" for item in policy.public_bounty_withheld)
        notice = (
            f"{heading}\n{marker} {policy.public_bounty_notice}\n>\n"
            f"> Withheld components:\n{items}\n"
        )
        text = text.replace(heading, notice, 1)

    blob = _git(root, ["hash-object", "-w", "--stdin"], input_bytes=text.encode("utf-8")).decode().strip()
    _git(
        root,
        ["update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"],
        environment=environment,
    )
    return True


def _append_ledger(path: Path, result: ProjectionResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "candidate_tree": result.candidate_tree,
        "policy_sha256": result.policy_sha256,
        "public_export_ref": result.public_export_ref,
        "public_parent": result.public_tip,
        "public_tip": result.public_tip,
        # Receipt, exactly like target_scan_files: an entry written by a run
        # that had no predecessor to check against says so permanently, in the
        # history it starts.
        "ledger_continuity": result.ledger_continuity,
        "source_sha": result.source_sha,
        "paths_refused": list(result.paths_refused),
        "unclassified_paths_refused": list(result.unclassified_paths_refused),
        # Receipt, not decoration: it is what distinguishes "the target scan
        # found nothing" from "the target scan never ran" in the audit trail.
        "target_scan_files": result.target_scan_files,
        "target_scan_findings": list(result.target_scan_findings),
        "target_scan_paths_skipped": list(result.target_scan_paths_skipped),
        "public_bounty_capability_status": result.public_bounty_capability_status,
        "public_bounty_withheld": list(result.public_bounty_withheld),
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
    allow_missing_ledger: Path | None = None,
    gate_report: Path,
    public_ref: str,
    public_export_ref: str,
    expected_public_tip: str,
    environment: dict[str, str] | None = None,
) -> ProjectionResult:
    root = root.resolve(strict=True)
    _require_clean_source(root)
    source_sha = _resolve_commit(root, source)
    public_tip, export_tip, ledger_continuity = _verify_public_rail(
        root,
        public_ref=public_ref,
        public_export_ref=public_export_ref,
        expected_public_tip=expected_public_tip,
        ledger_path=ledger_path,
        allow_missing_ledger=allow_missing_ledger,
    )
    try:
        policy = load_policy(policy_path)
    except PolicyError as error:
        raise ProjectorError(str(error)) from error
    refused, _public, unclassified = _classify_source(root, source_sha, policy)
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
        if refused:
            encoded = b"\0".join(path.encode("utf-8", errors="surrogateescape") for path in refused)
            _git(
                root,
                ["update-index", "--force-remove", "-z", "--stdin"],
                environment=index_environment,
                input_bytes=encoded + b"\0",
            )
        _annotate_public_bounty_mode(
            root,
            source_sha,
            policy,
            environment=index_environment,
        )
        candidate_tree = _git(root, ["write-tree"], environment=index_environment).decode().strip()
        remaining_refused, remaining_public, _remaining_unclassified = _classify_source(
            root, candidate_tree, policy
        )
        if remaining_refused:
            raise ProjectorError(f"candidate still contains refused paths: {remaining_refused!r}")
        if not remaining_public:
            raise ProjectorError("candidate tree is unexpectedly empty")
        _git(
            root,
            ["checkout-index", "--all", "--force", f"--prefix={candidate}/"],
            environment=index_environment,
        )

        # Advisory engagement-target scan, on the materialised candidate. It is
        # retained as a second signal, including positive findings, a liveness
        # receipt and every path it skipped. It does not own publication
        # authority: recognizers are denylists over an unbounded representation
        # space, while the path policy above permits the finite public surface.
        # A finding therefore remains evidence without becoming a veto, and a
        # clean/empty scan cannot authorize a path the policy did not permit.
        #
        # It runs from TRUSTED_TOOL_ROOT's import, not from the candidate, so a
        # candidate still cannot replace the advisory implementation reporting
        # on it.
        target_result = target_scan.scan(candidate)

        gate_environment = index_environment.copy()
        gate_environment["GIT_DIR"] = git_dir
        gate_environment["GIT_WORK_TREE"] = str(candidate)
        gate_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        gate_environment["SQUAD_EXPORT_TOOL_ROOT"] = str(TRUSTED_TOOL_ROOT)
        gate_environment["GITLEAKS_CONFIG"] = str(
            TRUSTED_TOOL_ROOT / "tools" / "export" / "policy" / "gitleaks.toml"
        )
        trusted_gate = TRUSTED_TOOL_ROOT / "bin" / "product-hygiene.sh"
        if not trusted_gate.is_file():
            raise ProjectorError(f"trusted export gate is unavailable: {trusted_gate}")
        gate = _run(
            candidate,
            [
                "bash",
                str(trusted_gate),
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
        try:
            report_metadata = gate_report.lstat()
            report_text = gate_report.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProjectorError("candidate gate did not publish a readable report") from error
        if not stat.S_ISREG(report_metadata.st_mode):
            raise ProjectorError("candidate gate report is not a regular file")
        required_report_lines = {
            "- Path-policy status: 0",
            "- Gitleaks status: 0",
            "- Entropy/identifier status: 0",
            "- Remote-ref audit status: 0",
        }
        if not required_report_lines <= set(report_text.splitlines()):
            raise ProjectorError("candidate gate report is incomplete or non-passing")
        # `- Remote-ref audit status: 0` is also what the gate writes when there
        # is no `public` remote to interrogate: bin/product-hygiene.sh leaves
        # remote_ref_status at its initial 0 and reports the skip only in prose.
        # A retained disjoint ref (GitHub keeps refs/pull/N/head across a
        # clean-slate force-push) is exactly the leak that audit exists to find,
        # so a status of 0 earned by not looking must not certify a projection.
        # An absent gate and a green gate must not look the same from here.
        if "remote-ref audit skipped" in report_text:
            raise ProjectorError(
                "candidate gate skipped the remote-advertised-ref audit (no 'public' "
                "remote configured); status 0 from a check that did not run is not a pass"
            )

    result = ProjectionResult(
        source_sha=source_sha,
        candidate_tree=candidate_tree,
        public_tip=public_tip,
        public_export_ref=export_tip,
        ledger_continuity=ledger_continuity,
        policy_sha256=policy_sha256,
        candidate_root=str(candidate),
        gate_report=str(gate_report.resolve()),
        paths_refused=tuple(refused),
        unclassified_paths_refused=tuple(unclassified),
        target_scan_files=target_result.files_scanned,
        target_scan_findings=tuple(target_result.findings),
        target_scan_paths_skipped=tuple(target_result.paths_skipped),
        public_bounty_capability_status=policy.public_bounty_status,
        public_bounty_withheld=policy.public_bounty_withheld,
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
    parser.add_argument("--ledger", help=f"default: <root>/{DEFAULT_LEDGER_PATH}")
    parser.add_argument(
        "--allow-missing-ledger",
        metavar="LEDGER_PATH",
        help=(
            "authorise the first projection onto a rail with no recorded "
            "history; must name the same ledger path this run will write"
        ),
    )
    parser.add_argument("--gate-report", help=f"default: <root>/{DEFAULT_GATE_REPORT_PATH}")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    try:
        result = project(
            root=root,
            source=args.source,
            candidate_root=Path(args.candidate),
            policy_path=Path(args.policy or root / "tools/export/policy/path-policy.json"),
            identifier_denylist=Path(
                args.identifier_denylist
                or root / "tools/export/identifier-denylist.txt"
            ),
            ledger_path=Path(args.ledger or root / DEFAULT_LEDGER_PATH),
            allow_missing_ledger=(
                Path(args.allow_missing_ledger)
                if args.allow_missing_ledger
                else None
            ),
            gate_report=Path(args.gate_report or root / DEFAULT_GATE_REPORT_PATH),
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
