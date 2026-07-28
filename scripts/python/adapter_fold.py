#!/usr/bin/env python3
"""V2 Task 2.6 — adapter fold: lane-truth rescued into shared/lane-role-overlay/v1/.

Investigation (not assumption) established that role-truth already lives
entirely in the canonical ``departments/*/specialists/*.md`` files by
design (their own boundary rule: "a sentence that would be false on some
lane belongs in the adapter"), and that almost all lane-truth is already
centrally sourced — the capability projection block from
``specialist-lane-capabilities.v1.json`` via ``lane_adapter_registry``, and
lane-wide constants (Gemini's native tool allowlist, ``max_turns``, Codex's
``sandbox_mode``) from ``lane-capabilities.tsv``/hardcoded template text.

Only a small typed field set, across the live 156-file corpus, is genuinely
per-specialist lane-truth that exists *nowhere* except hand-edits inside
the native adapter files themselves, surviving only because
``upsert_capability_projection`` never touches anything outside the
BEGIN/END capability block:

- Codex ``model_reasoning_effort`` (verified: varies "high"/"medium" across
  real files; ``lane_adapter_registry.render_adapter`` hardcodes "high"
  only for from-scratch creation).
- Kimi ``model`` (verified: varies "kimi-code/kimi-for-coding" vs
  "...-highspeed"; similarly hardcoded-on-creation only).

This module rescues exactly those two fields into
``shared/lane-role-overlay/v1/<lane>/<specialist>.json`` and reconstructs
the full adapter by composing with the existing, already-reviewed
generator (``lane_adapter_registry.render_adapter``/``capability_projection``)
rather than reimplementing template rendering — the fold proves parity
against what that generator already produces, patched with the rescued
per-specialist values in place of its hardcoded defaults.

FIX (TASK-2026-07-22-0625-v2-t2p6-fix, closing a REJECT of the original
2.6 commit): two things changed after cross-family review.

1. The overlay was never meant to be, and is not, self-contained lane
   truth by itself — 66/156 overlays hold a completely empty ``fields``
   object, because the bulk of any lane's policy (tool allowlists, sandbox
   mode, MCP surface, the capability projection block) is already
   centrally sourced elsewhere and reconstructed by
   ``lane_adapter_registry.render_adapter``, not carried in the overlay.
   Per the operator's core-swarm-first reframe (full native-adapter
   retirement is not a near-term goal), that renderer is PROMOTED here to
   permanent, shared, non-retiring infrastructure rather than something
   this fold tries to make obsolete. ``resolve_lane_context()`` /
   ``write_lane_context_file()`` / ``verify_lane_context()`` are the
   actual self-contained-lane-truth contract: they always compose the
   overlay's rescued deltas WITH the shared renderer's projection, never
   the overlay alone, and expose a content hash a caller (e.g. a future
   role-context-compiler wiring) can verify hasn't silently drifted.
2. ``prove_parity()`` used to blanket-normalize ANY registry hash and, for
   Gemini, the ENTIRE tools allowlist line before comparing — which
   contradicted its own "byte-identical" claim (most files in the reviewed
   snapshot required normalization) and, worse, could not detect a corrupted tools list or an
   unaudited hash (both verified live via adversarial probes). Renamed to
   ``prove_normalized_parity()`` and rebuilt on a structural delta check:
   it accepts ONLY the two exact, individually audited old-value ->
   new-value pairs found in the real corpus (never a wildcard), records
   every exception it actually applies, and fails closed on anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from specialist_capability_source import atomic_write_text

try:
    import lane_adapter_registry as registry
except ImportError:  # pragma: no cover - package-context fallback
    from . import lane_adapter_registry as registry  # type: ignore[no-redef]


OVERLAY_SCHEMA = "lane-role-overlay/v1"
LANE_CONTEXT_SCHEMA = "lane-context/v1"
_LANES = ("claude", "gemini", "gpt-codex", "kimi")
_CODEX_EFFORT_RE = re.compile(r'^model_reasoning_effort\s*=\s*"([^"]*)"\s*$', re.MULTILINE)
_KIMI_MODEL_RE = re.compile(r"^\s*model:\s*(\S+)", re.MULTILINE)
_SPECIALIST_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LEGACY_HEADING_RE = re.compile(r"^# Specialist Adapter: ([^\n]+)$", re.MULTILINE)
_CODEX_EFFORTS = frozenset({"low", "medium", "high"})
# Closed allowlist, deliberately explicit rather than derived: an unknown
# model string must fail rather than be waved through. The K3 pair comes
# from the 2026-07 refresh (shared/registries/profiles.tsv: kimi.k3.high,
# kimi.k3.256k); the kimi-for-coding pair predates profiles.tsv and is
# still live in the on-disk corpus.
_KIMI_MODELS = frozenset(
    {
        "kimi-code/kimi-for-coding",
        "kimi-code/kimi-for-coding-highspeed",
        "kimi-code/k3",
        "kimi-code/k3-256k",
    }
)

# The exact, individually audited staleness classes found by direct
# inspection of the real 156-file corpus (see the return artifact for
# TASK-2026-07-22-0625-v2-t2p6-fix for the verification commands run).
# These are the ONLY substitutions prove_normalized_parity() may grant —
# never a pattern that would also match an unaudited or malicious value.
_AUDITED_REGISTRY_SHA_OLD = "83bf08d4eb6d20c92f79809010e2930e2332b1371c1e68b8de6143697c1187ac"
_AUDITED_REGISTRY_SHA_NEW = "9ef0062bc54f046084c442e7c41093a7ce80a3e562c053a6928a4fe84dca1042"
_REGISTRY_SHA_PATTERN = re.compile(
    r'(?:registry_sha256=|capability_registry_sha256:\s*|capability_registry_sha256\s*=\s*")([0-9a-f]{64})'
)

# The exact, individually audited pre-schema Kimi overlays: their committed
# records under shared/lane-role-overlay/v1/kimi/ predate the `legacy_style`
# field, while their on-disk adapters are genuinely markerless, so resolving
# them from overlay data alone needs the flag restored. Pinned by name, never
# inferred from a correlated field: this shim originally keyed off "the
# overlay carries a custom description", an invariant the 2026-07 K3 refresh
# broke by landing marker-CARRYING adapters that also carry one (web-builder,
# large-context-analyst). Any other Kimi overlay resolves markerful — the
# shape lane_adapter_registry.render_adapter actually writes.
_AUDITED_KIMI_PRESCHEMA_OVERLAYS = frozenset(
    {
        "growth-and-search-analyst",
        "summarizer",
    }
)

_AUDITED_GEMINI_TOOLS_OLD = (
    'tools: ["read_file", "replace", "write_file", "run_shell_command", "glob", "grep_search"]',
    'tools: ["read_file","replace","write_file","run_shell_command","glob","grep_search"]',
)
_AUDITED_GEMINI_TOOLS_NEW = (
    'tools: ["read_file","replace","write_file","run_shell_command","glob","grep_search","playwright"]'
)
_GEMINI_TOOLS_LINE_RE = re.compile(r"^tools:.*$", re.MULTILINE)

# Per-lane (pattern, generic-template) for the specialist description line.
# "Generic" means auto-derived from the specialist name only, per
# lane_adapter_registry.render_adapter's own boilerplate -- anything else is
# a genuine hand-authored override, verified present in the live corpus
# across all four lanes.
_DESCRIPTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "claude": re.compile(r'^description:\s*"([^"]*)"\s*$', re.MULTILINE),
    "gemini": re.compile(r'^description:\s*"([^"]*)"\s*$', re.MULTILINE),
    "gpt-codex": re.compile(r'^description = "([^"]*)"\s*$', re.MULTILINE),
    "kimi": re.compile(r'^(\s*)description:\s*"([^"]*)"\s*$', re.MULTILINE),
}


def _generic_description(lane: str, specialist: str) -> str:
    label = {"claude": "Claude", "gemini": "Gemini", "gpt-codex": "Codex", "kimi": "Kimi"}[lane]
    return f"Thin {label} adapter for {specialist}; canonical brief is authoritative."


# Deprecated overlays may still contain captured bodies. Migrate those
# snapshots to typed style metadata and render every body from the live,
# centralized registry. This preserves audited corpus shape without letting a
# stale overlay suppress future safety-policy updates.
_CLAUDE_GEMINI_BODY_RE = re.compile(r"# Specialist Adapter:.*\Z", re.DOTALL)
_CODEX_BODY_RE = re.compile(r'developer_instructions = """\n.*\n"""\n\Z', re.DOTALL)


class AdapterFoldError(RuntimeError):
    """The overlay, extraction, or golden-file parity check failed."""


def _adapter_path(repo_root: Path, lane: str, specialist: str) -> Path:
    _validate_specialist(specialist)
    root = Path(repo_root)
    if lane == "gpt-codex":
        return root / "model-lanes" / "gpt-codex" / ".codex" / "agents" / f"{specialist}.toml"
    if lane == "claude":
        return root / "model-lanes" / "claude" / ".claude" / "agents" / f"{specialist}.md"
    if lane == "gemini":
        return root / "model-lanes" / "gemini" / ".gemini" / "agents" / f"{specialist}.md"
    if lane == "kimi":
        return root / "model-lanes" / "kimi" / ".kimi" / "agents" / f"{specialist}.yaml"
    raise AdapterFoldError(f"unknown lane: {lane}")


def overlay_path(
    repo_root: Path, lane: str, specialist: str, *, overlay_root: Path | None = None
) -> Path:
    if lane not in _LANES:
        raise AdapterFoldError(f"unknown lane: {lane}")
    _validate_specialist(specialist)
    base = Path(overlay_root) if overlay_root is not None else Path(repo_root)
    resolved_base = base.resolve(strict=False)
    overlay_dir = (
        resolved_base / "shared" / "lane-role-overlay" / "v1" / lane
    ).resolve(strict=False)
    candidate = (overlay_dir / f"{specialist}.json").resolve(strict=False)
    try:
        overlay_dir.relative_to(resolved_base)
        candidate.relative_to(resolved_base)
    except ValueError as exc:
        raise AdapterFoldError(
            f"overlay path escapes the configured root for {lane}/{specialist}"
        ) from exc
    if candidate.parent != overlay_dir:
        raise AdapterFoldError(
            f"overlay path escapes the lane directory for {lane}/{specialist}"
        )
    return candidate


def _validate_specialist(specialist: str) -> None:
    if not isinstance(specialist, str) or not _SPECIALIST_RE.fullmatch(specialist):
        raise AdapterFoldError(f"invalid specialist identifier: {specialist!r}")


def _validate_scalar(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise AdapterFoldError(f"{label} must be a non-empty control-free string")
    return value


def _legacy_metadata(lane: str, specialist: str, body: Any) -> dict[str, Any]:
    """Migrate a legacy body snapshot to typed style metadata without replay."""
    if not isinstance(body, str) or not body or "\x00" in body:
        raise AdapterFoldError(
            f"{lane}/{specialist}: deprecated body must be non-empty UTF-8 text"
        )
    text = body
    if lane == "gpt-codex":
        if not _CODEX_BODY_RE.fullmatch(text):
            raise AdapterFoldError(
                f"{lane}/{specialist}: deprecated body is not a recognized Codex snapshot"
            )
        return {"legacy_style": True}
    if lane in {"claude", "gemini"}:
        if not _CLAUDE_GEMINI_BODY_RE.fullmatch(text):
            raise AdapterFoldError(
                f"{lane}/{specialist}: deprecated body is not a recognized Markdown snapshot"
            )
        heading = _LEGACY_HEADING_RE.match(text)
        if not heading:
            raise AdapterFoldError(
                f"{lane}/{specialist}: deprecated body lacks a recognized heading"
            )
        metadata: dict[str, Any] = {
            "legacy_style": True,
            "legacy_heading": _validate_scalar(
                heading.group(1), f"{lane}/{specialist}: legacy heading"
            ),
        }
        historical_marker = (
            f"You are the `{specialist}` specialist running inside the "
            f"`{lane}` model lane."
        )
        compact_marker = (
            f"You are the `{specialist}` specialist in the `{lane}` lane."
        )
        if historical_marker in text:
            return metadata
        if compact_marker in text:
            metadata["legacy_variant"] = "compact-v1"
            return metadata
        raise AdapterFoldError(
            f"{lane}/{specialist}: deprecated body has an unknown policy shape"
        )
    raise AdapterFoldError(f"{lane}/{specialist}: deprecated body is not supported")


def _normalize_overlay_fields(
    lane: str, specialist: str, raw_fields: Mapping[str, Any]
) -> dict[str, Any]:
    if lane not in _LANES:
        raise AdapterFoldError(f"unknown lane: {lane}")
    _validate_specialist(specialist)
    if not isinstance(raw_fields, Mapping) or not all(
        isinstance(key, str) for key in raw_fields
    ):
        raise AdapterFoldError(f"{lane}/{specialist}: overlay fields must be an object")
    fields = dict(raw_fields)
    body = fields.pop("body", None)
    if body is not None:
        migrated = _legacy_metadata(lane, specialist, body)
        for key, value in migrated.items():
            if key in fields and fields[key] != value:
                raise AdapterFoldError(
                    f"{lane}/{specialist}: deprecated body conflicts with {key}"
                )
            fields[key] = value
    allowed = {
        "gpt-codex": {
            "model_reasoning_effort",
            "description",
            "legacy_style",
        },
        "claude": {
            "description",
            "legacy_style",
            "legacy_heading",
            "legacy_variant",
        },
        "gemini": {
            "description",
            "legacy_style",
            "legacy_heading",
            "legacy_variant",
        },
        "kimi": {"model", "description", "legacy_style"},
    }[lane]
    unexpected = sorted(set(fields) - allowed)
    if unexpected:
        raise AdapterFoldError(
            f"{lane}/{specialist}: unexpected overlay fields {unexpected}"
        )
    if "legacy_style" in fields and not isinstance(fields["legacy_style"], bool):
        raise AdapterFoldError(
            f"{lane}/{specialist}: legacy_style must be a boolean"
        )
    for key in ("description", "legacy_heading", "legacy_variant"):
        if key in fields:
            fields[key] = _validate_scalar(
                fields[key], f"{lane}/{specialist}: {key}"
            )
    if "legacy_heading" in fields and not fields.get("legacy_style"):
        raise AdapterFoldError(
            f"{lane}/{specialist}: legacy_heading requires legacy_style"
        )
    if "legacy_variant" in fields:
        if fields["legacy_variant"] != "compact-v1":
            raise AdapterFoldError(
                f"{lane}/{specialist}: unsupported legacy_variant "
                f"{fields['legacy_variant']!r}"
            )
        if not fields.get("legacy_style"):
            raise AdapterFoldError(
                f"{lane}/{specialist}: legacy_variant requires legacy_style"
            )
    if "model_reasoning_effort" in fields:
        effort = _validate_scalar(
            fields["model_reasoning_effort"],
            f"{lane}/{specialist}: model_reasoning_effort",
        )
        if effort not in _CODEX_EFFORTS:
            raise AdapterFoldError(
                f"{lane}/{specialist}: unsupported model_reasoning_effort {effort!r}"
            )
    if "model" in fields:
        model = _validate_scalar(fields["model"], f"{lane}/{specialist}: model")
        if model not in _KIMI_MODELS:
            raise AdapterFoldError(
                f"{lane}/{specialist}: unsupported Kimi model {model!r}"
            )
    return fields


def extract_overlay_fields(repo_root: Path, lane: str, specialist: str) -> dict[str, Any]:
    """Rescue the per-specialist lane-truth that exists only in the live adapter file."""

    adapter_path = _adapter_path(repo_root, lane, specialist)
    try:
        text = adapter_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdapterFoldError(f"no real adapter for {lane}/{specialist}: {exc}") from exc
    fields: dict[str, Any] = {}
    if lane == "gpt-codex":
        match = _CODEX_EFFORT_RE.search(text)
        if not match:
            raise AdapterFoldError(f"{specialist}: model_reasoning_effort not found")
        fields["model_reasoning_effort"] = match.group(1)
    if lane == "kimi":
        match = _KIMI_MODEL_RE.search(text)
        if not match:
            raise AdapterFoldError(f"{specialist}: kimi model not found")
        fields["model"] = match.group(1)
    description_match = _DESCRIPTION_PATTERNS[lane].search(text)
    if description_match:
        description = description_match.group(description_match.lastindex or 1)
        if description != _generic_description(lane, specialist):
            fields["description"] = description
    is_legacy_style = False
    if lane in {"claude", "gemini"}:
        body_match = _CLAUDE_GEMINI_BODY_RE.search(text)
        is_legacy_style = bool(
            body_match
            and f"specialist running inside the `{lane}` model lane" in body_match.group(0)
        )
    elif lane == "gpt-codex":
        body_match = _CODEX_BODY_RE.search(text)
        is_legacy_style = bool(
            body_match
            and "specialist running inside the `gpt-codex` model lane"
            in body_match.group(0)
        )
    elif lane == "kimi":
        is_legacy_style = not text.startswith("# generated_by=")
    if is_legacy_style:
        fields["legacy_style"] = True
        if lane in ("claude", "gemini"):
            if not body_match:
                raise AdapterFoldError(f"{specialist}: legacy-style file has no body to rescue")
            heading = _LEGACY_HEADING_RE.match(body_match.group(0))
            if not heading:
                raise AdapterFoldError(
                    f"{specialist}: legacy-style file has no recognized heading"
                )
            fields["legacy_heading"] = heading.group(1)
        elif lane == "gpt-codex":
            body_match = _CODEX_BODY_RE.search(text)
            if not body_match:
                raise AdapterFoldError(f"{specialist}: legacy-style file has no body to rescue")
    return _normalize_overlay_fields(lane, specialist, fields)


def write_overlay(
    repo_root: Path, lane: str, specialist: str, *, overlay_root: Path | None = None
) -> Path:
    fields = extract_overlay_fields(repo_root, lane, specialist)
    payload = {
        "schema": OVERLAY_SCHEMA,
        "lane": lane,
        "specialist": specialist,
        "fields": fields,
    }
    path = overlay_path(repo_root, lane, specialist, overlay_root=overlay_root)
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def _read_overlay_fields(
    repo_root: Path, lane: str, specialist: str, *, overlay_root: Path | None = None
) -> dict[str, Any]:
    path = overlay_path(repo_root, lane, specialist, overlay_root=overlay_root)
    if not path.exists():
        return extract_overlay_fields(repo_root, lane, specialist)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterFoldError(f"malformed overlay {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AdapterFoldError(f"overlay {path} must contain a JSON object")
    if payload.get("schema") != OVERLAY_SCHEMA or payload.get("lane") != lane or payload.get("specialist") != specialist:
        raise AdapterFoldError(f"overlay {path} does not match {lane}/{specialist}")
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise AdapterFoldError(f"overlay {path} has no valid fields object")
    if set(payload) != {"schema", "lane", "specialist", "fields"}:
        raise AdapterFoldError(f"overlay {path} contains unexpected top-level fields")
    if (
        lane == "kimi"
        and specialist in _AUDITED_KIMI_PRESCHEMA_OVERLAYS
        and "legacy_style" not in fields
    ):
        # Migrate the presentation marker from overlay data alone; resolution
        # must not consult the native adapter.
        fields = {**fields, "legacy_style": True}
    return _normalize_overlay_fields(lane, specialist, fields)


def render_adapter_from_overlay(
    repo_root: Path,
    lane: str,
    specialist: str,
    *,
    overlay_root: Path | None = None,
    override_fields: Mapping[str, Any] | None = None,
) -> str:
    """Compose the existing generator's output with the rescued overlay fields.

    Reuses ``lane_adapter_registry.render_adapter`` for everything that is
    already centrally sourced (role pointer, capability projection, lane
    constants) and applies only validated scalar/style metadata from the
    overlay rather than reimplementing adapter rendering or replaying prose.
    """

    root = Path(repo_root)
    fields = _normalize_overlay_fields(
        lane,
        specialist,
        override_fields
        if override_fields is not None
        else _read_overlay_fields(
            root, lane, specialist, overlay_root=overlay_root
        ),
    )
    legacy_style = bool(fields.pop("legacy_style", False))
    legacy_variant = fields.pop("legacy_variant", None)
    rendered = registry.render_adapter(
        root,
        lane,
        specialist,
        legacy_style=legacy_style,
        legacy_variant=legacy_variant,
    )
    if lane == "gpt-codex":
        effort = fields.pop("model_reasoning_effort", None)
        if effort is None:
            raise AdapterFoldError(f"{specialist}: overlay is missing model_reasoning_effort")
        rendered, count = _CODEX_EFFORT_RE.subn(
            f'model_reasoning_effort = "{effort}"', rendered
        )
        if count != 1:
            raise AdapterFoldError(f"{specialist}: could not patch model_reasoning_effort")
    elif lane == "kimi":
        model = fields.pop("model", None)
        if model is None:
            raise AdapterFoldError(f"{specialist}: overlay is missing model")
        rendered, count = _KIMI_MODEL_RE.subn(f"  model: {model}", rendered)
        if count != 1:
            raise AdapterFoldError(f"{specialist}: could not patch kimi model")
    description = fields.pop("description", None)
    if description is not None:
        pattern = _DESCRIPTION_PATTERNS[lane]
        serialized = json.dumps(description, ensure_ascii=False)
        if lane == "kimi":
            rendered, count = pattern.subn(
                lambda m: f"{m.group(1)}description: {serialized}", rendered
            )
        elif lane == "gpt-codex":
            rendered, count = pattern.subn(f"description = {serialized}", rendered)
        else:
            rendered, count = pattern.subn(f"description: {serialized}", rendered)
        if count != 1:
            raise AdapterFoldError(f"{specialist}: could not patch description")
    heading = fields.pop("legacy_heading", None)
    if heading is not None:
        rendered, count = re.subn(
            r"(?m)^# Specialist Adapter:.*$",
            f"# Specialist Adapter: {heading}",
            rendered,
            count=1,
        )
        if count != 1:
            raise AdapterFoldError(f"{specialist}: could not patch legacy heading")
    if legacy_style:
        rendered = _strip_generated_by_marker(lane, rendered)
    if fields:
        raise AdapterFoldError(f"{lane}/{specialist}: unexpected overlay fields {sorted(fields)}")
    return rendered


def _strip_generated_by_marker(lane: str, text: str) -> str:
    if lane in ("gpt-codex", "kimi"):
        return re.sub(r"^# generated_by=.*\n", "", text, count=1)
    return re.sub(
        r"^generated_by:.*\n^capability_registry_sha256:.*\n", "", text, count=1, flags=re.MULTILINE
    )


def _apply_audited_registry_sha_exception(rendered: str, on_disk: str) -> tuple[str, str | None]:
    """Substitute ``on_disk``'s registry hash with ``rendered``'s ONLY when
    both sides are exactly the one audited old/new pair. Any other value on
    either side — including a value that merely LOOKS like a plausible hash
    — is left untouched, so it surfaces as a genuine mismatch rather than
    being silently waved through."""

    rendered_matches = list(_REGISTRY_SHA_PATTERN.finditer(rendered))
    disk_matches = list(_REGISTRY_SHA_PATTERN.finditer(on_disk))
    if not rendered_matches or not disk_matches:
        return on_disk, None
    if len(rendered_matches) != len(disk_matches):
        return on_disk, None
    if any(
        match.group(1) != _AUDITED_REGISTRY_SHA_NEW
        for match in rendered_matches
    ):
        return on_disk, None
    if any(
        match.group(1) != _AUDITED_REGISTRY_SHA_OLD for match in disk_matches
    ):
        return on_disk, None
    normalized = on_disk
    for match in reversed(disk_matches):
        start, end = match.span(1)
        normalized = (
            normalized[:start]
            + _AUDITED_REGISTRY_SHA_NEW
            + normalized[end:]
        )
    return normalized, f"registry_sha256: {_AUDITED_REGISTRY_SHA_OLD}->{_AUDITED_REGISTRY_SHA_NEW}"


def _apply_audited_gemini_tools_exception(rendered: str, on_disk: str) -> tuple[str, str | None]:
    """Substitute ``on_disk``'s ``tools:`` line with ``rendered``'s ONLY when
    both sides are exactly the one audited old/new pair. A tampered or
    otherwise-unaudited tools line is left untouched here, so it surfaces
    as a genuine mismatch rather than being silently waved through — this
    is what closes the exact adversarial probe codex's review ran
    (``tools: ["arbitrary-unsafe-tool"]`` must never pass)."""

    rendered_match = _GEMINI_TOOLS_LINE_RE.search(rendered)
    disk_match = _GEMINI_TOOLS_LINE_RE.search(on_disk)
    if not rendered_match or not disk_match:
        return on_disk, None
    if rendered_match.group(0) != _AUDITED_GEMINI_TOOLS_NEW:
        return on_disk, None
    if disk_match.group(0) not in _AUDITED_GEMINI_TOOLS_OLD:
        return on_disk, None
    normalized = on_disk[: disk_match.start()] + _AUDITED_GEMINI_TOOLS_NEW + on_disk[disk_match.end() :]
    return normalized, f"gemini_tools: {disk_match.group(0)!r}->{_AUDITED_GEMINI_TOOLS_NEW!r}"


@dataclass(frozen=True)
class ParityResult:
    """Honest parity outcome: ``byte_identical`` is true only when no audited
    exception was needed. ``exceptions_applied`` enumerates every exact
    substitution, so live-corpus drift stays visible."""

    lane: str
    specialist: str
    byte_identical: bool
    exceptions_applied: tuple[str, ...]


def _prove_normalized_parity_text(rendered: str, on_disk: str, lane: str, specialist: str) -> ParityResult:
    """The pure comparison core (no file I/O) — directly unit-testable with
    synthetic strings, which is what proves the structural-delta property
    holds for ANY input, not merely the specific real files this module
    happens to be exercised against elsewhere."""

    byte_identical = rendered == on_disk
    exceptions: list[str] = []
    normalized_on_disk = on_disk
    if not byte_identical:
        normalized_on_disk, applied = _apply_audited_registry_sha_exception(rendered, normalized_on_disk)
        if applied:
            exceptions.append(applied)
        if lane == "gemini":
            normalized_on_disk, applied = _apply_audited_gemini_tools_exception(rendered, normalized_on_disk)
            if applied:
                exceptions.append(applied)
    if rendered != normalized_on_disk:
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(rendered, normalized_on_disk)) if a != b),
            min(len(rendered), len(normalized_on_disk)),
        )
        window = slice(max(0, first_diff - 40), first_diff + 40)
        raise AdapterFoldError(
            f"{lane}/{specialist}: normalized-parity mismatch at byte {first_diff} "
            f"(audited exceptions applied: {exceptions or 'none'})\n"
            f"  rendered: {rendered[window]!r}\n"
            f"  on_disk : {normalized_on_disk[window]!r}"
        )
    return ParityResult(
        lane=lane, specialist=specialist, byte_identical=byte_identical, exceptions_applied=tuple(exceptions)
    )


def prove_normalized_parity(
    repo_root: Path,
    lane: str,
    specialist: str,
    *,
    overlay_root: Path | None = None,
    override_fields: Mapping[str, Any] | None = None,
) -> ParityResult:
    """Render from canonical+overlay and assert normalized parity against the
    live adapter. ``byte_identical`` and the audited-exception split are
    derived from the live corpus rather than pinned to a historical count.
    Any other divergence — including a corrupted tools list or an unaudited
    hash — fails closed here exactly as a raw diff would.
    """

    root = Path(repo_root)
    rendered = render_adapter_from_overlay(
        root, lane, specialist, overlay_root=overlay_root, override_fields=override_fields
    )
    on_disk = _adapter_path(root, lane, specialist).read_text(encoding="utf-8")
    return _prove_normalized_parity_text(rendered, on_disk, lane, specialist)


def _lane_specialists(repo_root: Path, lane: str) -> tuple[str, ...]:
    if lane == "gpt-codex":
        directory = Path(repo_root) / "model-lanes" / "gpt-codex" / ".codex" / "agents"
        pattern, suffix = "*.toml", ".toml"
    elif lane == "claude":
        directory = Path(repo_root) / "model-lanes" / "claude" / ".claude" / "agents"
        pattern, suffix = "*.md", ".md"
    elif lane == "gemini":
        directory = Path(repo_root) / "model-lanes" / "gemini" / ".gemini" / "agents"
        pattern, suffix = "*.md", ".md"
    elif lane == "kimi":
        directory = Path(repo_root) / "model-lanes" / "kimi" / ".kimi" / "agents"
        pattern, suffix = "*.yaml", ".yaml"
    else:
        raise AdapterFoldError(f"unknown lane: {lane}")
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            candidate.name[: -len(suffix)]
            for candidate in directory.glob(pattern)
            if candidate.stem not in {"README", "exploit_developer"}
        )
    )


def fold_department(
    repo_root: Path, department: str, *, overlay_root: Path | None = None
) -> dict[str, object]:
    """Write overlays + prove normalized parity for every real adapter of one
    department's specialists. Reports the honest byte_identical/exception
    split, not just an undifferentiated pass/fail count."""

    root = Path(repo_root)
    if department == "shared":
        specialists_dir = root / "shared" / "specialists"
    else:
        specialists_dir = root / "departments" / department / "specialists"
    if not specialists_dir.is_dir():
        raise AdapterFoldError(f"no such department: {department}")
    department_specialists = {path.stem for path in specialists_dir.glob("*.md")}

    overlays_written = 0
    parity_failures: list[str] = []
    pairs_checked = 0
    byte_identical_count = 0
    exception_count = 0
    for lane in _LANES:
        for specialist in _lane_specialists(root, lane):
            if specialist not in department_specialists:
                continue
            write_overlay(root, lane, specialist, overlay_root=overlay_root)
            overlays_written += 1
            pairs_checked += 1
            try:
                result = prove_normalized_parity(root, lane, specialist, overlay_root=overlay_root)
            except AdapterFoldError as exc:
                parity_failures.append(str(exc))
                continue
            if result.byte_identical:
                byte_identical_count += 1
            else:
                exception_count += 1
    return {
        "department": department,
        "specialists": len(department_specialists),
        "lane_specialist_pairs": pairs_checked,
        "overlays_written": overlays_written,
        "parity_failures": parity_failures,
        "pairs_checked": pairs_checked,
        "byte_identical_count": byte_identical_count,
        "exception_count": exception_count,
    }


@dataclass(frozen=True)
class LaneContext:
    """Self-contained, composed lane-truth text for one (lane, specialist)
    pair — the overlay's rescued deltas already merged with
    ``lane_adapter_registry.render_adapter``'s shared, non-retiring common
    projection. This, not the raw overlay JSON alone (66/156 of which are
    completely empty), is the unit a role-context compiler should consume
    as full lane truth."""

    schema: str
    lane: str
    specialist: str
    text: str
    overlay_sha256: str
    text_sha256: str


def resolve_lane_context(
    repo_root: Path, lane: str, specialist: str, *, overlay_root: Path | None = None
) -> LaneContext:
    """The shared, non-retiring resolution path a role-context compiler
    should invoke for full lane truth: composes the overlay's rescued
    per-specialist deltas with ``lane_adapter_registry.render_adapter``'s
    already-centralized common projection (capability block, lane
    constants, tool allowlists, sandbox policy). The renderer this fold was
    originally scoped to help retire is instead promoted here to permanent
    shared infrastructure — per the operator's core-swarm-first reframe,
    full native-adapter retirement is not a near-term goal, so the overlay
    can stay a pure delta store without stranding any consumer that needs
    complete lane truth.
    """

    root = Path(repo_root)
    overlay_fields = _read_overlay_fields(root, lane, specialist, overlay_root=overlay_root)
    overlay_sha256 = hashlib.sha256(
        json.dumps(overlay_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    text = render_adapter_from_overlay(root, lane, specialist, overlay_root=overlay_root)
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return LaneContext(
        schema=LANE_CONTEXT_SCHEMA,
        lane=lane,
        specialist=specialist,
        text=text,
        overlay_sha256=overlay_sha256,
        text_sha256=text_sha256,
    )


def write_lane_context_file(
    repo_root: Path, lane: str, specialist: str, dest_path: Path, *, overlay_root: Path | None = None
) -> LaneContext:
    """Materialize a resolved ``LaneContext`` to a file — e.g. as the
    ``lane_overlay_path`` argument ``role_context_compiler.compile_role_context``
    already expects, proving real compositional compatibility without this
    module needing to modify that (out-of-write-scope) compiler at all."""

    context = resolve_lane_context(repo_root, lane, specialist, overlay_root=overlay_root)
    atomic_write_text(Path(dest_path), context.text)
    return context


def verify_lane_context(
    repo_root: Path,
    lane: str,
    specialist: str,
    previous: LaneContext,
    *,
    overlay_root: Path | None = None,
) -> LaneContext:
    """Re-resolve and confirm lane truth has not silently drifted since
    ``previous`` was materialized — the "verifies" half of "a shared,
    non-retiring module the compiler invokes and verifies". Raises rather
    than silently trusting stale content."""

    if (
        previous.schema != LANE_CONTEXT_SCHEMA
        or previous.lane != lane
        or previous.specialist != specialist
    ):
        raise AdapterFoldError(
            f"{lane}/{specialist}: previous lane context identity mismatch"
        )
    previous_text_sha256 = hashlib.sha256(
        previous.text.encode("utf-8")
    ).hexdigest()
    if previous_text_sha256 != previous.text_sha256:
        raise AdapterFoldError(
            f"{lane}/{specialist}: previous lane context content hash mismatch"
        )
    current = resolve_lane_context(
        repo_root, lane, specialist, overlay_root=overlay_root
    )
    if previous.overlay_sha256 != current.overlay_sha256:
        raise AdapterFoldError(
            f"{lane}/{specialist}: overlay fields drifted since resolution"
        )
    if current.text_sha256 != previous.text_sha256:
        raise AdapterFoldError(
            f"{lane}/{specialist}: lane context drifted since it was resolved "
            f"(was {previous.text_sha256}, now {current.text_sha256})"
        )
    return current


__all__ = [
    "OVERLAY_SCHEMA",
    "LANE_CONTEXT_SCHEMA",
    "AdapterFoldError",
    "ParityResult",
    "LaneContext",
    "overlay_path",
    "extract_overlay_fields",
    "write_overlay",
    "render_adapter_from_overlay",
    "prove_normalized_parity",
    "fold_department",
    "resolve_lane_context",
    "write_lane_context_file",
    "verify_lane_context",
]
