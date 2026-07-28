from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol


VERDICTS = frozenset({"duplicate", "likely-duplicate", "novel"})
TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._+-]*")
DEDUP_KEY_PATTERN = re.compile(r"(?:finding|chain):v1:[a-f0-9]{64}")


class PriorArtSource(Protocol):
    name: str

    def search(
        self,
        target: str | Mapping[str, Any],
        item: dict[str, Any],
        query: dict[str, Any],
    ) -> Iterable[Mapping[str, Any]]:
        """Return candidate prior-art records for one target and item."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_text(item)}" for key, item in sorted(value.items()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(_text(item) for item in value)
    return str(value)


def _normalized_text(value: Any) -> str:
    return " ".join(TOKEN_PATTERN.findall(_text(value).casefold()))


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            _normalized_text(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: _normalized_text(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical(item) for item in value]
    return _normalized_text(value)


def _digest(kind: str, payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        _canonical(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{kind}:v1:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _target_name(target: str | Mapping[str, Any]) -> str:
    if isinstance(target, str):
        name = target.strip()
    elif isinstance(target, Mapping):
        name = str(
            target.get("name")
            or target.get("id")
            or target.get("target")
            or ""
        ).strip()
    else:
        name = ""
    if not name:
        raise ValueError("target must be a non-empty string or mapping with name/id")
    return name


def _is_chain(item: Mapping[str, Any]) -> bool:
    return item.get("kind") in {"chain", "composite_chain"} or (
        "terminus" in item and "links" in item
    )


def _validate_item(item: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise ValueError("item must be a finding or composite-chain mapping")
    normalized = dict(item)
    if _is_chain(normalized):
        terminus = normalized.get("terminus")
        links = normalized.get("links")
        if not isinstance(terminus, (str, Mapping)) or not _normalized_text(terminus):
            raise ValueError("a composite chain requires a non-empty terminus")
        if (
            not isinstance(links, Sequence)
            or isinstance(links, (str, bytes, bytearray))
            or not links
            or any(not isinstance(link, (str, Mapping)) for link in links)
        ):
            raise ValueError("a composite chain requires a non-empty links list")
        normalized["kind"] = "composite_chain"
        return normalized
    if not _normalized_text(normalized.get("component")):
        raise ValueError("a finding requires an affected component")
    normalized["kind"] = "finding"
    return normalized


def _finding_identity(item: Mapping[str, Any]) -> dict[str, Any]:
    weakness = (
        item.get("weakness")
        or item.get("vulnerability_type")
        or item.get("cwe")
        or item.get("category")
        or item.get("title")
    )
    return {
        "component": item.get("component"),
        "version": item.get("version") or item.get("affected_version"),
        "weakness": weakness,
    }


def _explicit_weakness(item: Mapping[str, Any]) -> Any:
    return (
        item.get("weakness")
        or item.get("vulnerability_type")
        or item.get("cwe")
        or item.get("category")
    )


def finding_key(target: str | Mapping[str, Any], item: Mapping[str, Any]) -> str:
    finding = _validate_item(item)
    if finding["kind"] != "finding":
        raise ValueError("finding_key requires a single finding")
    return _digest(
        "finding",
        {"target": _target_name(target), **_finding_identity(finding)},
    )


def _link_signature(link: Any) -> str:
    return json.dumps(
        _canonical(link),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def composite_chain_key(
    target: str | Mapping[str, Any],
    item: Mapping[str, Any],
) -> str:
    chain = _validate_item(item)
    if chain["kind"] != "composite_chain":
        raise ValueError("composite_chain_key requires a composite chain")
    links = sorted({_link_signature(link) for link in chain["links"]})
    return _digest(
        "chain",
        {
            "target": _target_name(target),
            "terminus": chain["terminus"],
            "links": links,
        },
    )


def _dedup_key(target: str | Mapping[str, Any], item: Mapping[str, Any]) -> str:
    if _is_chain(item):
        return composite_chain_key(target, item)
    return finding_key(target, item)


def _tokens(*values: Any) -> set[str]:
    return set(TOKEN_PATTERN.findall(" ".join(_text(value) for value in values).casefold()))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _field_matches(expected: Any, candidate: Any) -> bool:
    normalized_expected = _normalized_text(expected)
    if not normalized_expected:
        return False
    if isinstance(candidate, Sequence) and not isinstance(
        candidate, (str, bytes, bytearray)
    ):
        return any(
            normalized_expected == _normalized_text(value) for value in candidate
        )
    return normalized_expected == _normalized_text(candidate)


def _candidate_item(candidate: Mapping[str, Any]) -> dict[str, Any]:
    nested = candidate.get("item")
    if isinstance(nested, Mapping):
        return dict(nested)
    fields = {
        key: candidate[key]
        for key in (
            "kind",
            "title",
            "component",
            "version",
            "affected_version",
            "weakness",
            "vulnerability_type",
            "cwe",
            "category",
            "keywords",
            "terminus",
            "links",
        )
        if key in candidate
    }
    return fields


def _candidate_exact_key(
    target: str | Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> str | None:
    explicit = candidate.get("dedup_key")
    if isinstance(explicit, str) and DEDUP_KEY_PATTERN.fullmatch(explicit):
        return explicit
    for key in DEDUP_KEY_PATTERN.findall(
        _text((candidate.get("title"), candidate.get("summary"), candidate.get("snippet")))
    ):
        return key
    candidate_item = _candidate_item(candidate)
    try:
        return _dedup_key(target, candidate_item)
    except (TypeError, ValueError):
        return None


def _finding_similarity(
    item: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[float, list[str]]:
    other = _candidate_item(candidate)
    score = 0.0
    basis: list[str] = []
    component = _normalized_text(item.get("component"))
    other_component = other.get("component")
    if _field_matches(component, other_component):
        score += 0.35
        basis.append("affected component")
    version = _normalized_text(item.get("version") or item.get("affected_version"))
    other_version = other.get("version") or other.get("affected_version")
    if _field_matches(version, other_version):
        score += 0.15
        basis.append("affected version")
    weakness = _normalized_text(_finding_identity(item)["weakness"])
    other_weakness_value = _explicit_weakness(other)
    other_weakness = _normalized_text(other_weakness_value)
    if _field_matches(weakness, other_weakness_value):
        score += 0.20
        basis.append("weakness")
    lexical = _jaccard(
        _tokens(
            item.get("title"),
            item.get("keywords"),
            item.get("component"),
            item.get("version") or item.get("affected_version"),
            weakness,
        ),
        _tokens(
            other.get("title"),
            other.get("keywords"),
            other_weakness,
            candidate.get("title"),
            candidate.get("summary"),
            candidate.get("snippet"),
        ),
    )
    if lexical:
        structured_fields_present = sum(
            bool(_normalized_text(value))
            for value in (other_component, other_version, other_weakness)
        )
        lexical_weight = 0.30 if structured_fields_present else 0.85
        score += lexical_weight * lexical
        basis.append(f"keyword overlap {lexical:.2f}")
    return min(score, 1.0), basis


def _chain_similarity(
    item: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[float, list[str]]:
    other = _candidate_item(candidate)
    if not _is_chain(other):
        overlap = _jaccard(
            _tokens(item.get("links")),
            _tokens(other, candidate.get("title"), candidate.get("snippet")),
        )
        return 0.25 * overlap, [f"individual-link-only overlap {overlap:.2f}"] if overlap else []

    terminus_overlap = _jaccard(
        _tokens(item.get("terminus")),
        _tokens(other.get("terminus")),
    )
    left_links = {_link_signature(link) for link in item.get("links", [])}
    right_links = {_link_signature(link) for link in other.get("links", [])}
    links_overlap = _jaccard(left_links, right_links)
    basis = [
        f"terminus overlap {terminus_overlap:.2f}",
        f"link-set overlap {links_overlap:.2f}",
    ]
    return (0.5 * terminus_overlap) + (0.5 * links_overlap), basis


def _query(
    target: str | Mapping[str, Any],
    item: Mapping[str, Any],
    dedup_key: str,
) -> dict[str, Any]:
    if _is_chain(item):
        terms = sorted(_tokens(item.get("terminus"), item.get("links")))
        component = item.get("component")
        version = item.get("version")
        item_kind = "composite_chain"
    else:
        terms = sorted(
            _tokens(
                item.get("title"),
                item.get("component"),
                item.get("version"),
                item.get("weakness"),
                item.get("keywords"),
            )
        )
        component = item.get("component")
        version = item.get("version") or item.get("affected_version")
        item_kind = "finding"
    return {
        "target": _target_name(target),
        "item_kind": item_kind,
        "component": component,
        "version": version,
        "terms": terms[:24],
        "phrase": " ".join(terms[:12]),
        "dedup_key": dedup_key,
    }


def _normalize_hit(
    source: str,
    candidate: Mapping[str, Any],
    similarity: float,
    basis: list[str],
    exact: bool,
) -> dict[str, Any]:
    source_id = candidate.get("id") or candidate.get("source_id")
    hit: dict[str, Any] = {
        "source": source,
        "source_id": str(source_id) if source_id is not None else None,
        "title": str(candidate.get("title") or source_id or "untitled prior art"),
        "url": candidate.get("url"),
        "similarity": round(similarity, 4),
        "similarity_basis": ["exact dedup key", *basis] if exact else basis,
    }
    return hit


def prior_art_check(
    target: str | Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    sources: Iterable[PriorArtSource] | None = None,
) -> dict[str, Any]:
    """Search pluggable prior-art sources and return a structured dedup verdict."""
    validated_item = _validate_item(item)
    target_name = _target_name(target)
    item_kind = validated_item["kind"]
    dedup_key = _dedup_key(target, validated_item)
    query = _query(target, validated_item, dedup_key)

    if sources is None:
        from .sources import default_sources

        sources = default_sources()

    hits: list[dict[str, Any]] = []
    source_statuses: list[dict[str, Any]] = []
    best_verdict = "novel"
    best_similarity = 0.0

    for source in sources:
        source_name = str(getattr(source, "name", type(source).__name__))
        try:
            candidates = list(source.search(target, validated_item, query))
        except Exception as exc:
            source_statuses.append(
                {
                    "source": source_name,
                    "status": "unavailable",
                    "hit_count": 0,
                    "error": type(exc).__name__,
                }
            )
            continue

        source_hits = 0
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            candidate_target = candidate.get("target")
            if (
                candidate_target
                and _normalized_text(candidate_target) != _normalized_text(target_name)
            ):
                continue
            candidate_key = _candidate_exact_key(target, candidate)
            exact = candidate_key == dedup_key
            if item_kind == "composite_chain":
                similarity, basis = _chain_similarity(validated_item, candidate)
            else:
                similarity, basis = _finding_similarity(validated_item, candidate)
            if exact:
                similarity = 1.0
            if not exact and similarity < 0.42:
                continue
            hits.append(
                _normalize_hit(source_name, candidate, similarity, basis, exact)
            )
            source_hits += 1
            best_similarity = max(best_similarity, similarity)
            if exact:
                best_verdict = "duplicate"
            elif best_verdict != "duplicate" and similarity >= 0.72:
                best_verdict = "likely-duplicate"

        source_statuses.append(
            {
                "source": source_name,
                "status": "ok",
                "hit_count": source_hits,
            }
        )

    hits.sort(
        key=lambda hit: (
            -float(hit["similarity"]),
            str(hit["source"]),
            str(hit["source_id"] or ""),
        )
    )
    if best_verdict == "duplicate":
        rationale = "An exact target-scoped dedup key was found in prior art."
    elif best_verdict == "likely-duplicate":
        rationale = (
            "No exact key matched, but prior art overlaps the affected component/version "
            "or the composite terminus and link set above the likely-duplicate threshold."
        )
    else:
        rationale = (
            "No exact or high-similarity target-scoped prior art was returned by the "
            "available sources; novel is provisional when any source is unavailable."
        )
    return {
        "target": target_name,
        "item_kind": item_kind,
        "dedup_key": dedup_key,
        "verdict": best_verdict,
        "rationale": rationale,
        "best_similarity": round(best_similarity, 4),
        "hits": hits,
        "sources_consulted": source_statuses,
    }
