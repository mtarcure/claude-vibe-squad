#!/usr/bin/env python3
"""Static checks for two defect shapes that "0 bare except:" cannot catch.

Plan A found a daemon that lied about its own health with no bare `except`
anywhere in the path: `daemon/main.py` fires the outbox watcher with
`asyncio.create_task(...)` and never wires a done-callback, so an exception
inside the watcher is invisible for the rest of the process's life -- asyncio
only logs "Task exception was never retrieved" when the task is garbage
collected, and a task pinned by a live local (as this one is, for the whole
app lifetime) is never collected. Meanwhile `daemon/watcher.py` defaulted
`VAULT_ROOT` to the maintainer's own home-relative path, so a clone on a
different machine silently creates and watches a phantom directory instead
of failing loudly.

Both shapes are ordinary, exception-free control flow -- no linter that
counts `except` clauses (bare or otherwise) will ever see them. These two
checks look at what the code *doesn't* do instead:

  * ``dangling-create-task`` -- two shapes, both under this one rule id
    because they're the same underlying defect (a task's exception has no
    path back to anything that logs or re-raises it):

    1. A name bound to the result of ``asyncio.create_task`` /
       ``asyncio.ensure_future`` (any receiver, so ``loop.create_task`` counts
       too) with no ``<name>.add_done_callback(...)`` anywhere in the same
       function/module scope. Chained use
       (``asyncio.create_task(x).add_done_callback(cb)``) is exempt -- it was
       never assigned to a name in the first place, so there is nothing to
       lose track of. An eventual bare ``await`` on the stored name is *not*
       treated as sufficient: that is exactly the pattern `daemon/main.py`
       already had (an `await` in the `lifespan` shutdown `finally`) and it
       is still the bug, because the exception stays invisible for the
       task's entire live duration and only surfaces at process shutdown.
    2. A bare, unassigned ``asyncio.create_task(coro())`` used as a
       standalone statement -- arguably worse than (1): nothing holds a
       reference at all, so the task also carries early-GC risk on top of
       the invisible-exception problem. This is the rule's textbook case and
       was a false negative until 2026-08-17 (only assignment forms were
       checked); adding it uncovered a coupled false positive on
       ``asyncio.TaskGroup``, fixed in the same pass -- see below.

    **Exempt: ``asyncio.TaskGroup``.** ``tg.create_task(...)`` inside
    ``async with asyncio.TaskGroup() as tg:`` is not flagged in either
    stored or bare form. A ``TaskGroup`` re-raises every child task's
    exception itself when the ``async with`` block exits (`PEP 654`
    structured concurrency, Python 3.11+) -- neither a stored reference nor
    a done-callback is needed for the exception to surface. The exemption is
    computed once per file by matching the exact ``<name>.create_task(...)``
    call nodes whose receiver name is bound by a literal ``TaskGroup(...)``
    ``async with`` in the same statement tree -- matched by name and AST
    shape, not by binding, which is exactly the tradeoff the rest of this
    module already makes and already accepts two gaps for below: a
    same-named shadowed identifier and an intermediate-variable indirection.
    No ``TaskGroup`` exists in this repo today, but the false positive would
    have been silent until someone adopted one.

  * ``home-relative-env-default`` -- ``os.environ.get(KEY, default)`` /
    ``os.getenv(KEY, default)`` where the *default* expression anchors on
    ``Path.home()`` / ``.expanduser()`` and then joins a hardcoded, non-dotfile
    string literal directly onto it (``Path.home()`` joined with a literal
    ``"Obsidian-Claude-Vibe-Squad"`` segment,
    ``os.path.join(str(Path.home()), "SomeRepo")``, and similar). Two shapes
    are deliberately *not* flagged:

    - A bare ``Path.home()`` / ``expanduser("~")`` with no extra literal
      segment at all -- it resolves to the user's actual home directory, not
      a phantom subdirectory baked in by whoever wrote the default.
    - A segment starting with ``.`` immediately joined onto the anchor
      (``Path.home() / ".config" / "chrome" / "tabs.json"``) -- that is the
      ordinary XDG-style "optional, user-scoped app config" idiom, not a
      maintainer's own repo/project path leaking into a default. This
      exemption exists because `scripts/python/browser_keep_alive.py`
      defaults `CHRONO_BROWSER_TABS_FILE` to exactly this shape for an
      intentionally optional, read-only, missing-file-tolerant config file --
      an unqualified "any literal after Path.home()" rule flagged it as a
      false positive during this checker's own rollout (2026-08-17). What
      distinguishes the real defect is not "joins a literal onto home" but
      "defaults an installation root -- something later mkdir'd or otherwise
      load-bearing -- to the maintainer's own directory name."

Both checks are pure `ast` analysis: no imports are resolved, so `Path` /
`os` / `environ` are matched by attribute/name shape, not by binding.

Known, accepted gaps (found in review, deliberately not fixed -- recorded
here so they're known rather than hidden):

  * **Delegated callback attachment.** If a codebase wires
    `t.add_done_callback(cb)` through a shared helper --
    `background_tasks.attach(t)` where `attach` itself calls
    `add_done_callback` -- `dangling-create-task` still flags `t` at the
    call site, because scope-local text matching can't see through the
    helper. Scope-local counting is intentional (see the module-level
    design note above this list), not an oversight; a codebase that adopts
    such a helper needs a per-repo suppression, not a change to this rule.
  * **Real, non-app OS folders under home.** `home-relative-env-default`
    only exempts a *dotfile*-prefixed immediate segment
    (`Path.home() / ".config" / ...`). `Path.home() / "Downloads"` or
    `Path.home() / "Desktop"` -- real, standard OS folders with no leading
    dot -- still flag, indistinguishable at the AST level from `Path.home()`
    joined with the literal `"Obsidian-Claude-Vibe-Squad"` segment (the
    actual defect shape).
  * **Unbound `.environ` attribute.** `_is_environ_get_call` matches any
    `<expr>.environ.get(...)`, including `self.environ.get(...)` on a class
    whose `environ` attribute is an unrelated dict that merely happens to
    share `os.environ`'s name -- no import/type resolution backs the match.
  * **TaskGroup exemption: shadowed-identifier leak.** The exemption in (2)
    above matches by receiver *name*, and `ast.walk` sweeps every nested
    function body inside the `async with` subtree. So
    `async with asyncio.TaskGroup() as tg: def helper(tg): tg.create_task(x)`
    wrongly exempts `helper`'s `tg.create_task(...)` even though that `tg`
    is an unrelated parameter shadowing the TaskGroup name, not the
    TaskGroup itself.
  * **TaskGroup exemption: intermediate-variable false positive.** The
    exemption only fires when `context_expr` is itself a literal
    `TaskGroup(...)` call. `group = asyncio.TaskGroup()` followed by
    `async with group as tg: tg.create_task(...)` still flags as
    `dangling-create-task`, because `context_expr` there is the `Name`
    `group`, not a `TaskGroup(...)` `Call` node.

  Both TaskGroup gaps are the same "matched by name/shape, not by binding"
  tradeoff as the rest of this list -- a deliberate boundary of pure `ast`
  analysis, not an oversight, and not worth scope-aware binding analysis for
  a construct with zero current usage in this repo.

Run directly to scan the repository's git-tracked `*.py` files:

    python3 scripts/python/state_lint.py

Exit status is 1 if any violation is found, 0 otherwise. `find_violations`
is the importable entry point for callers (including this module's own
tests) that want to scan a specific file or in-memory source instead.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_root import resolve_vault_root  # noqa: E402


DANGLING_CREATE_TASK = "dangling-create-task"
HOME_RELATIVE_ENV_DEFAULT = "home-relative-env-default"

_TASK_FACTORY_ATTRS = {"create_task", "ensure_future"}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    col: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: [{self.rule}] {self.message}"


def _unparse(node: ast.AST) -> str | None:
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _is_task_factory_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in _TASK_FACTORY_ATTRS
    if isinstance(func, ast.Name):
        return func.id in _TASK_FACTORY_ATTRS
    return False


def _taskgroup_exempt_call_ids(tree: ast.AST) -> set[int]:
    """id() of every `<name>.create_task(...)` / `<name>.ensure_future(...)`
    Call node whose receiver `<name>` is bound by
    `async with (asyncio.)?TaskGroup(...) as <name>:` in the same statement
    tree. A TaskGroup re-raises every child task's exception itself when the
    `async with` block exits, so neither a stored reference nor a
    done-callback is needed -- see the module docstring."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncWith):
            continue
        for item in node.items:
            ctx, var = item.context_expr, item.optional_vars
            if not (isinstance(ctx, ast.Call) and isinstance(var, ast.Name)):
                continue
            func = ctx.func
            is_taskgroup = (isinstance(func, ast.Attribute) and func.attr == "TaskGroup") or (
                isinstance(func, ast.Name) and func.id == "TaskGroup"
            )
            if not is_taskgroup:
                continue
            tg_name = var.id
            for sub in ast.walk(node):  # the whole `async with`, body included
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in _TASK_FACTORY_ATTRS
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == tg_name
                ):
                    exempt.add(id(sub))
    return exempt


@dataclass
class _Scope:
    node: ast.AST
    callback_targets: set[str] = field(default_factory=set)
    # (target key, the create_task/ensure_future Call node) pairs bound
    # directly in this scope's own statements (nested functions get their
    # own _Scope, so their assignments are not recorded here).
    pending: list[tuple[str, ast.Call]] = field(default_factory=list)


class _ScopeCollector(ast.NodeVisitor):
    """Walk the tree once, bucketing create_task assignments and
    add_done_callback receivers by their enclosing function/module scope,
    plus every bare (unassigned) create_task/ensure_future statement found
    anywhere -- those need no scope, since there's no name to search a
    callback for."""

    def __init__(self, exempt_call_ids: set[int]) -> None:
        self.scopes: list[_Scope] = []
        self.bare_hits: list[ast.Call] = []
        self._exempt_call_ids = exempt_call_ids
        self._stack: list[_Scope] = []

    def _enter_scope(self, node: ast.AST) -> None:
        scope = _Scope(node=node)
        self.scopes.append(scope)
        self._stack.append(scope)
        self.generic_visit(node)
        self._stack.pop()

    def visit_Module(self, node: ast.Module) -> None:
        self._enter_scope(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_scope(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            self._stack
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_done_callback"
        ):
            key = _unparse(node.func.value)
            if key:
                self._stack[-1].callback_targets.add(key)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_assignment(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._record_assignment([node.target], node.value)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        value = node.value
        if (
            isinstance(value, ast.Call)
            and _is_task_factory_call(value)
            and id(value) not in self._exempt_call_ids
        ):
            self.bare_hits.append(value)
        self.generic_visit(node)

    def _record_assignment(self, targets: list[ast.AST], value: ast.AST) -> None:
        if not self._stack or not isinstance(value, ast.Call) or not _is_task_factory_call(value):
            return
        if id(value) in self._exempt_call_ids:
            return
        if len(targets) != 1:
            return  # tuple/multi-target assigns: skip rather than guess
        key = _unparse(targets[0])
        if key is None:
            return
        self._stack[-1].pending.append((key, value))


def check_dangling_create_task(tree: ast.AST) -> list[tuple[int, int, str, str]]:
    """Return (line, col, target, kind) hits. kind is "stored" for a name
    bound to create_task with no matching add_done_callback in the same
    function/module scope, or "bare" for a create_task result never
    assigned to anything at all."""
    exempt = _taskgroup_exempt_call_ids(tree)
    collector = _ScopeCollector(exempt)
    collector.visit(tree)
    hits: list[tuple[int, int, str, str]] = []
    for scope in collector.scopes:
        for key, call_node in scope.pending:
            if key not in scope.callback_targets:
                hits.append((call_node.lineno, call_node.col_offset, key, "stored"))
    for call_node in collector.bare_hits:
        hits.append((call_node.lineno, call_node.col_offset, "", "bare"))
    return hits


def _is_environ_get_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "get":
        value = func.value
        if isinstance(value, ast.Attribute) and value.attr == "environ":
            return True  # os.environ.get(...)
        if isinstance(value, ast.Name) and value.id == "environ":
            return True  # environ.get(...) via `from os import environ`
        return False
    if isinstance(func, ast.Attribute) and func.attr == "getenv":
        return True  # os.getenv(...)
    if isinstance(func, ast.Name) and func.id == "getenv":
        return True  # getenv(...) via `from os import getenv`
    return False


def _extract_default_arg(node: ast.Call) -> ast.AST | None:
    if len(node.args) >= 2:
        return node.args[1]
    for kw in node.keywords:
        if kw.arg == "default":
            return kw.value
    return None


def _home_anchor_calls(node: ast.AST) -> list[ast.Call]:
    """Find Path.home() / *.expanduser(...) calls within `node`."""
    anchors = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "home" and not n.args and not n.keywords:
                anchors.append(n)
            elif n.func.attr == "expanduser":
                anchors.append(n)
    return anchors


def _contains_node(haystack: ast.AST, needle: ast.AST) -> bool:
    return any(n is needle for n in ast.walk(haystack))


def _str_constant(node: ast.AST | None) -> ast.Constant | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node
    return None


def _is_anchor_expr(node: ast.AST, anchor: ast.Call) -> bool:
    """True if `node` *is* the anchor call, or a simple single-argument cast
    of it (`str(Path.home())`). Deliberately identity-based rather than
    "anchor is somewhere in this subtree" -- `Path.home() / ".config" / "x"`
    is a left-associative BinOp chain, and a containment check matches the
    outermost `/ "x"` before the innermost `/ ".config"` that's actually
    joined to the anchor, misreading which literal is adjacent to home."""
    if node is anchor:
        return True
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        return _is_anchor_expr(node.args[0], anchor)
    return False


def _immediate_joined_literal(default: ast.AST, anchor: ast.Call) -> ast.Constant | None:
    """The literal string segment joined directly onto `anchor`, covering the
    three shapes actually seen in this repo: `Path.home() / "x"`,
    `os.path.join(str(Path.home()), "x", ...)`, and
    `Path.home().joinpath("x", ...)`. Returns None if `anchor` isn't joined
    to a literal via one of these specific shapes (a broader, order-blind
    fallback runs in that case -- see `_first_literal_outside`)."""
    for node in ast.walk(default):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if _is_anchor_expr(node.left, anchor):
                literal = _str_constant(node.right)
                if literal is not None:
                    return literal
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "join" and node.args and _is_anchor_expr(node.args[0], anchor):
                if len(node.args) > 1:
                    literal = _str_constant(node.args[1])
                    if literal is not None:
                        return literal
            if node.func.attr == "joinpath" and _is_anchor_expr(node.func.value, anchor):
                if node.args:
                    literal = _str_constant(node.args[0])
                    if literal is not None:
                        return literal
    return None


def _first_literal_outside(node: ast.AST, anchors: list[ast.Call]) -> ast.Constant | None:
    """Fallback: the first non-blank string literal in `node` outside of the
    anchor calls' own subtrees (i.e. joined onto the home anchor by some
    shape `_immediate_joined_literal` doesn't specifically recognize, not
    just the "~" argument of an expanduser() call itself)."""
    excluded_ids = {id(sub) for anchor in anchors for sub in ast.walk(anchor)}
    for n in ast.walk(node):
        if id(n) in excluded_ids:
            continue
        literal = _str_constant(n)
        if literal is not None and literal.value.strip():
            return literal
    return None


def check_home_relative_env_default(tree: ast.AST) -> list[tuple[int, int, str]]:
    """Return (line, col, default-source) for env-var defaults that anchor on
    the caller's home directory and then join a hardcoded, non-dotfile
    literal onto it. A literal starting with "." (the `~/.config/app/...`
    idiom) is exempt -- see the module docstring for why."""
    hits: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_environ_get_call(node):
            continue
        default = _extract_default_arg(node)
        if default is None:
            continue
        anchors = _home_anchor_calls(default)
        if not anchors:
            continue
        literal = None
        for anchor in anchors:
            literal = _immediate_joined_literal(default, anchor)
            if literal is not None:
                break
        if literal is None:
            literal = _first_literal_outside(default, anchors)
        if literal is None:
            continue  # bare home()/expanduser("~") with no extra segment at all
        if literal.value.startswith("."):
            continue  # ~/.config/app/... idiom -- optional, user-scoped by convention
        hits.append((node.lineno, node.col_offset, _unparse(default) or "<default>"))
    return hits


def find_violations(source: str, filename: str = "<string>") -> list[Violation]:
    """Run both checks over `source`, returning Violations sorted by line."""
    tree = ast.parse(source, filename=filename)
    out: list[Violation] = []
    for line, col, target, kind in check_dangling_create_task(tree):
        if kind == "bare":
            message = (
                "this create_task()/ensure_future() result is never assigned to anything, "
                "so it's both liable to early garbage collection and has no path back to a "
                "handler for its exception. Store it and add a `.add_done_callback(...)`, or "
                "use it inside `asyncio.TaskGroup`."
            )
        else:
            message = (
                f"`{target}` is never given a `.add_done_callback(...)` in this scope; "
                "an exception in the task is invisible until (if ever) something else "
                "retrieves it. Add a done-callback that logs/re-raises."
            )
        out.append(Violation(filename, line, col, DANGLING_CREATE_TASK, message))
    for line, col, default_src in check_home_relative_env_default(tree):
        out.append(
            Violation(
                filename,
                line,
                col,
                HOME_RELATIVE_ENV_DEFAULT,
                f"default `{default_src}` bakes a hardcoded path onto the caller's home "
                "directory; a clone on another machine silently gets a phantom path "
                "instead of a loud failure. Default to something repo-relative "
                "(e.g. Path(__file__).resolve().parents[N]) or omit the default.",
            )
        )
    out.sort(key=lambda v: (v.line, v.col))
    return out


def find_violations_in_file(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    return find_violations(source, filename=str(path))


def _tracked_python_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [repo_root / line for line in result.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files to check. Defaults to every git-tracked *.py file in the repo.",
    )
    args = parser.parse_args(argv)

    repo_root = resolve_vault_root()
    paths = [Path(p) for p in args.paths] if args.paths else _tracked_python_files(repo_root)

    all_violations: list[Violation] = []
    for path in paths:
        try:
            all_violations.extend(find_violations_in_file(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"{path}: skipped ({exc})", file=sys.stderr)

    for v in all_violations:
        print(v)

    by_rule: dict[str, int] = {}
    for v in all_violations:
        by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
    print(f"\n{len(all_violations)} violation(s) across {len(paths)} file(s): {by_rule}", file=sys.stderr)

    return 1 if all_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
