#!/usr/bin/env python3
"""Mandatory, packet-bound checks immediately before board host admission.

Thin composition over ``dispatch_context_builder``. One local rule: owner-mismatch
harness-drift. Absent ``mode`` -> ``modeless`` (key-presence; DISP-01) is NOT restated
here; it is delegated to ``context_builder.resolve_packet_mode``, the rule's one home.
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

import board_process_truth as process_truth
import dispatch_context_builder as context_builder


VERDICT_SCHEMA = "dispatch-preflight/v1"
ACK_FIELD = "dispatch_preflight_ack"
OWNER_MISMATCH = "owner_mismatch"
DIRTY_WRITE_SCOPE = "dirty_write_scope"
COUPLED_HASH_PIN = "coupled_hash_pin"
ADVISORY_SCAN_FAILED = "advisory_scan_failed"
KNOWN_ACKS = frozenset({OWNER_MISMATCH})
TOOLKIT_BOUNDARY = "\n## Dispatch Context\n"
RECENT_DISPATCH_WINDOW = 50

EXIT_PASS = 0
EXIT_INTERNAL = 2
EXIT_REFUSE = 3
EXIT_ACK_REQUIRED = 4


class ExactContractViolation(ValueError):
    """The final packet contradicts a deterministic dispatch contract."""


@dataclass(frozen=True)
class PacketContract:
    fields: Mapping[str, str]
    body: str
    task_id: str
    specialist: str
    to_model: str
    write_scope: tuple[str, ...]
    direct_lane: bool
    route: Mapping[str, Any]
    assembled_prompt_bytes: int


@dataclass(frozen=True)
class PreflightVerdict:
    packet_sha256: str
    task_id: str
    decision: str
    refusals: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[Mapping[str, Any], ...] = ()
    informational: tuple[Mapping[str, Any], ...] = ()
    warning_set_sha256: str | None = None
    ack_sha256: str | None = None

    @property
    def exit_code(self) -> int:
        if self.decision == "deny":
            return EXIT_REFUSE
        if self.decision == "needs_ack":
            return EXIT_ACK_REQUIRED
        return EXIT_PASS

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": VERDICT_SCHEMA,
            "packet_sha256": self.packet_sha256,
            "task_id": self.task_id,
            "decision": self.decision,
            "refusals": list(self.refusals),
            "warnings": list(self.warnings),
            "informational": list(self.informational),
            "warning_set_sha256": self.warning_set_sha256,
            "ack_sha256": self.ack_sha256,
        }


def _field(fields: Mapping[str, str], name: str) -> str:
    return context_builder._unquote(fields.get(name, ""))  # noqa: SLF001


def _parse_acknowledgements(raw: str) -> frozenset[str]:
    raw = raw.strip()
    if not raw:
        return frozenset()
    if not raw.startswith("[") or not raw.endswith("]"):
        raise ExactContractViolation(f"{ACK_FIELD} must be a YAML inline list")
    inner = raw[1:-1].strip()
    if not inner:
        return frozenset()
    acknowledgements = []
    for item in inner.split(","):
        value = item.strip().strip("'\"")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
            raise ExactContractViolation(
                f"{ACK_FIELD} contains an invalid acknowledgement: {value!r}"
            )
        acknowledgements.append(value)
    if len(acknowledgements) != len(set(acknowledgements)):
        raise ExactContractViolation(f"{ACK_FIELD} contains duplicate entries")
    unknown = sorted(set(acknowledgements) - KNOWN_ACKS)
    if unknown:
        raise ExactContractViolation(
            f"{ACK_FIELD} contains unknown acknowledgement(s): {', '.join(unknown)}"
        )
    return frozenset(acknowledgements)


def _contains(scope: str, target: str) -> bool:
    scope_path = PurePosixPath(scope)
    target_path = PurePosixPath(target)
    return scope_path == target_path or scope_path in target_path.parents


def _role_path(repo_root: Path, row: Mapping[str, str]) -> Path:
    namespace = row["source_namespace"]
    base = repo_root / ("shared" if namespace == "shared" else f"departments/{namespace}")
    path = base / "specialists" / f"{row['specialist']}.md"
    if not path.is_file():
        raise ExactContractViolation(
            f"canonical specialist brief is unavailable: {path}"
        )
    return path


def _validate_contract(
    repo_root: Path,
    fields: Mapping[str, str],
    body: str,
    packet_text: str,
) -> PacketContract:
    # Delegated, not restated: a copy here could drift from the layer that gates.
    fields = {**fields, "mode": context_builder.resolve_packet_mode(fields)}
    task_id = _field(fields, "id")
    specialist = _field(fields, "specialist")
    to_model = _field(fields, "to_model")
    direct_allowed = _field(fields, "direct_lane_work_allowed") or _field(
        fields, "lead_direct_allowed"
    )
    direct_lane = specialist == "none" and direct_allowed == "true"

    if not context_builder.TASK_RE.fullmatch(task_id):
        raise ExactContractViolation("task id is invalid")
    try:
        context_builder.MODEL_TO_LANE[to_model]
    except KeyError as exc:
        raise ExactContractViolation(f"unsupported to_model: {to_model!r}") from exc

    # Preserve the existing explicit direct-lane compatibility path. It has no
    # specialist row or brief to compare and therefore no owner semantic. Its
    # legacy metadata remains governed by send-task's existing guards.
    if direct_lane:
        return PacketContract(
            fields, body, task_id, specialist, to_model, (), True, {}, 0
        )

    if not context_builder.IDENTIFIER_RE.fullmatch(specialist):
        raise ExactContractViolation("specialist identifier is invalid")
    context_builder.require_packet_fields(fields)
    lane = context_builder.MODEL_TO_LANE[to_model]
    row = context_builder._runtime_row(repo_root, specialist)  # noqa: SLF001
    namespace = _field(fields, "source_namespace")
    if row.get("source_namespace") != namespace:
        raise ExactContractViolation("packet namespace does not match runtime map")
    if lane != row.get("primary_lane") and not _field(fields, "model_override_reason"):
        raise ExactContractViolation(
            "packet lane differs from the runtime-map primary without model_override_reason"
        )

    # These calls bind the packet to the selected runtime/profile registries and
    # prove that its canonical role exists. They intentionally do not probe a
    # lane executable; host admission and trusted-context build own that gate.
    profile_id = context_builder._selected_profile(row, lane)  # noqa: SLF001
    profile = context_builder._profile_row(  # noqa: SLF001
        repo_root, lane=lane, profile_id=profile_id
    )
    _role_path(repo_root, row)

    write_scope = context_builder.parse_scope(
        fields.get("write_scope", ""), field="write_scope"
    )
    return_artifact = context_builder._safe_relative(  # noqa: SLF001
        fields.get("return_artifact", ""), field="return_artifact"
    )
    if return_artifact and write_scope and not any(
        _contains(scope, return_artifact) for scope in write_scope
    ):
        raise ExactContractViolation("return_artifact is outside packet write_scope")

    contract = context_builder.validate_verification_contract(fields)
    if contract.get("run_id") != _field(fields, "run_id") or contract.get(
        "mode"
    ) != _field(fields, "mode"):
        raise ExactContractViolation("verification contract run/mode mismatch")

    memory_aperture, _memory_focus = context_builder.packet_memory_contract(fields)
    prompt = context_builder.assemble_trusted_launch_prompt(
        packet_text,
        task_id=task_id,
        attempt_id="d-" + "0" * 32,
        generation=1,
        memory_aperture=memory_aperture,
    )
    prompt_bytes = len(prompt.encode("utf-8"))
    if prompt_bytes > context_builder.TRUSTED_LAUNCH_PROMPT_LIMIT:
        raise ExactContractViolation("task packet is too large for trusted launch prompt")

    return PacketContract(
        fields,
        body,
        task_id,
        specialist,
        to_model,
        write_scope,
        False,
        {
            "profile_id": profile_id,
            "registry_model": profile["model_id"],
            "effective_model": profile["model_id"],
            "review_lane": row.get("review_lane", "none"),
            "model_override": lane != row.get("primary_lane"),
        },
        prompt_bytes,
    )


def _author_text(fields: Mapping[str, str], body: str) -> str:
    body = body.split(TOOLKIT_BOUNDARY, 1)[0]
    frontmatter_intent = " ".join(
        _field(fields, name)
        for name in ("title", "goal", "objective", "task_shape")
        if _field(fields, name)
    )
    return f"{frontmatter_intent}\n{body}".lower()


def _author_task_text(contract: PacketContract) -> str:
    return _author_text(contract.fields, contract.body)


class GitProbeError(RuntimeError):
    """git could not answer -- distinct from git answering "nothing"."""


def _git_paths(repo_root: Path, *arguments: str) -> tuple[str, ...]:
    """Paths from a git query, or raise if the query never ran.

    Swallowing failures here made a scan that could not run look exactly like a
    scan that found nothing, so `_write_scope_advisories` returned `()` and the
    caller read that as "clean". `_scan_failed_advisory` was written to prevent
    precisely that, but it sits one level up and never saw these errors -- its
    tests inject RuntimeError, which this function does not catch. Raising lets
    the real failures reach it. The scan stays FAIL-OPEN (the advisory never
    gates dispatch); it stops being fail-SILENT.
    """
    try:
        result = subprocess.run(
            ("git", "-C", str(repo_root), *arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitProbeError(f"git {arguments[0]} did not run: {exc}") from exc
    if result.returncode:
        # `git grep` exits 1 for "no matches" -- a real answer, not a failure
        # (measured). Every other nonzero exit means the query did not run:
        # `ls-files` exits 128 outside a repository, for instance.
        if arguments[:1] == ("grep",) and result.returncode == 1:
            return ()
        raise GitProbeError(
            f"git {arguments[0]} failed with exit {result.returncode}"
        )
    return tuple(
        item.decode("utf-8", "surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    )


def _write_scope_advisories(
    repo_root: Path, fields: Mapping[str, str], body: str
) -> tuple[Mapping[str, Any], ...]:
    """Return fail-open authoring diagnostics; these must never gate dispatch."""
    try:
        write_scope = context_builder.parse_scope(
            fields.get("write_scope", ""), field="write_scope"
        )
        warnings: list[Mapping[str, Any]] = []
        tracked_paths = _git_paths(repo_root, "ls-files", "-z")
        for source in sorted(set(write_scope) & set(tracked_paths)):
            digest = hashlib.sha256((repo_root / source).read_bytes()).hexdigest()
            pins = _git_paths(repo_root, "grep", "-lz", digest, "--")
            missing = tuple(
                path for path in pins
                if not any(_contains(scope, path) for scope in write_scope)
            )
            if missing:
                sample = ", ".join(missing[:3])
                warnings.append({
                    "code": COUPLED_HASH_PIN, "gate": "advisory", "blocking": False,
                    "message": f"{source} hash is pinned outside write_scope by "
                    f"{len(missing)} tracked path(s) (sample: {sample})",
                    "source_path": source, "missing_count": len(missing),
                    "paths": list(missing[:10]),
                })

        dirty = set()
        if write_scope:
            dirty.update(
                _git_paths(
                    repo_root, "diff", "--name-only", "-z", "--", *write_scope
                )
            )
            dirty.update(
                _git_paths(
                    repo_root,
                    "diff",
                    "--cached",
                    "--name-only",
                    "-z",
                    "--",
                    *write_scope,
                )
            )
        if dirty:
            warnings.append(
                {
                    "code": DIRTY_WRITE_SCOPE,
                    "gate": "advisory",
                    "blocking": False,
                    "message": "tracked main-checkout changes already overlap write_scope",
                    "paths": sorted(dirty),
                }
            )
        return tuple(warnings)
    except Exception as exc:  # Fail-open, including future drift -- but not silent.
        return (_scan_failed_advisory(exc),)


def _scan_failed_advisory(exc: BaseException) -> Mapping[str, Any]:
    """Loud marker: the scan did not finish, so its silence proves nothing.

    Returning `()` said "scanned, no warnings" about a scan that never ran,
    making a broken packet the cleanest-looking packet on the board. Shaped as
    an advisory on purpose -- no `required_ack`, not blocking -- so it reports
    the blind spot without becoming the gate these diagnostics may not be.
    """
    return {
        "code": ADVISORY_SCAN_FAILED,
        "gate": "advisory",
        "blocking": False,
        "message": (
            f"authoring advisories could not be computed ({type(exc).__name__}: "
            f"{exc}); an empty warning list below is not evidence of a clean packet"
        ),
    }


def authoring_warnings(repo_root: Path, packet: Path) -> tuple[Mapping[str, Any], ...]:
    try:
        fields, body = context_builder._parse_task_text(  # noqa: SLF001
            Path(packet).read_text(encoding="utf-8")
        )
        root = Path(repo_root).resolve(strict=True)
    except Exception as exc:  # Unparsable packet: a scan that could not run.
        return (_scan_failed_advisory(exc),)
    return _write_scope_advisories(root, fields, body)


def _scope_classification(write_scope: Sequence[str]) -> str:
    harness_surfaces = ("bin/", "scripts/", "model-lanes/", "shared/registries/")
    has_harness_surface = any(
        path in {"bin", "scripts", "model-lanes", "shared"}
        or path.startswith(harness_surfaces)
        or path.endswith((".py", ".sh", ".toml", ".tsv"))
        for path in write_scope
    )
    artifact_only = bool(write_scope) and all(
        path.startswith(("_state/", "docs/")) or path.endswith(".md")
        for path in write_scope
    )
    return (
        "mixed" if has_harness_surface and artifact_only
        else "harness_surface" if has_harness_surface
        else "artifact_only" if artifact_only
        else "other"
    )


def _matching_signals(text: str) -> tuple[str, ...]:
    groups = {
        "prompt": ("prompt", "instruction"),
        "adapter": ("adapter", "role overlay", "model-lane"),
        "routing": ("routing", "owner mismatch", "specialist selection"),
        "script_drift": (
            "script drift",
            "script-drift",
            "validator drift",
            "harness drift",
            "generated adapter",
            "generated-adapter",
            "tool catalog",
        ),
    }
    return tuple(
        name for name, phrases in groups.items() if any(item in text for item in phrases)
    )


def _first_line(markdown: str, *needles: str) -> str:
    for line in markdown.splitlines():
        compact = line.strip().lstrip("- ")
        lowered = compact.lower()
        if compact and all(needle.lower() in lowered for needle in needles):
            return compact
    return ""


def _read_role(repo_root: Path, specialist: str) -> tuple[Path, str]:
    row = context_builder._runtime_row(repo_root, specialist)  # noqa: SLF001
    path = _role_path(repo_root, row)
    return path, path.read_text(encoding="utf-8")


def _owner_mismatch_warning(
    repo_root: Path, contract: PacketContract
) -> Mapping[str, Any] | None:
    if contract.direct_lane or contract.specialist != "technical-writer":
        return None
    task_text = _author_task_text(contract)
    signals = _matching_signals(task_text)
    action_terms = (
        "audit",
        "analyze",
        "diagnose",
        "drift",
        "hygiene",
        "repair",
        "fix",
        "prevent",
        "compare",
        "change",
        "implement",
    )
    if len(signals) < 3 or not any(term in task_text for term in action_terms):
        return None

    documentation_intent = any(
        phrase in task_text
        for phrase in (
            "write an adr",
            "write documentation",
            "write the documentation",
            "changelog",
            "release notes",
            "post-spec handoff",
        )
    )
    scope_kind = _scope_classification(contract.write_scope)
    if documentation_intent and scope_kind == "artifact_only":
        return None

    technical_path, technical = _read_role(repo_root, "technical-writer")
    harness_path, harness = _read_role(repo_root, "harness-optimizer")
    prompt_path, prompt = _read_role(repo_root, "prompt-engineer")
    triage_path = repo_root / "shared" / "specialists" / "triage.md"
    try:
        triage = triage_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExactContractViolation(
            f"owner semantic source is unavailable: {triage_path}"
        ) from exc

    boundaries = (
        (technical_path, technical, ("Changelogs", "documentation")),
        (technical_path, technical, ("I do NOT", "invent")),
        (harness_path, harness, ("Owns prompt", "script-drift")),
        (prompt_path, prompt, ("squad-wide prompt", "harness-optimizer")),
        (prompt_path, prompt, ("I do NOT", "routing")),
        (triage_path, triage, ("Docs / changelog", "technical-writer")),
    )
    evidence = [
        {
            "source": path.relative_to(repo_root).as_posix(),
            "boundary": _first_line(markdown, *needles),
        }
        for path, markdown, needles in boundaries
    ]
    return {
        "code": OWNER_MISMATCH,
        "selected_specialist": "technical-writer",
        "recommended_specialist": "harness-optimizer",
        "message": (
            "task semantics concern squad-wide prompt/adapter/routing/script drift, "
            "while technical-writer is documentation-shaped"
        ),
        "matched_task_signals": list(signals),
        "write_scope": list(contract.write_scope),
        "write_scope_classification": scope_kind,
        "required_ack": f"{ACK_FIELD}: [{OWNER_MISMATCH}]",
        "evidence": evidence,
    }


def _concentration_information(
    repo_root: Path, contract: PacketContract
) -> Mapping[str, Any]:
    path = repo_root / "_state" / "dispatch-log.jsonl"
    recent: deque[str] = deque(maxlen=RECENT_DISPATCH_WINDOW)
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    recent.append(line)
    except OSError:
        return {
            "code": "recent_dispatch_concentration",
            "gate": "informational",
            "available": False,
            "note": "dispatch log unavailable; concentration never changes verdict",
        }

    records = []
    malformed = 0
    for line in recent:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            malformed += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            malformed += 1
    specialist_counts = Counter(str(item.get("specialist", "")) for item in records)
    lane_counts = Counter(str(item.get("model_lane", "")) for item in records)
    return {
        "code": "recent_dispatch_concentration",
        "gate": "informational",
        "available": True,
        "window_records": len(records),
        "malformed_records": malformed,
        "selected_specialist_count": specialist_counts[contract.specialist],
        "selected_model_lane_count": lane_counts[contract.to_model],
        "note": (
            "raw counts contain neither task shape nor eligible-owner set and "
            "never change this verdict"
        ),
    }


def evaluate_packet(repo_root: Path, packet: Path) -> PreflightVerdict:
    repo_root = Path(repo_root).resolve(strict=True)
    raw = Path(packet).read_bytes()
    packet_sha256 = hashlib.sha256(raw).hexdigest()
    task_id = ""
    try:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExactContractViolation(f"task packet is not valid UTF-8: {exc}") from exc
        fields, body = context_builder._parse_task_text(text)  # noqa: SLF001
        task_id = _field(fields, "id")
        acknowledgements = _parse_acknowledgements(fields.get(ACK_FIELD, ""))
        contract = _validate_contract(repo_root, fields, body, text)
        warning = _owner_mismatch_warning(repo_root, contract)
        advisories = _write_scope_advisories(repo_root, fields, body)
    except (context_builder.DispatchContextError, ExactContractViolation, OSError) as exc:
        return PreflightVerdict(
            packet_sha256=packet_sha256,
            task_id=task_id,
            decision="deny",
            refusals=(
                {
                    "code": "exact_contract_violation",
                    "message": str(exc),
                },
            ),
        )

    warning_basis = warning
    warnings: tuple[Mapping[str, Any], ...] = advisories
    if warning is not None:
        warning = {**warning, "acknowledged": OWNER_MISMATCH in acknowledgements}
        warnings = (warning, *warnings)
    acknowledgement_warnings = tuple(
        item for item in warnings if item.get("required_ack")
    )
    informational = []
    if not contract.direct_lane:
        informational.extend(
            (
                {"code": "route_resolution", "gate": "required", **contract.route},
                {
                    "code": "trusted_launch_prompt",
                    "gate": "required",
                    "assembled_prompt_bytes": contract.assembled_prompt_bytes,
                    "assembled_prompt_limit": context_builder.TRUSTED_LAUNCH_PROMPT_LIMIT,
                },
            )
        )
    informational.append(_concentration_information(repo_root, contract))
    unused = sorted(acknowledgements - {item["code"] for item in warnings})
    if unused:
        informational.append(
            {
                "code": "unused_preflight_acknowledgement",
                "gate": "informational",
                "acknowledgements": unused,
            }
        )

    warning_set_sha256 = None
    ack_sha256 = None
    if warning_basis is not None:
        warning_set_sha256 = hashlib.sha256(
            context_builder._canonical_json([warning_basis])  # noqa: SLF001
        ).hexdigest()
        if all(bool(item["acknowledged"]) for item in acknowledgement_warnings):
            ack_sha256 = hashlib.sha256(
                f"{packet_sha256}\0{warning_set_sha256}".encode("ascii")
            ).hexdigest()
    decision = (
        "needs_ack"
        if acknowledgement_warnings
        and not all(bool(item["acknowledged"]) for item in acknowledgement_warnings)
        else "allow"
    )
    return PreflightVerdict(
        packet_sha256=packet_sha256,
        task_id=contract.task_id,
        decision=decision,
        warnings=warnings,
        informational=tuple(informational),
        warning_set_sha256=warning_set_sha256,
        ack_sha256=ack_sha256,
    )


def verdict_matches_packet(
    verdict: PreflightVerdict | Mapping[str, Any], packet: Path
) -> bool:
    declared = (
        verdict.packet_sha256
        if isinstance(verdict, PreflightVerdict)
        else verdict.get("packet_sha256")
    )
    if not isinstance(declared, str) or not process_truth.SHA256.fullmatch(declared):
        return False
    try:
        actual = hashlib.sha256(Path(packet).read_bytes()).hexdigest()
    except OSError:
        return False
    return hmac.compare_digest(declared, actual)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--authoring-warnings-only", action="store_true")
    return parser


def _print_advisories(warnings: Sequence[Mapping[str, Any]]) -> None:
    for warning in warnings:
        try:
            if warning.get("gate") == "advisory":
                print(
                    f"dispatch preflight warning [{warning['code']}]: "
                    f"{warning['message']}",
                    file=sys.stderr,
                )
        except Exception:
            continue


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.authoring_warnings_only:
        _print_advisories(authoring_warnings(args.repo_root, args.packet))
        return EXIT_PASS
    try:
        verdict = evaluate_packet(args.repo_root.resolve(strict=True), args.packet)
    except OSError as exc:
        print(f"dispatch preflight internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    _print_advisories(verdict.warnings)
    print(
        json.dumps(
            verdict.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    )
    return verdict.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
