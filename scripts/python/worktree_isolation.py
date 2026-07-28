#!/usr/bin/env python3
"""V2 Task 2.3 — worktree-per-instance concurrency pool and F4 .git denials.

The security property is allowlist-based, not denylist-based: a task's
Seatbelt write scope is exactly its own worktree root (validated to be a
real, non-aliased, registered ``git worktree``, never the shared git
directory or a path inside it). Denial of shared ``.git`` state — refs,
config, hooks, remotes, sibling worktrees, the integration branch — falls
out of ``(deny default)`` in ``seatbelt_profile.compile_profile`` by
construction; this module does not reimplement Seatbelt enforcement or
Task 2.1's scheduler, it composes both.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Sequence

from launch_hygiene import run_sanitized
from seatbelt_profile import CompiledProfile, ProfileSpec, compile_profile

try:
    import board_router
except ImportError:  # pragma: no cover - package-context fallback
    from . import board_router  # type: ignore[no-redef]


GIT_RESOURCE_CLASSES: tuple[str, ...] = (
    "git_refs",
    "git_config",
    "git_hooks",
    "git_remotes",
    "integration_branch",
)
_GIT_EXECUTABLE = Path("/usr/bin/git")
_TASK_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
_ATTEMPT_RE = re.compile(r"^d-[0-9a-f]{32}$")
_UNSAFE_BRANCH_CHARS = re.compile(r"[\s~^:?*\[\\]")
_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40,64}$")


class WorktreeIsolationError(RuntimeError):
    """A worktree cannot be provisioned, or its write scope is not provably isolated."""


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [
                str(_GIT_EXECUTABLE),
                # CBSE hardening (corpus C section 1.A / defensive posture #1):
                # every board git op in a worker-controlled worktree runs with
                # hook and fsmonitor execution disabled so a worker-planted
                # `.git/hooks/*` or `core.fsmonitor` program can never fire on
                # the host. A command-line `-c` overrides any value the same key
                # carries in a (potentially worker-planted) config file.
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=",
                "-c",
                "gc.auto=0",
                *args,
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            close_fds=True,
            # Neutralize worker-plantable global/system git config as a second
            # CBSE layer: HOME is already absent here, and pinning the global and
            # system config to /dev/null keeps a planted `~/.gitconfig` (aliases,
            # `core.hooksPath`, `sshCommand`, pager/editor exec) out of every
            # board plumbing call. Commit identity is git's built-in
            # username@hostname auto-detection, unaffected by these settings.
            env={
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_TERMINAL_PROMPT": "0",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorktreeIsolationError(f"git invocation failed: {exc}") from exc


def _canonical_existing(path: Path, label: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise WorktreeIsolationError(f"{label} must be an absolute path: {raw}")
    try:
        resolved = Path(os.path.realpath(raw))
        if not resolved.exists():
            raise WorktreeIsolationError(f"{label} does not exist: {raw}")
    except OSError as exc:
        raise WorktreeIsolationError(f"{label} is unavailable: {raw}: {exc}") from exc
    return resolved


def git_common_dir(repo_root: Path) -> Path:
    """Resolve the one shared git directory for a main repo or a linked worktree."""

    root = _canonical_existing(Path(repo_root), "repo root")
    completed = _run_git(["rev-parse", "--git-common-dir"], cwd=root)
    if completed.returncode != 0:
        raise WorktreeIsolationError(
            f"cannot resolve git-common-dir for {root}: {completed.stderr.strip()}"
        )
    raw = completed.stdout.strip()
    if not raw:
        raise WorktreeIsolationError(f"git-common-dir was empty for {root}")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = Path(os.path.realpath(candidate))
    except OSError as exc:
        raise WorktreeIsolationError(f"git-common-dir is unavailable: {exc}") from exc
    if not resolved.is_dir():
        raise WorktreeIsolationError(f"git-common-dir is not a directory: {resolved}")
    return resolved


def _registered_worktree_roots(repo_root: Path) -> tuple[Path, ...]:
    completed = _run_git(["worktree", "list", "--porcelain"], cwd=repo_root)
    if completed.returncode != 0:
        raise WorktreeIsolationError(f"cannot list worktrees: {completed.stderr.strip()}")
    roots: list[Path] = []
    for line in completed.stdout.splitlines():
        if line.startswith("worktree "):
            roots.append(Path(os.path.realpath(line[len("worktree "):])))
    return tuple(roots)


def worktree_write_scope_paths(worktree_root: Path, repo_root: Path) -> tuple[Path, ...]:
    """Validate and return the exact, sole Seatbelt write scope for one worktree.

    Rejects the shared git directory itself, any path inside it, and any
    path that is not the realpath-identical root of a currently registered
    ``git worktree`` (blocking symlink/hardlink aliases of a real worktree).
    """

    root = _canonical_existing(Path(worktree_root), "worktree root")
    common = git_common_dir(repo_root)
    if root == common or common in root.parents:
        raise WorktreeIsolationError(f"worktree root is the shared git directory: {root}")
    if root in common.parents or root == common.parent and common.name == ".git":
        # A worktree root can never legitimately be an ancestor of the shared dir.
        raise WorktreeIsolationError(f"worktree root contains the shared git directory: {root}")
    try:
        if os.path.commonpath((str(root), str(common))) == str(common):
            raise WorktreeIsolationError(f"worktree root is inside the shared git directory: {root}")
    except ValueError:
        pass  # different drives is not a concept on POSIX; unreachable here.
    registered = _registered_worktree_roots(repo_root)
    if root not in registered:
        raise WorktreeIsolationError(
            f"worktree root is not a registered git worktree of {repo_root}: {root}"
        )
    return (root,)


def _validate_task_attempt(task_id: str, attempt_id: str) -> None:
    if not isinstance(task_id, str) or not _TASK_RE.fullmatch(task_id):
        raise WorktreeIsolationError(f"invalid task id: {task_id!r}")
    if not isinstance(attempt_id, str) or not _ATTEMPT_RE.fullmatch(attempt_id):
        raise WorktreeIsolationError(f"invalid attempt id: {attempt_id!r}")


def _branch_name(task_id: str, attempt_id: str) -> str:
    candidate = f"worktree/{task_id}/{attempt_id}"
    if (
        ".." in candidate
        or candidate.startswith("-")
        or candidate.endswith(".lock")
        or candidate.endswith("/")
        or candidate.startswith("/")
        or "@{" in candidate
        or candidate == "@"
        or _UNSAFE_BRANCH_CHARS.search(candidate)
        or any(ord(character) < 32 for character in candidate)
    ):
        raise WorktreeIsolationError(f"derived branch name is unsafe: {candidate!r}")
    return candidate


@dataclass(frozen=True)
class WorktreeHandle:
    task_id: str
    attempt_id: str
    branch: str
    worktree_root: Path
    repo_root: Path
    base_commit: str = ""


@dataclass(frozen=True)
class WorktreeIntegrationReceipt:
    status: str
    task_id: str
    base_commit: str
    worker_head: str
    target_before: str
    target_after: str
    integration_commit: str
    exact_worker_history: bool
    integrated_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    uncommitted_excluded_paths: tuple[str, ...]
    # A deletion must be stated, never inferred by diffing the receipt's other
    # fields: `integrated_paths` alone cannot distinguish "this path was
    # modified" from "this path was removed". `authorized_delete_paths` records
    # the frozen capability the deletions were checked against, so the audit
    # trail carries both what disappeared and under which authorization.
    deleted_paths: tuple[str, ...] = ()
    authorized_delete_paths: tuple[str, ...] = ()


class WorktreePool:
    """Provisions and releases one git worktree per concurrent task attempt."""

    def __init__(self, repo_root: Path, pool_root: Path, *, base_branch: str = "v2") -> None:
        self._repo_root = _canonical_existing(Path(repo_root), "repo root")
        self._pool_root = Path(pool_root)
        if not self._pool_root.is_absolute():
            raise WorktreeIsolationError(f"pool root must be absolute: {pool_root}")
        self._pool_root.mkdir(parents=True, exist_ok=True)
        self._base_branch = base_branch
        self._handles: dict[tuple[str, str], WorktreeHandle] = {}

    def active(self) -> tuple[WorktreeHandle, ...]:
        return tuple(self._handles.values())

    def provision(
        self,
        task_id: str,
        attempt_id: str,
        *,
        high_assurance: bool = False,
        dedicated_volume_attested: bool = False,
    ) -> WorktreeHandle:
        _validate_task_attempt(task_id, attempt_id)
        key = (task_id, attempt_id)
        if key in self._handles:
            raise WorktreeIsolationError(
                f"task/attempt already has a provisioned worktree: {task_id} {attempt_id}"
            )
        if high_assurance and not dedicated_volume_attested:
            raise WorktreeIsolationError(
                "high-assurance worktrees require dedicated volume attestation"
            )
        branch = _branch_name(task_id, attempt_id)
        worktree_root = self._pool_root / attempt_id
        if worktree_root.exists():
            raise WorktreeIsolationError(f"worktree path already exists: {worktree_root}")

        self._reject_target_inside_shared_git(worktree_root)

        base_commit = _resolve_commit(self._repo_root, self._base_branch)
        completed = _run_git(
            ["worktree", "add", "-q", "-b", branch, str(worktree_root), base_commit],
            cwd=self._repo_root,
        )
        if completed.returncode != 0:
            raise WorktreeIsolationError(
                f"git worktree add failed for {task_id}: {completed.stderr.strip()}"
            )
        try:
            canonical_root = Path(os.path.realpath(worktree_root))
            worktree_write_scope_paths(canonical_root, self._repo_root)
        except WorktreeIsolationError as exc:
            rolled_back, detail = self._rollback_failed_provision(worktree_root, branch)
            if not rolled_back:
                raise WorktreeIsolationError(
                    f"worktree provisioning rejected AND rollback incomplete for {task_id}: "
                    f"{exc}; {detail}"
                ) from exc
            raise WorktreeIsolationError(
                f"worktree provisioning rejected and rolled back for {task_id}: {exc}"
            ) from exc
        handle = WorktreeHandle(
            task_id=task_id,
            attempt_id=attempt_id,
            branch=branch,
            worktree_root=canonical_root,
            repo_root=self._repo_root,
            base_commit=base_commit,
        )
        self._handles[key] = handle
        return handle

    def _reject_target_inside_shared_git(self, worktree_root: Path) -> None:
        """Validate/canonicalize the intended target against the common git dir
        BEFORE ``git worktree add`` runs, so the common failure mode (a pool
        rooted inside ``.git``) never mutates shared git state in the first
        place. ``worktree_root`` does not exist yet, so this canonicalizes via
        its existing parent rather than the not-yet-created path itself.
        """

        common = git_common_dir(self._repo_root)
        resolved_parent = Path(os.path.realpath(worktree_root.parent))
        candidate = resolved_parent / worktree_root.name
        if candidate == common or common in candidate.parents:
            raise WorktreeIsolationError(
                f"worktree target is the shared git directory or inside it: {candidate}"
            )
        try:
            if os.path.commonpath((str(candidate), str(common))) == str(common):
                raise WorktreeIsolationError(
                    f"worktree target is inside the shared git directory: {candidate}"
                )
        except ValueError:
            pass  # different drives is not a concept on POSIX; unreachable here.

    def _rollback_failed_provision(self, worktree_root: Path, branch: str) -> tuple[bool, str]:
        """Exact rollback for a post-add failure: remove the worktree AND its
        branch so no forbidden shared-git state survives a rejected
        provisioning attempt. Reports success/failure rather than swallowing
        a rollback failure, since that would itself be exactly the kind of
        silent fail-open this fix exists to close.
        """

        remove_completed = _run_git(
            ["worktree", "remove", "--force", str(worktree_root)], cwd=self._repo_root
        )
        branch_completed = _run_git(["branch", "-D", branch], cwd=self._repo_root)
        ok = remove_completed.returncode == 0 and branch_completed.returncode == 0
        detail = (
            f"worktree_remove_rc={remove_completed.returncode} "
            f"branch_delete_rc={branch_completed.returncode} "
            f"worktree_remove_stderr={remove_completed.stderr.strip()!r} "
            f"branch_delete_stderr={branch_completed.stderr.strip()!r}"
        )
        return ok, detail

    def release(self, handle: WorktreeHandle, *, force: bool = False) -> None:
        key = (handle.task_id, handle.attempt_id)
        if key not in self._handles:
            raise WorktreeIsolationError(
                f"no active worktree for {handle.task_id} {handle.attempt_id}"
            )
        stored = self._handles[key]
        if stored != handle:
            raise WorktreeIsolationError(
                f"handle does not match the stored worktree for {handle.task_id} "
                f"{handle.attempt_id}: forged, stale, or cross-pool handle rejected "
                "before any mutation"
            )
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(stored.worktree_root))
        completed = _run_git(args, cwd=self._repo_root)
        if completed.returncode != 0:
            raise WorktreeIsolationError(
                f"git worktree remove failed for {handle.task_id}: {completed.stderr.strip()}"
            )
        del self._handles[key]


def _resolve_commit(repo_root: Path, value: str) -> str:
    completed = _run_git(
        ["rev-parse", "--verify", f"{value}^{{commit}}"],
        cwd=repo_root,
    )
    candidate = completed.stdout.strip()
    if completed.returncode != 0 or not _OBJECT_ID_RE.fullmatch(candidate):
        raise WorktreeIsolationError(
            f"cannot resolve commit {value!r}: {completed.stderr.strip()}"
        )
    return candidate


def _normalized_relative(value: str, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise WorktreeIsolationError(f"{label} is empty or invalid")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate == PurePosixPath(".")
        or ".." in candidate.parts
        or any(part in {"", "."} for part in candidate.parts)
    ):
        raise WorktreeIsolationError(f"{label} is not a safe repository path: {value!r}")
    return candidate


def _is_contained(path: PurePosixPath, scopes: Sequence[PurePosixPath]) -> bool:
    return any(scope == path or scope in path.parents for scope in scopes)


# Configuration-Based Sandbox Escape (CBSE) surfaces — corpus C section 1.A and
# corpus A technique #7. A sandboxed/poisoned worker cannot break the host
# isolation directly, so it plants a file the *unsandboxed* host, IDE, or CI
# runner later auto-executes or auto-loads. Directory segments here are ones an
# auto-activation step keys on; basenames are files a host tool runs on open,
# activate, install, or import. The `.git`/`.githooks` components are a
# structural escape (git itself would execute them) and are refused regardless
# of scope; the rest are refused only when they fall OUTSIDE the operator's
# declared write_scope, because an in-scope edit was explicitly authorized by
# the dispatching packet.
_CBSE_STRUCTURAL_SEGMENTS: frozenset[str] = frozenset({".git", ".githooks"})
_CBSE_AUTOLOAD_SEGMENTS: frozenset[str] = frozenset(
    {".venv", "venv", ".vscode", ".idea", ".claude", ".cursor", ".config"}
)
_CBSE_AUTOLOAD_BASENAMES: frozenset[str] = frozenset(
    {
        "site.py",
        "sitecustomize.py",
        "usercustomize.py",
        "package.json",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        ".envrc",
        ".pth",
    }
)


def _cbse_classification(path: PurePosixPath) -> str | None:
    """Return a CBSE reason if ``path`` names an auto-exec/config surface.

    ``.git``/``.githooks`` components and any ``.pth`` file are structural and
    always flagged; the ``.claude`` segment specifically catches command hooks
    (``.claude/commands``). Callers decide whether an auto-load surface inside
    the declared write_scope is tolerated.
    """

    parts = path.parts
    for part in parts:
        if part in _CBSE_STRUCTURAL_SEGMENTS:
            return f"embedded git directory/hook path: {path.as_posix()}"
    name = path.name
    if name in _CBSE_AUTOLOAD_BASENAMES or name.endswith(".pth"):
        return f"auto-loaded config/manifest file: {path.as_posix()}"
    for part in parts[:-1]:
        if part in _CBSE_AUTOLOAD_SEGMENTS:
            return f"auto-activated config directory: {path.as_posix()}"
    return None


def scan_cbse_artifacts(
    worktree_root: Path,
    worker_paths: Sequence[PurePosixPath],
    scopes: Sequence[PurePosixPath],
    excluded: Sequence[PurePosixPath],
) -> None:
    """Refuse worker-planted CBSE auto-exec/config artifacts before integration.

    ``worker_paths`` is the union of every committed and uncommitted worker
    change. Two classes are refused fail-closed:

    * **Structural escapes** — a symlink (a trusted worker can create one after
      the launch-time no-follow audit), or an embedded ``.git``/``.githooks``
      path — regardless of scope. These can never legitimately be worker output.
    * **Auto-load surfaces** — venv/IDE/host config files an unsandboxed host
      would execute or import — only when they fall outside the declared
      write_scope. An in-scope surface was authorized by the packet; an
      out-of-scope one is exactly the CBSE plant this guard exists to stop, so
      it is blocked instead of being silently retained in the worktree.
    """

    root = _canonical_existing(Path(worktree_root), "worktree root")
    violations: list[str] = []
    for path in sorted(set(worker_paths), key=lambda item: item.as_posix()):
        if _is_contained(path, excluded):
            continue
        on_disk = root / path
        try:
            state = os.lstat(on_disk)
        except OSError:
            state = None
        if state is not None and stat.S_ISLNK(state.st_mode):
            violations.append(f"symlink in worker output: {path.as_posix()}")
            continue
        reason = _cbse_classification(path)
        if reason is None:
            continue
        structural = any(part in _CBSE_STRUCTURAL_SEGMENTS for part in path.parts)
        if structural or not _is_contained(path, scopes):
            violations.append(reason)
    if violations:
        raise WorktreeIsolationError(
            "worker planted configuration-based sandbox-escape (CBSE) artifacts "
            "outside the authorized scope: " + "; ".join(sorted(set(violations)))
        )


# Operator-authorized worker deletion (B-enumerated hybrid). The board's
# default remains a categorical refusal of every worker-committed `D`. The one
# authorized path is keyed on an EXACT file list the dispatcher pins into the
# verification contract, so it is covered by `verification_contract_sha256` and
# is exactly as unforgeable as `write_scope`: a worker editing its worktree copy
# of the packet changes nothing, because the controller reads the authorization
# from its own side and passes it in.
#
# `write_scope` is deliberately NOT deletion authority. A directory-form scope
# ("src/legacy/") authorizes ordinary mutation of everything beneath it; reading
# that as deletion authority would convert "may delete the approved files" into
# "may delete anything under the directory". The frozen list is the capability;
# the scope is only an upper bound on it.
_PATHSPEC_PATTERN_CHARACTERS = frozenset("*?[]\\")
# Regular file and executable file. A committed `120000` (symlink) or `160000`
# (gitlink/submodule) is never integrable worker output.
_INTEGRABLE_BLOB_MODES: frozenset[str] = frozenset({"100644", "100755"})


def _authorized_delete_path(value: str) -> PurePosixPath:
    """Normalize one authorization entry, rejecting anything not file-precise."""

    path = _normalized_relative(value, label="authorized delete path")
    text = path.as_posix()
    if value != text:
        raise WorktreeIsolationError(
            "authorized delete path is not in canonical repo-relative form "
            f"(a trailing slash or redundant segment names a directory, not a file): {value!r}"
        )
    if value.startswith(":") or any(
        character in _PATHSPEC_PATTERN_CHARACTERS for character in value
    ):
        raise WorktreeIsolationError(
            "authorized delete path must be a literal file path, not a pattern or "
            f"pathspec magic: {value!r}"
        )
    return path


def freeze_delete_authorization(
    repo_root: Path,
    base_commit: str,
    authorized_delete_paths: Sequence[str],
    scopes: Sequence[PurePosixPath],
    excluded: Sequence[PurePosixPath],
) -> tuple[PurePosixPath, ...]:
    """Resolve the controller's deletion capability against the immutable base.

    Enforces ``authorized_delete_paths ⊆ write_scope``,
    ``authorized_delete_paths ∩ exclude_paths = ∅``, and file-precision against
    the bound base tree: an entry that resolves to a tree (a directory the
    operator named by mistake) or to nothing at all is refused rather than
    silently authorizing whatever happens to sit at that path later. Bridge
    outputs (the return artifact and the response envelope) can never be
    authorized deletion targets, and neither can a structural CBSE path.
    """

    frozen: list[PurePosixPath] = []
    for value in authorized_delete_paths:
        path = _authorized_delete_path(value)
        text = path.as_posix()
        if not _is_contained(path, scopes):
            raise WorktreeIsolationError(
                f"authorized delete path is outside the declared write scope: {text}"
            )
        if _is_contained(path, excluded):
            raise WorktreeIsolationError(
                "authorized delete path is a bridge-owned output and can never be "
                f"an authorized deletion target: {text}"
            )
        if any(part in _CBSE_STRUCTURAL_SEGMENTS for part in path.parts):
            raise WorktreeIsolationError(
                f"authorized delete path is a structural git/hook path: {text}"
            )
        object_type = _run_git(
            ["cat-file", "-t", f"{base_commit}:{text}"],
            cwd=repo_root,
        )
        resolved_type = object_type.stdout.strip()
        if object_type.returncode != 0 or not resolved_type:
            raise WorktreeIsolationError(
                "authorized delete path is not tracked at the worktree base "
                f"commit: {text}"
            )
        if resolved_type != "blob":
            raise WorktreeIsolationError(
                "authorized delete path must name a file; it resolves to a "
                f"{resolved_type} at the worktree base: {text}"
            )
        frozen.append(path)
    if len(set(frozen)) != len(frozen):
        raise WorktreeIsolationError("authorized delete paths contain duplicate entries")
    return tuple(sorted(frozen, key=lambda item: item.as_posix()))


def _unauthorized_delete_error(
    unauthorized: Sequence[str],
    authorized: Sequence[PurePosixPath],
) -> WorktreeIsolationError:
    """Build the refusal so salvage is one glance, not an investigation.

    Naming ONLY the offending paths (the pre-authorization behavior) left an
    operator unable to tell "this delete was never approved" from "the approval
    list has a typo", so the authorized set is stated alongside the refusal.
    """

    authorized_text = (
        ", ".join(path.as_posix() for path in authorized) if authorized else "(none)"
    )
    return WorktreeIsolationError(
        "worker commit deletes are not authorized for board integration: "
        + ", ".join(unauthorized)
        + "; authorized deletions for this task: "
        + authorized_text
    )


def _reject_non_regular_committed_modes(
    repo_root: Path,
    commit: str,
    paths: Sequence[PurePosixPath],
    *,
    require_present: bool = False,
) -> None:
    """Refuse a committed symlink or gitlink, from committed state alone.

    ``scan_cbse_artifacts`` catches a symlink by ``lstat``-ing the worktree, so
    it only sees what is on disk at integration time. A worker that COMMITS a
    file->symlink typechange and then restores a regular file in its working
    tree defeats that check, and a typechange is recorded as ``T`` rather than
    ``D``, so it never reached the deletion gate either. Reading the mode out of
    the committed tree closes both: it is the tree that gets integrated, not the
    worktree.

    ``commit`` is one point in the audited history, never "the" worker state:
    integration ships a HISTORY, so every tree along it is delivered output.
    See :func:`_audited_worker_changes`, which applies this at every commit it
    walks.
    """

    if not paths:
        return
    listed = _run_git(
        [
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            commit,
            "--",
            *(f":(literal){path.as_posix()}" for path in paths),
        ],
        cwd=repo_root,
    )
    if listed.returncode != 0:
        raise WorktreeIsolationError(
            f"cannot inspect committed worker file modes: {listed.stderr.strip()}"
        )
    violations: list[str] = []
    seen: set[str] = set()
    for record in listed.stdout.split("\x00"):
        if not record or "\t" not in record:
            continue
        meta, _, raw_path = record.partition("\t")
        fields = meta.split()
        if len(fields) < 2:
            raise WorktreeIsolationError("git ls-tree returned malformed output")
        mode = fields[0]
        seen.add(raw_path)
        if mode not in _INTEGRABLE_BLOB_MODES:
            violations.append(f"{raw_path} (mode {mode})")
    if require_present:
        # Fail CLOSED. A path this commit changed to anything but `D` exists in
        # this commit's tree, so a missing `ls-tree` record means the lookup
        # itself failed -- a pathspec that did not match the way it was meant
        # to, say -- and an unmatched path silently passes a gate whose whole
        # job is to inspect it. Only the per-commit caller can assert this: the
        # head-tree pass is handed the UNION of non-`D` paths across the
        # history, where an authorized delete legitimately leaves no record.
        unresolved = tuple(
            sorted(path.as_posix() for path in paths if path.as_posix() not in seen)
        )
        if unresolved:
            raise WorktreeIsolationError(
                "cannot inspect committed worker file modes; these changed paths "
                "have no tree entry at the commit that changed them: "
                + ", ".join(unresolved)
            )
    if violations:
        raise WorktreeIsolationError(
            "worker committed a non-regular file (symlink, submodule, or other "
            "typechange), which is never integrable board output: "
            + ", ".join(sorted(violations))
        )


def _changed_records(
    repo_root: Path,
    base: str,
    head: str,
) -> tuple[tuple[str, PurePosixPath], ...]:
    completed = _run_git(
        ["diff", "--name-status", "-z", "--no-renames", base, head],
        cwd=repo_root,
    )
    if completed.returncode != 0:
        raise WorktreeIsolationError(
            f"cannot enumerate worker changes: {completed.stderr.strip()}"
        )
    fields = [item for item in completed.stdout.split("\x00") if item]
    if len(fields) % 2:
        raise WorktreeIsolationError("git diff returned malformed name-status output")
    records: list[tuple[str, PurePosixPath]] = []
    for offset in range(0, len(fields), 2):
        status = fields[offset]
        if not re.fullmatch(r"[A-Z]", status):
            raise WorktreeIsolationError(
                f"worker change has unsupported status: {status!r}"
            )
        records.append(
            (
                status,
                _normalized_relative(
                    fields[offset + 1],
                    label="worker changed path",
                ),
            )
        )
    return tuple(records)


def _audited_worker_changes(
    repo_root: Path,
    base: str,
    head: str,
) -> tuple[tuple[str, PurePosixPath], ...]:
    """Walk the worker's linear history, auditing every commit it will ship.

    The mode gate lives HERE, inside the walk, rather than at the call site on
    ``head``. Auditing only the head tree was a reproduced bypass: a worker
    committed a ``120000``/``160000`` entry for a base-tracked path and restored
    a regular blob in a later commit, leaving a clean worktree AND a clean head
    tree while the unsafe commit still entered the target's ancestry -- the
    fast-forward route makes the worker commits the target history verbatim, and
    the merge route keeps ``worker_head`` as a parent. Deleting the path at head
    laundered it the same way, with nothing left for a head ``ls-tree`` to see.

    Coupling the gate to the walk is the point: a caller cannot enumerate this
    history without every one of its trees being mode-audited, so the two can
    never drift apart again. Both integration routes consume this function, so
    the refusal is symmetric by construction.
    """

    listed = _run_git(
        ["rev-list", "--reverse", "--topo-order", f"{base}..{head}"],
        cwd=repo_root,
    )
    if listed.returncode != 0:
        raise WorktreeIsolationError(
            f"cannot enumerate worker commits: {listed.stderr.strip()}"
        )
    commits = tuple(item for item in listed.stdout.splitlines() if item)
    previous = base
    records: list[tuple[str, PurePosixPath]] = []
    for commit in commits:
        if not _OBJECT_ID_RE.fullmatch(commit):
            raise WorktreeIsolationError("worker history contains an invalid commit id")
        parent_result = _run_git(
            ["show", "-s", "--format=%P", commit],
            cwd=repo_root,
        )
        parents = parent_result.stdout.split()
        if parent_result.returncode != 0 or parents != [previous]:
            raise WorktreeIsolationError(
                "worker history must be linear from its bound base; merge or "
                "unrelated-parent commits are not integrable"
            )
        commit_records = _changed_records(repo_root, previous, commit)
        _reject_non_regular_committed_modes(
            repo_root,
            commit,
            tuple(
                sorted(
                    {path for status, path in commit_records if status != "D"},
                    key=lambda item: item.as_posix(),
                )
            ),
            require_present=True,
        )
        records.extend(commit_records)
        previous = commit
    if previous != head:
        raise WorktreeIsolationError("worker history does not terminate at worker HEAD")
    return tuple(records)


def _uncommitted_records(
    worktree_root: Path,
) -> tuple[tuple[str, PurePosixPath], ...]:
    """Worker residue as ``(XY, path)``, keeping git's two-column status code.

    ``X`` is HEAD-vs-index, ``Y`` is index-vs-worktree. Callers that only need
    the paths use :func:`_uncommitted_paths`; staging needs ``Y`` to tell an
    already-staged change from one that still has to be picked up.
    """

    completed = _run_git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=worktree_root,
    )
    if completed.returncode != 0:
        raise WorktreeIsolationError(
            f"cannot enumerate worker residue: {completed.stderr.strip()}"
        )
    fields = [item for item in completed.stdout.split("\x00") if item]
    records: list[tuple[str, PurePosixPath]] = []
    offset = 0
    while offset < len(fields):
        record = fields[offset]
        if len(record) < 4 or record[2] != " ":
            raise WorktreeIsolationError("git status returned malformed porcelain output")
        code = record[:2]
        records.append(
            (code, _normalized_relative(record[3:], label="uncommitted worker path"))
        )
        if code in {"R ", "C ", " R", " C"}:
            offset += 1
            if offset >= len(fields):
                raise WorktreeIsolationError(
                    "git status returned an incomplete rename record"
                )
            records.append(
                (
                    code,
                    _normalized_relative(
                        fields[offset], label="uncommitted worker path"
                    ),
                )
            )
        offset += 1
    return tuple(records)


def _uncommitted_paths(worktree_root: Path) -> tuple[PurePosixPath, ...]:
    return tuple(path for _code, path in _uncommitted_records(worktree_root))


def commit_worker_residue(
    handle: WorktreeHandle,
    write_scope: Sequence[str],
    *,
    exclude_paths: Sequence[str] = (),
) -> tuple[str, ...]:
    """Commit the in-scope working-tree residue a worker left behind.

    Integration only ever moves *committed* worker history, but a specialist
    CLI edits files -- it does not commit them. Without this step every task
    that touches real code ends in "worker left uncommitted in-scope code
    changes", the supervisor blocks after provisioning, and the finished
    response is stranded in the worktree.

    The controller commits, not the worker, so the scope is the dispatcher's
    declared ``write_scope`` rather than whatever the worker chose to stage.
    The commit is pathspec-limited for exactly that reason: a bare commit
    would sweep in anything the worker staged outside its scope, and the
    out-of-scope and delete gates downstream would then reject work that was
    otherwise clean. Paths outside the scope, and the bridge-owned outputs in
    ``exclude_paths``, are deliberately left dirty and contained.

    Returns the repo-relative paths that were committed, in sorted order.
    """

    _validate_task_attempt(handle.task_id, handle.attempt_id)
    repo_root = _canonical_existing(handle.repo_root, "repo root")
    worktree_root = worktree_write_scope_paths(handle.worktree_root, repo_root)[0]
    scopes = tuple(
        _normalized_relative(item, label="write scope") for item in write_scope
    )
    excluded = tuple(
        _normalized_relative(item, label="excluded bridge path")
        for item in exclude_paths
    )
    if not scopes:
        raise WorktreeIsolationError("integration write scope is empty")
    current_worker_branch = _run_git(
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=worktree_root,
    )
    if (
        current_worker_branch.returncode != 0
        or current_worker_branch.stdout.strip() != handle.branch
    ):
        raise WorktreeIsolationError("worker worktree is detached or changed branches")

    in_scope = tuple(
        (code, path.as_posix())
        for code, path in _uncommitted_records(worktree_root)
        if _is_contained(path, scopes) and not _is_contained(path, excluded)
    )
    residue = tuple(sorted({path for _code, path in in_scope}))
    if not residue:
        return ()

    # A pathspec given to `git add` is matched against the index and the
    # working tree, never against HEAD alone. A worker that removed a file
    # with `git rm` leaves it in neither, so the pathspec matched nothing and
    # git failed the whole staging step with exit 128 -- taking every finished
    # task that deletes a file down with it. Such a path is already staged
    # (worktree column ' '), so it needs no `add` at all; it only has to stay
    # in the commit pathspec below. `-A` then makes the index match the
    # working tree for the paths that do still need picking up, which is what
    # records an unstaged deletion. Both lists remain pathspec-limited to the
    # declared scope: this makes an in-scope deletion stageable without
    # widening which paths are eligible.
    stageable = sorted({path for code, path in in_scope if code[1] != " "})
    literal_residue = [f":(literal){path}" for path in residue]
    if stageable:
        staged = _run_git(
            ["add", "-A", "--", *(f":(literal){path}" for path in stageable)],
            cwd=worktree_root,
        )
        if staged.returncode != 0:
            raise WorktreeIsolationError(
                f"cannot stage worker residue: {staged.stderr.strip()}"
            )
    pending = _run_git(
        ["diff", "--cached", "--quiet", "HEAD", "--", *literal_residue],
        cwd=worktree_root,
    )
    if pending.returncode not in {0, 1}:
        raise WorktreeIsolationError(
            f"cannot inspect staged worker residue: {pending.stderr.strip()}"
        )
    if pending.returncode == 0:
        return ()
    committed = _run_git(
        [
            "commit",
            "-q",
            "-m",
            f"board: worker residue for {handle.task_id} ({handle.attempt_id})",
            "--",
            *literal_residue,
        ],
        cwd=worktree_root,
    )
    if committed.returncode != 0:
        raise WorktreeIsolationError(
            f"cannot commit worker residue: {committed.stderr.strip()}"
        )
    return residue


def integrate_worktree_commits(
    handle: WorktreeHandle,
    write_scope: Sequence[str],
    *,
    exclude_paths: Sequence[str] = (),
    authorized_delete_paths: Sequence[str] = (),
    target_branch: str = "v2",
) -> WorktreeIntegrationReceipt:
    """Atomically integrate only committed, declared-scope worker changes.

    The worktree base is immutable. Under one controller lock, the entire
    declared scope on ``target_branch`` must still match that base. Every
    committed worker change must be in scope, distinct from bridge-owned
    outputs, and either non-deleting or named in ``authorized_delete_paths``;
    out-of-scope dirty probes are retained only in the isolated worktree and
    reported. If the target advanced on disjoint paths, an off-worktree merge
    commit retains the original worker commits as ancestors. Git's normal
    index/ref locks make the final fast-forward the single visible branch
    transition.

    ``authorized_delete_paths`` defaults to empty, so the default behavior is
    the categorical refusal of every worker-committed deletion. It must be
    supplied by the CONTROLLER from its own copy of the dispatcher-pinned
    verification contract — never read from the worktree, which the worker can
    edit. See :func:`freeze_delete_authorization` for what an entry must satisfy.
    """

    _validate_task_attempt(handle.task_id, handle.attempt_id)
    if target_branch != os.environ.get("SQUAD_BASE_BRANCH", "v2"):
        raise WorktreeIsolationError(
            f"board integration target must be {os.environ.get('SQUAD_BASE_BRANCH', 'v2')}"
        )
    repo_root = _canonical_existing(handle.repo_root, "repo root")
    worktree_root = worktree_write_scope_paths(handle.worktree_root, repo_root)[0]
    scopes = tuple(
        _normalized_relative(item, label="write scope") for item in write_scope
    )
    excluded = tuple(
        _normalized_relative(item, label="excluded bridge path")
        for item in exclude_paths
    )
    if not scopes:
        raise WorktreeIsolationError("integration write scope is empty")
    if not handle.base_commit or _resolve_commit(repo_root, handle.base_commit) != handle.base_commit:
        raise WorktreeIsolationError("worktree handle has no valid immutable base commit")
    # Freeze the deletion capability against the immutable base BEFORE any
    # worker state is consulted, so the authorized set can never be a function
    # of what the worker did.
    authorized_deletes = freeze_delete_authorization(
        repo_root,
        handle.base_commit,
        authorized_delete_paths,
        scopes,
        excluded,
    )
    authorized_delete_strings = tuple(path.as_posix() for path in authorized_deletes)
    current_worker_branch = _run_git(
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=worktree_root,
    )
    if (
        current_worker_branch.returncode != 0
        or current_worker_branch.stdout.strip() != handle.branch
    ):
        raise WorktreeIsolationError("worker worktree is detached or changed branches")
    worker_head = _resolve_commit(worktree_root, "HEAD")
    ancestry = _run_git(
        ["merge-base", "--is-ancestor", handle.base_commit, worker_head],
        cwd=repo_root,
    )
    if ancestry.returncode != 0:
        raise WorktreeIsolationError("worker history does not descend from its bound base")

    common = git_common_dir(repo_root)
    lock_path = common / "board-integration.lock"
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        current_target_branch = _run_git(
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=repo_root,
        )
        if (
            current_target_branch.returncode != 0
            or current_target_branch.stdout.strip() != target_branch
        ):
            raise WorktreeIsolationError(
                f"integration repo is not checked out on {target_branch}"
            )
        target_before = _resolve_commit(repo_root, f"refs/heads/{target_branch}")
        target_ancestry = _run_git(
            ["merge-base", "--is-ancestor", handle.base_commit, target_before],
            cwd=repo_root,
        )
        if target_ancestry.returncode != 0:
            raise WorktreeIsolationError(
                "target branch no longer descends from the worktree base"
            )
        scope_strings = [path.as_posix() for path in scopes]
        literal_scopes = [f":(literal){path}" for path in scope_strings]
        scope_drift = _run_git(
            [
                "diff",
                "--quiet",
                handle.base_commit,
                target_before,
                "--",
                *literal_scopes,
            ],
            cwd=repo_root,
        )
        if scope_drift.returncode not in {0, 1}:
            raise WorktreeIsolationError(
                f"cannot verify target write scope: {scope_drift.stderr.strip()}"
            )
        if scope_drift.returncode == 1:
            raise WorktreeIsolationError(
                "target write scope changed since the worker worktree was created"
            )
        changed = _audited_worker_changes(
            repo_root,
            handle.base_commit,
            worker_head,
        )

        def selected(path: PurePosixPath) -> bool:
            return _is_contained(path, scopes) and not _is_contained(path, excluded)

        def authorized_delete(path: PurePosixPath) -> bool:
            return path in authorized_deletes

        committed_out_of_scope = tuple(
            sorted(path.as_posix() for _status, path in changed if not selected(path))
        )
        if committed_out_of_scope:
            raise WorktreeIsolationError(
                "worker committed paths outside the integration scope or bridge-owned "
                "outputs: " + ", ".join(committed_out_of_scope)
            )
        deleted_paths = tuple(
            sorted(path.as_posix() for status, path in changed if status == "D")
        )
        unauthorized_deletes = tuple(
            sorted(
                path.as_posix()
                for status, path in changed
                if status == "D" and not authorized_delete(path)
            )
        )
        if unauthorized_deletes:
            raise _unauthorized_delete_error(unauthorized_deletes, authorized_deletes)
        integrated_paths = tuple(
            sorted({path.as_posix() for _status, path in changed})
        )
        worker_residue = _uncommitted_paths(worktree_root)
        # CBSE gate: refuse worker-planted auto-exec/config artifacts (symlinks,
        # embedded .git/hooks, venv/IDE/host config) across every committed and
        # uncommitted change before any branch mutation. This runs before the
        # ff-merge so a config-based sandbox-escape plant is surfaced to the
        # operator, never integrated onto the target branch, and never left
        # dormant in a worktree a later host git op might trip over.
        scan_cbse_artifacts(
            worktree_root,
            tuple(path for _status, path in changed) + tuple(worker_residue),
            scopes,
            excluded,
        )
        # Typechange gate, from committed state. A `T` record (for example
        # file->symlink) is not a `D`, so the deletion gate never saw it, and
        # the CBSE scan above reads the worktree rather than the tree that is
        # about to be integrated.
        #
        # The AUTHORITATIVE application of this gate is inside
        # `_audited_worker_changes`, at every commit in the shipped history.
        # This head-tree pass is defense in depth, and is honestly redundant
        # TODAY: given a history proven linear and proven to terminate at
        # `worker_head`, any non-regular mode at head was necessarily recorded
        # as a non-`D` change in the commit that introduced it, so the walk
        # already refused it. Removing it breaks no test. It is kept because it
        # costs one `ls-tree` and it stops being redundant the moment either of
        # those two proofs is weakened -- which is exactly how the head-only
        # check became a bypass in the first place.
        _reject_non_regular_committed_modes(
            repo_root,
            worker_head,
            tuple(
                sorted(
                    {path for status, path in changed if status != "D"},
                    key=lambda item: item.as_posix(),
                )
            ),
        )
        invalid_residue = tuple(
            sorted(
                path.as_posix()
                for path in worker_residue
                if _is_contained(path, scopes)
                and not _is_contained(path, excluded)
            )
        )
        if invalid_residue:
            raise WorktreeIsolationError(
                "worker left uncommitted in-scope code changes: "
                + ", ".join(invalid_residue)
            )
        uncommitted_excluded_paths = tuple(
            sorted(
                path.as_posix()
                for path in worker_residue
                if not _is_contained(path, scopes)
                and not _is_contained(path, excluded)
            )
        )
        if not integrated_paths:
            return WorktreeIntegrationReceipt(
                status="no-committed-in-scope-changes",
                task_id=handle.task_id,
                base_commit=handle.base_commit,
                worker_head=worker_head,
                target_before=target_before,
                target_after=target_before,
                integration_commit=target_before,
                exact_worker_history=False,
                integrated_paths=(),
                excluded_paths=(),
                uncommitted_excluded_paths=uncommitted_excluded_paths,
                deleted_paths=(),
                authorized_delete_paths=authorized_delete_strings,
            )

        literal_integrated = [f":(literal){path}" for path in integrated_paths]
        dirty_integrated = _run_git(
            [
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *literal_integrated,
            ],
            cwd=repo_root,
        )
        if dirty_integrated.returncode != 0:
            raise WorktreeIsolationError(
                f"cannot inspect target worktree state: {dirty_integrated.stderr.strip()}"
            )
        if dirty_integrated.stdout:
            raise WorktreeIsolationError(
                "target worktree has uncommitted changes on worker integration paths"
            )

        exact_worker_history = target_before == handle.base_commit
        if exact_worker_history:
            integration_commit = worker_head
        else:
            merged_tree = _run_git(
                ["merge-tree", "--write-tree", target_before, worker_head],
                cwd=repo_root,
            )
            tree_id = merged_tree.stdout.splitlines()[0].strip()
            if merged_tree.returncode != 0 or not _OBJECT_ID_RE.fullmatch(tree_id):
                raise WorktreeIsolationError(
                    "worker changes conflict with current target: "
                    + merged_tree.stderr.strip()
                )
            message = (
                f"board integrate {handle.task_id}\n\n"
                f"Worker-Head: {worker_head}\n"
                f"Worker-Base: {handle.base_commit}\n"
            )
            created = _run_git(
                [
                    "commit-tree",
                    tree_id,
                    "-p",
                    target_before,
                    "-p",
                    worker_head,
                    "-m",
                    message,
                ],
                cwd=repo_root,
            )
            integration_commit = created.stdout.strip()
            if created.returncode != 0 or not _OBJECT_ID_RE.fullmatch(integration_commit):
                raise WorktreeIsolationError(
                    f"cannot create filtered integration commit: {created.stderr.strip()}"
                )
            integration_diff = _changed_records(
                repo_root,
                target_before,
                integration_commit,
            )
            # Symmetry with the worker-history audit above. These two checks
            # used to disagree: the fast-forward case (target_before ==
            # base_commit) is governed ONLY by the history audit, the merge
            # case by both, so a divergent rule would make a worker's outcome
            # depend on whether v2 happened to advance concurrently on
            # unrelated paths. Same predicate, same refusal, either route.
            merge_unauthorized_deletes = tuple(
                sorted(
                    path.as_posix()
                    for status, path in integration_diff
                    if status == "D" and not authorized_delete(path)
                )
            )
            if merge_unauthorized_deletes:
                raise _unauthorized_delete_error(
                    merge_unauthorized_deletes, authorized_deletes
                )
            unexpected = tuple(
                sorted(
                    path.as_posix()
                    for _status, path in integration_diff
                    if not selected(path)
                )
            )
            if unexpected:
                raise WorktreeIsolationError(
                    "prepared integration commit escapes write scope: "
                    + ", ".join(unexpected)
                )

        if _resolve_commit(repo_root, f"refs/heads/{target_branch}") != target_before:
            raise WorktreeIsolationError(
                "target branch advanced concurrently before atomic integration"
            )
        merged = _run_git(
            ["merge", "--ff-only", "--no-edit", integration_commit],
            cwd=repo_root,
            timeout=30,
        )
        if merged.returncode != 0:
            target_after_failure = _resolve_commit(
                repo_root, f"refs/heads/{target_branch}"
            )
            if target_after_failure != target_before:
                raise WorktreeIsolationError(
                    "integration failed after the target branch moved concurrently"
                )
            raise WorktreeIsolationError(
                f"atomic integration failed before the branch commit point: "
                f"{merged.stderr.strip()}"
            )
        target_after = _resolve_commit(repo_root, f"refs/heads/{target_branch}")
        if target_after != integration_commit:
            raise WorktreeIsolationError("integration did not land the expected commit")
        return WorktreeIntegrationReceipt(
            status="integrated",
            task_id=handle.task_id,
            base_commit=handle.base_commit,
            worker_head=worker_head,
            target_before=target_before,
            target_after=target_after,
            integration_commit=integration_commit,
            exact_worker_history=exact_worker_history,
            integrated_paths=integrated_paths,
            excluded_paths=(),
            uncommitted_excluded_paths=uncommitted_excluded_paths,
            deleted_paths=deleted_paths,
            authorized_delete_paths=authorized_delete_strings,
        )
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def linked_worktree_commit_write_dirs(
    handle: WorktreeHandle,
) -> tuple[Path, ...]:
    """Return the narrow shared-Git directories needed for a worker commit.

    Codex's own workspace sandbox can already write the linked worktree files,
    but Git stores its linked index/HEAD, loose objects, branch lock, and
    reflogs in the main repository's common directory. This derives only the
    current attempt's metadata/branch directories plus the shared object store;
    it never grants the integration ref directory.
    """

    repo_root = _canonical_existing(handle.repo_root, "repo root")
    worktree_root = worktree_write_scope_paths(handle.worktree_root, repo_root)[0]
    common = git_common_dir(repo_root)
    git_dir_result = _run_git(["rev-parse", "--git-dir"], cwd=worktree_root)
    raw_git_dir = Path(git_dir_result.stdout.strip())
    if git_dir_result.returncode != 0 or not str(raw_git_dir):
        raise WorktreeIsolationError("cannot resolve linked worktree git directory")
    if not raw_git_dir.is_absolute():
        raw_git_dir = worktree_root / raw_git_dir
    linked_git_dir = Path(os.path.realpath(raw_git_dir))
    expected_parent = common / "worktrees"
    if (
        linked_git_dir.parent != expected_parent
        or linked_git_dir.name != handle.attempt_id
        or not linked_git_dir.is_dir()
    ):
        raise WorktreeIsolationError(
            "linked worktree metadata does not match the authenticated attempt"
        )
    branch_result = _run_git(
        ["symbolic-ref", "--quiet", "HEAD"],
        cwd=worktree_root,
    )
    expected_ref = f"refs/heads/{handle.branch}"
    if branch_result.returncode != 0 or branch_result.stdout.strip() != expected_ref:
        raise WorktreeIsolationError("linked worktree branch identity changed")
    branch_path = common / PurePosixPath(expected_ref)
    reflog_path = common / "logs" / PurePosixPath(expected_ref)
    if not branch_path.is_file() or not reflog_path.is_file():
        raise WorktreeIsolationError("linked worktree branch metadata is incomplete")
    objects = common / "objects"
    if not objects.is_dir():
        raise WorktreeIsolationError("shared Git object directory is unavailable")
    return (
        linked_git_dir,
        objects,
        branch_path.parent,
        reflog_path.parent,
    )


def to_board_task(
    handle: WorktreeHandle,
    *,
    write_paths: Sequence[str] = (),
    read_paths: Sequence[str] = (),
    depends_on: Sequence["board_router.DepEdge"] = (),
    priority: int = 0,
) -> "board_router.BoardTask":
    """Build a Task-2.1 ``BoardTask`` for a provisioned worktree.

    The handle's own worktree root is re-validated as a real, currently
    registered git worktree (never the shared git directory or a path
    inside it) on every call — this rejects fabricated or stale handles
    before they ever reach the scheduler. Any caller-supplied
    ``write_paths`` must equal that validated scope exactly; a mismatch
    (shared git state, a sibling worktree, a relative path, a symlink
    escape, or anything else) is rejected rather than silently trusted,
    since the scheduler treats ``BoardTask.write_paths`` as the claimed
    write scope.

    Attaches read-only claims on every shared git resource class: a
    worktree task may legitimately need to observe shared git state (log,
    diff, fetch info), but mode="read" is the only mode ever declared here
    — writes are denied at the OS level by ``compile_worktree_profile``
    regardless of what any caller declares, so this is defense-in-depth,
    not the primary enforcement.
    """

    validated_root = worktree_write_scope_paths(handle.worktree_root, handle.repo_root)[0]
    resolved_write_paths = tuple(write_paths) if write_paths else (str(validated_root),)
    for candidate in resolved_write_paths:
        if candidate != str(validated_root):
            raise WorktreeIsolationError(
                f"write path is not the validated worktree scope for {handle.task_id}: "
                f"{candidate!r} != {str(validated_root)!r}"
            )
    resources = tuple(
        board_router.ResourceClaim(
            resource_class=resource_class, target=str(handle.repo_root), mode="read"
        )
        for resource_class in GIT_RESOURCE_CLASSES
    )
    return board_router.BoardTask(
        task_id=handle.task_id,
        write_paths=resolved_write_paths,
        read_paths=tuple(read_paths),
        depends_on=tuple(depends_on),
        resources=resources,
        worktree_root=str(validated_root),
        metadata_complete=True,
        priority=priority,
    )


def compile_worktree_profile(
    worktree_root: Path,
    repo_root: Path,
    *,
    executable_paths: Sequence[Path] = (Path("/bin/sh"), Path("/bin/bash")),
    broker_port: int | None = None,
) -> CompiledProfile:
    """Compile a deny-default Seatbelt profile scoped to exactly one worktree."""

    scope = worktree_write_scope_paths(worktree_root, repo_root)
    return compile_profile(
        ProfileSpec(
            write_paths=scope,
            executable_paths=tuple(executable_paths),
            broker_port=broker_port,
        )
    )


def assert_write_effect(profile: CompiledProfile, target: Path, *, allowed: bool) -> None:
    """Attempt a real write to ``target`` under ``profile`` and prove the OS effect.

    Mirrors ``launch_hygiene.run_preflight_canary``'s own denial formula
    exactly: denied means non-zero exit, the target was never created or
    modified, and the kernel's own permission-denial text is present.
    """

    target_path = Path(target)
    before_exists = target_path.exists()
    before_state = target_path.stat() if before_exists else None
    completed = run_sanitized(
        ["/bin/sh", "-c", 'printf probe-write >> "$1"', "sh", str(target_path)],
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
        cwd=target_path.parent if target_path.parent.exists() else Path("/"),
        timeout=5,
        profile=profile,
    )
    after_exists = target_path.exists()
    unchanged = before_exists == after_exists and (
        not after_exists or (before_state is not None and target_path.stat().st_mtime_ns == before_state.st_mtime_ns)
    )
    if allowed:
        if completed.returncode != 0 or not after_exists:
            raise WorktreeIsolationError(
                f"expected write to be allowed but it was denied: {target_path}: {completed.stderr.strip()}"
            )
    else:
        denied = completed.returncode != 0 and unchanged and "Operation not permitted" in completed.stderr
        if not denied:
            raise WorktreeIsolationError(
                f"expected write to be DENIED but it was not: {target_path}: "
                f"rc={completed.returncode} unchanged={unchanged} stderr={completed.stderr.strip()!r}"
            )


__all__ = [
    "GIT_RESOURCE_CLASSES",
    "WorktreeIsolationError",
    "WorktreeHandle",
    "WorktreeIntegrationReceipt",
    "WorktreePool",
    "git_common_dir",
    "worktree_write_scope_paths",
    "scan_cbse_artifacts",
    "freeze_delete_authorization",
    "integrate_worktree_commits",
    "linked_worktree_commit_write_dirs",
    "to_board_task",
    "compile_worktree_profile",
    "assert_write_effect",
]
