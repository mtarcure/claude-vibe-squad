#!/usr/bin/env python3
"""Resolve and validate a task capability into an immutable dispatch snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from validate_capabilities import MODES, Validator, parse_frontmatter


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
GATE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DEGRADED_STATES = {"degraded-blueprint", "needs_tool"}


class CapabilityDispatchError(ValueError):
    """The packet's capability pointer cannot produce a valid snapshot."""


def parse_gates(raw: str) -> list[str]:
    value = raw.strip()
    if value == "[]":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        raise CapabilityDispatchError("capability card gates must be an inline list")
    gates = [part.strip().strip("'\"") for part in value[1:-1].split(",")]
    if any(not GATE_RE.fullmatch(gate) for gate in gates):
        raise CapabilityDispatchError("capability card contains a malformed gate token")
    return gates


def resolve_snapshot(
    root: Path, mode: str, capability: str, acknowledgement: str = ""
) -> dict[str, object]:
    """Return the validator-derived immutable snapshot for one capability pointer."""
    root = root.resolve()
    mode = mode.strip()
    reference = capability.strip()
    if mode not in MODES:
        raise CapabilityDispatchError(
            f"capability requires a valid mode; got {mode or 'missing'!r}"
        )
    if "/" in reference:
        parts = reference.split("/")
        if len(parts) != 2 or not all(SLUG_RE.fullmatch(part) for part in parts):
            raise CapabilityDispatchError(f"malformed capability reference: {reference!r}")
        reference_mode, slug = parts
        if reference_mode != mode:
            raise CapabilityDispatchError(
                f"capability mode mismatch: packet mode {mode!r}, reference {reference!r}"
            )
    else:
        if not SLUG_RE.fullmatch(reference):
            raise CapabilityDispatchError(f"malformed capability slug: {reference!r}")
        slug = reference

    card = root / "shared" / "capabilities" / mode / f"{slug}.md"
    if not card.is_file() or card.is_symlink():
        raise CapabilityDispatchError(
            f"capability card does not exist for mode {mode!r}: {slug!r}"
        )
    raw = card.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CapabilityDispatchError(f"capability card is not UTF-8: {card}") from exc

    result = Validator(root).validate_text(
        text, card.relative_to(root).as_posix(), card
    )
    if result["status"] != "pass":
        codes = sorted(
            str(error.get("code", "unknown"))
            for error in result.get("errors", [])
            if isinstance(error, dict)
        )
        raise CapabilityDispatchError(
            f"capability card fails validation: {','.join(codes) or 'unknown'}"
        )
    frontmatter, _body_start, frontmatter_findings = parse_frontmatter(text)
    if frontmatter_findings:
        raise CapabilityDispatchError("capability card frontmatter is malformed")

    derived_state = str(result["derived_state"])
    base_state = derived_state.split(":", 1)[0]
    acknowledgement = acknowledgement.strip()
    if base_state not in DEGRADED_STATES and acknowledgement not in {"", "none"}:
        raise CapabilityDispatchError(
            f"capability {frontmatter['id']} derives {derived_state}; "
            "degradation acknowledgement is not applicable"
        )
    hold = base_state in DEGRADED_STATES and acknowledgement != derived_state
    return {
        "capability_id": frontmatter["id"],
        "capability_card_path": card.relative_to(root).as_posix(),
        "capability_card_sha256": hashlib.sha256(raw).hexdigest(),
        "capability_derived_state": derived_state,
        "capability_gates": parse_gates(frontmatter["gates"]),
        "capability_degradation_ack": acknowledgement,
        "dispatch_decision": "hold" if hold else "allow",
        "hold_reason": (
            f"capability {frontmatter['id']} derives {derived_state}; add "
            f"capability_degradation_ack: {derived_state} to acknowledge the typed degradation"
            if hold
            else ""
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--ack", default="")
    args = parser.parse_args()
    try:
        snapshot = resolve_snapshot(args.root, args.mode, args.capability, args.ack)
    except (CapabilityDispatchError, OSError, KeyError) as exc:
        print(f"capability dispatch validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
