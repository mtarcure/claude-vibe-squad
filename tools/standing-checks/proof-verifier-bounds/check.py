#!/usr/bin/env python3
"""Static evidence checker for Merkle/MMR proof-verifier invariants.

The checker is deliberately conservative: a missing syntactic guard is a review hit,
while a present guard is only a source-level signal that still needs manual control-flow
and call-site validation.  It has no third-party Python dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


INVARIANTS = {
    "I1": "strict_index_bounds",
    "I2": "exhaustive_leaf_consumption",
    "I3": "strict_order_and_uniqueness",
    "I4": "total_proof_consumption",
    "I5": "positional_binding",
}

EXCLUDED_PARTS = {
    ".git",
    "target",
    "node_modules",
    "cache",
    "artifacts",
    "out",
    "build",
}


@dataclass(frozen=True)
class FunctionBlock:
    name: str
    signature: str
    clean: str
    original: str
    start_line: int


@dataclass(frozen=True)
class InvariantResult:
    invariant: str
    name: str
    status: str
    evidence_line: int | None
    evidence: str | None


@dataclass(frozen=True)
class FunctionResult:
    path: str
    language: str
    function: str
    start_line: int
    invariants: list[InvariantResult]

    @property
    def missing(self) -> list[str]:
        return [item.invariant for item in self.invariants if item.status == "missing_signal"]


def strip_comments_and_strings(source: str, language: str) -> str:
    """Replace comments and string contents with spaces while preserving offsets/newlines."""

    chars = list(source)
    i = 0
    state = "code"
    quote = ""
    while i < len(chars):
        current = chars[i]
        following = chars[i + 1] if i + 1 < len(chars) else ""
        if state == "code":
            if current == "/" and following == "/":
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "line_comment"
                continue
            if current == "/" and following == "*":
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "block_comment"
                continue
            rust_char = (
                language == "rust"
                and current == "'"
                and (
                    (i + 2 < len(chars) and chars[i + 2] == "'")
                    or (i + 3 < len(chars) and chars[i + 1] == "\\" and chars[i + 3] == "'")
                )
            )
            # A Rust lifetime such as &'static is not a quoted string.
            if current == '"' or (current == "'" and (language == "solidity" or rust_char)):
                quote = current
                chars[i] = " "
                i += 1
                state = "string"
                continue
            i += 1
            continue
        if state == "line_comment":
            if current == "\n":
                state = "code"
            else:
                chars[i] = " "
            i += 1
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "code"
            else:
                if current != "\n":
                    chars[i] = " "
                i += 1
            continue
        if state == "string":
            if current == "\\":
                chars[i] = " "
                if i + 1 < len(chars) and chars[i + 1] != "\n":
                    chars[i + 1] = " "
                i += 2
                continue
            if current == quote:
                chars[i] = " "
                i += 1
                state = "code"
            else:
                if current != "\n":
                    chars[i] = " "
                i += 1
    return "".join(chars)


def matching_brace(text: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def strip_statically_dead_blocks(clean: str) -> str:
    """Ignore the simplest decoy guards placed under literal-false branches."""

    chars = list(clean)
    pattern = re.compile(r"\bif\s*(?:\(\s*false\s*\)|false)\s*\{")
    for match in list(pattern.finditer(clean)):
        opening = clean.find("{", match.start())
        closing = matching_brace(clean, opening)
        if closing is None:
            continue
        for index in range(match.start(), closing + 1):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def extract_functions(source: str, language: str) -> list[FunctionBlock]:
    clean_source = strip_statically_dead_blocks(strip_comments_and_strings(source, language))
    if language == "solidity":
        pattern = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\s*\(")
    else:
        pattern = re.compile(
            r"\b(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)\s*\("
        )

    blocks: list[FunctionBlock] = []
    for match in pattern.finditer(clean_source):
        if language == "rust":
            prefix = clean_source[max(0, match.start() - 200) : match.start()]
            if re.search(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]\s*$", prefix):
                continue
        opening = clean_source.find("{", match.end())
        semicolon = clean_source.find(";", match.end())
        if opening < 0 or (semicolon >= 0 and semicolon < opening):
            continue
        closing = matching_brace(clean_source, opening)
        if closing is None:
            continue
        start = match.start()
        blocks.append(
            FunctionBlock(
                name=match.group(1),
                signature=clean_source[start:opening],
                clean=clean_source[start : closing + 1],
                original=source[start : closing + 1],
                start_line=source.count("\n", 0, start) + 1,
            )
        )
    return blocks


def is_candidate(block: FunctionBlock) -> bool:
    text = (block.signature + "\n" + block.clean).lower()
    has_proof = bool(re.search(r"\b(proof|proofs|witness|siblings?)\b", text))
    has_leaf = bool(re.search(r"\b(leaf|leaves|leafcount|leaf_count)\b", text))
    verifier_semantics = bool(
        re.search(
            r"(verify|verification|calculate_?root|compute_?root|merkle|mmr|mountain|multiproof|peak|root)",
            text,
        )
    )
    hash_semantics = bool(re.search(r"(keccak256|sha256|hashv?|digest|hasher|fold_hash)", text))
    return has_proof and has_leaf and (verifier_semantics or hash_semantics)


def loop_blocks(clean: str, language: str) -> list[tuple[str, str, int]]:
    if language == "solidity":
        loop_re = re.compile(r"\bfor\s*\(([^)]*)\)\s*\{")
    else:
        loop_re = re.compile(r"\bfor\s+([^\{]+?)\s*\{")
    loops: list[tuple[str, str, int]] = []
    for match in loop_re.finditer(clean):
        opening = clean.find("{", match.start())
        closing = matching_brace(clean, opening)
        if closing is not None:
            loops.append((match.group(1), clean[opening + 1 : closing], opening + 1))
    return loops


def source_evidence(block: FunctionBlock, offset: int) -> tuple[int, str]:
    line = block.start_line + block.clean.count("\n", 0, offset)
    relative_line = block.clean.count("\n", 0, offset)
    original_lines = block.original.splitlines()
    snippet = original_lines[relative_line].strip() if relative_line < len(original_lines) else ""
    return line, snippet[:240]


def result_from_match(
    invariant: str,
    block: FunctionBlock,
    match_offset: int | None,
) -> InvariantResult:
    if match_offset is None:
        return InvariantResult(
            invariant=invariant,
            name=INVARIANTS[invariant],
            status="missing_signal",
            evidence_line=None,
            evidence=None,
        )
    line, snippet = source_evidence(block, match_offset)
    return InvariantResult(
        invariant=invariant,
        name=INVARIANTS[invariant],
        status="present_signal",
        evidence_line=line,
        evidence=snippet,
    )


def first_match(text: str, patterns: Iterable[str]) -> int | None:
    hits: list[int] = []
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            hits.append(match.start())
    return min(hits) if hits else None


def index_bounds(block: FunctionBlock, language: str) -> int | None:
    for header, body, offset in loop_blocks(block.clean, language):
        if language == "solidity":
            variable_match = re.search(r"(?:uint(?:8|16|32|64|128|256)?\s+)?(\w+)\s*(?:=\s*0)?\s*;", header)
            if not variable_match or not re.search(r"(?:leaves?\.length|leaves?len)\b", header, re.I):
                continue
            variable = re.escape(variable_match.group(1))
            leaf = rf"leaves?\s*\[\s*{variable}\s*\]\s*\.\s*(?:index|position)"
            count = r"(?:leafCount|leaf_count|totalLeaves|total_leaves|leavesCount|leaves_count)"
            patterns = [
                rf"(?:require|assert)\s*\(\s*{leaf}\s*<\s*{count}\b",
                rf"if\s*\(\s*{leaf}\s*>=\s*{count}\b[^)]*\)\s*(?:\{{[^}}]*\}}|revert\b)",
                rf"if\s*\(\s*{count}\s*<=\s*{leaf}\b[^)]*\)\s*(?:\{{[^}}]*\}}|revert\b)",
            ]
        else:
            index_loop = re.search(r"(\w+)\s+in\s+0\s*\.\.\s*leaves?\.len\s*\(\s*\)", header, re.I)
            item_loop = re.search(r"(\w+)\s+in\s+(?:&\s*)?leaves?\.iter\s*\(\s*\)", header, re.I)
            if index_loop:
                leaf = rf"leaves?\s*\[\s*{re.escape(index_loop.group(1))}\s*\]\s*\.\s*(?:index|position)"
            elif item_loop:
                leaf = rf"{re.escape(item_loop.group(1))}\s*\.\s*(?:index|position)"
            else:
                continue
            count = r"(?:leaf_count|leafCount|total_leaves|leaves_count)"
            patterns = [
                rf"(?<![A-Za-z0-9_])(?:require|assert|ensure)!\s*\(\s*{leaf}\s*<\s*{count}\b",
                rf"if\s+{leaf}\s*>=\s*{count}\b[^\{{]*\{{[^}}]*(?:return\s+Err|return\s+err|panic!)",
                rf"if\s+{count}\s*<=\s*{leaf}\b[^\{{]*\{{[^}}]*(?:return\s+Err|return\s+err|panic!)",
            ]
        local = first_match(body, patterns)
        if local is not None:
            return offset + local

    if language == "rust":
        quantified = first_match(
            block.clean,
            [
                r"leaves?\.iter\s*\(\s*\)\.all\s*\(\s*\|\s*(\w+)\s*\|\s*\1\.(?:index|position)\s*<\s*(?:leaf_count|total_leaves)",
            ],
        )
        if quantified is not None:
            return quantified
    return None


def strict_order(block: FunctionBlock, language: str) -> int | None:
    for header, body, offset in loop_blocks(block.clean, language):
        if language == "solidity":
            variable_match = re.search(r"(?:uint(?:8|16|32|64|128|256)?\s+)?(\w+)\s*=\s*1\s*;", header)
            if not variable_match or not re.search(r"leaves?\.length", header, re.I):
                continue
            variable = re.escape(variable_match.group(1))
            current = rf"leaves?\s*\[\s*{variable}\s*\]\s*\.\s*(?:index|position)"
            previous = rf"leaves?\s*\[\s*{variable}\s*-\s*1\s*\]\s*\.\s*(?:index|position)"
            patterns = [
                rf"(?:require|assert)\s*\(\s*{current}\s*>\s*{previous}",
                rf"if\s*\(\s*{current}\s*<=\s*{previous}[^)]*\)\s*(?:\{{[^}}]*\}}|revert\b)",
            ]
        else:
            variable_match = re.search(r"(\w+)\s+in\s+1\s*\.\.\s*leaves?\.len\s*\(\s*\)", header, re.I)
            if not variable_match:
                continue
            variable = re.escape(variable_match.group(1))
            current = rf"leaves?\s*\[\s*{variable}\s*\]\s*\.\s*(?:index|position)"
            previous = rf"leaves?\s*\[\s*{variable}\s*-\s*1\s*\]\s*\.\s*(?:index|position)"
            patterns = [
                rf"(?<![A-Za-z0-9_])(?:require|assert|ensure)!\s*\(\s*{current}\s*>\s*{previous}",
                rf"if\s+{current}\s*<=\s*{previous}\s*\{{[^}}]*(?:return\s+Err|return\s+err|panic!)",
            ]
        local = first_match(body, patterns)
        if local is not None:
            return offset + local

    if language == "rust":
        return first_match(
            block.clean,
            [
                r"leaves?\.windows\s*\(\s*2\s*\)\.all\s*\(\s*\|\s*(\w+)\s*\|\s*\1\s*\[\s*1\s*\]\.(?:index|position)\s*>\s*\1\s*\[\s*0\s*\]\.(?:index|position)",
            ],
        )
    return None


def consumption_guard(block: FunctionBlock, language: str, kind: str) -> int | None:
    assert kind in {"leaf", "proof"}
    if kind == "leaf":
        counter = r"(?:leafPos|leaf_pos|leafIndex|leaf_index|leavesConsumed|leaves_consumed|leafIter\.offset|leaf_iter\.offset)"
        length = r"(?:leaves?\.length|leaves?\.len\s*\(\s*\)|leavesLen|leaves_len|leafIter\.data\.length|leaf_iter\.data\.len\s*\(\s*\))"
        residual = r"(?:leafIter\.length|leaf_iter\.len\s*\(\s*\))"
    else:
        counter = r"(?:proofPos|proof_pos|proofIndex|proof_index|proofOffset|proof_offset|proofIter\.offset|proof_iter\.offset)"
        length = r"(?:proofs?\.length|proofs?\.len\s*\(\s*\)|proofs?Len|proofs?_len|proofIter\.data\.length|proof_iter\.data\.len\s*\(\s*\))"
        residual = r"(?:proofIter\.length|proof_iter\.len\s*\(\s*\))"

    if language == "solidity":
        patterns = [
            rf"(?:require|assert)\s*\(\s*{counter}\s*==\s*{length}\b",
            rf"(?:require|assert)\s*\(\s*{length}\s*==\s*{counter}\b",
            rf"if\s*\(\s*{counter}\s*!=\s*{length}\s*\)\s*(?:\{{[^}}]*revert[^}}]*\}}|revert\b)",
            rf"if\s*\(\s*{residual}\s*!=\s*0\s*\)\s*(?:\{{[^}}]*revert[^}}]*\}}|revert\b)",
            rf"if\s*\([^;{{}}]*{counter}\s*==\s*{length}[^;{{}}]*\)\s*revert\b",
        ]
    else:
        patterns = [
            rf"(?<![A-Za-z0-9_])(?:require|assert|ensure)!\s*\(\s*{counter}\s*==\s*{length}\b",
            rf"if\s+{counter}\s*!=\s*{length}\s*\{{[^}}]*(?:return\s+Err|return\s+err|panic!)",
            rf"if\s+{residual}\s*!=\s*0\s*\{{[^}}]*(?:return\s+Err|return\s+err|panic!)",
            rf"(?<![A-Za-z0-9_])(?:require|assert|ensure)!\s*\(\s*{kind}_iter\.next\s*\(\s*\)\.is_none\s*\(\s*\)",
        ]
    match = first_match(block.clean, patterns)
    if match is None:
        return None

    # A consumption assertion before any reconstruction/consumption is likely vacuous.
    consumption_patterns = (
        [r"leafPos\s*\+\+", r"leaf_pos\s*\+=\s*1", r"_next\s*\(\s*leafIter", r"leaf_iter\.next\s*\("]
        if kind == "leaf"
        else [r"proofPos\s*\+\+", r"proof_pos\s*\+=\s*1", r"_next\s*\(\s*proofIter", r"proof_iter\.next\s*\("]
    )
    consumed_at = [m.start() for pattern in consumption_patterns for m in re.finditer(pattern, block.clean, re.I)]
    if consumed_at and match <= min(consumed_at):
        return None
    return match


def positional_binding(block: FunctionBlock, language: str) -> int | None:
    expected_position_patterns = [
        r"(?<![A-Za-z0-9_])(?:require|assert|ensure)!?\s*\([^;\n]*(?:\.index|\.position)[^;\n]*(?:expectedIndex|expected_index|expectedPosition|expected_position|sequence|nonce)",
        r"if\s*\(?[^;\n]*(?:\.index|\.position)\s*!=\s*(?:expectedIndex|expected_index|expectedPosition|expected_position|sequence|nonce)[^\{;]*\{?[^}]*?(?:revert|return\s+Err|return\s+err)",
    ]
    direct_hash_patterns = [
        r"keccak256\s*\(\s*abi\.encode(?:Packed)?\s*\([^;)]*(?:\.index|\.position|\bindex\b|\bposition\b)[^;)]*(?:\.data|\.value|\bdata\b|\bvalue\b|\bpayload\b)",
        r"(?:hashv?|digest|fold_hash|hash_pair)\s*!?\s*\([^;\n]*(?:\.index|\.position|index_bytes|position_bytes)[^;\n]*(?:\.data|\.value|data|value|payload)",
        r"(?:hashv?|digest|fold_hash|hash_pair)\s*!?\s*\([^;\n]*(?:\.data|\.value|data|value|payload)[^;\n]*(?:\.index|\.position|index_bytes|position_bytes)",
    ]
    match = first_match(block.clean, expected_position_patterns + direct_hash_patterns)
    if match is not None:
        return match

    if language == "rust":
        derived = re.finditer(
            r"let\s+(\w*(?:index|position)\w*)\s*=\s*[^;]*(?:\.index|\.position)\.to_(?:le|be)_bytes\s*\(\s*\)",
            block.clean,
            re.I,
        )
        for item in derived:
            variable = re.escape(item.group(1))
            later = block.clean[item.end() :]
            linked = re.search(
                rf"(?:hashv?|digest|fold_hash|hash_pair)\s*!?\s*\([^;\n]*{variable}[^;\n]*(?:\.data|\.value|data|value|payload)",
                later,
                re.I,
            )
            if linked:
                return item.start()
    return None


def analyze_function(path: Path, language: str, block: FunctionBlock) -> FunctionResult:
    evidence = {
        "I1": index_bounds(block, language),
        "I2": consumption_guard(block, language, "leaf"),
        "I3": strict_order(block, language),
        "I4": consumption_guard(block, language, "proof"),
        "I5": positional_binding(block, language),
    }
    return FunctionResult(
        path=str(path),
        language=language,
        function=block.name,
        start_line=block.start_line,
        invariants=[result_from_match(invariant, block, evidence[invariant]) for invariant in INVARIANTS],
    )


def infer_language(path: Path, requested: str) -> str | None:
    if requested != "auto":
        expected = ".sol" if requested == "solidity" else ".rs"
        return requested if path.suffix == expected else None
    if path.suffix == ".sol":
        return "solidity"
    if path.suffix == ".rs":
        return "rust"
    return None


def source_files(inputs: Sequence[Path], language: str) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_file():
            if infer_language(item, language):
                files.append(item)
            continue
        if item.is_dir():
            for candidate in item.rglob("*"):
                if not candidate.is_file() or any(part in EXCLUDED_PARTS for part in candidate.parts):
                    continue
                if infer_language(candidate, language):
                    files.append(candidate)
    return sorted(set(files))


def analyze(
    inputs: Sequence[Path],
    language: str,
    entrypoint: str | None = None,
) -> tuple[list[FunctionResult], int]:
    results: list[FunctionResult] = []
    files = source_files(inputs, language)
    for path in files:
        source = path.read_text(encoding="utf-8", errors="replace")
        selected_language = infer_language(path, language)
        assert selected_language is not None
        for block in extract_functions(source, selected_language):
            if entrypoint and not re.search(entrypoint, block.name):
                continue
            if is_candidate(block):
                results.append(analyze_function(path, selected_language, block))
    return results, len(files)


def serializable(results: Sequence[FunctionResult], files_scanned: int) -> dict[str, object]:
    return {
        "schema": "proof-verifier-bounds/result-v1",
        "files_scanned": files_scanned,
        "candidate_functions": len(results),
        "disposition": "review_hits" if any(result.missing for result in results) else ("signals_complete" if results else "no_candidates"),
        "results": [
            {
                **{key: value for key, value in asdict(result).items() if key != "invariants"},
                "missing": result.missing,
                "invariants": [asdict(item) for item in result.invariants],
            }
            for result in results
        ],
        "limits": [
            "present_signal is syntactic evidence, not a proof of reachability or dominance",
            "missing_signal is a review hit, not a vulnerability finding",
            "no_candidates is not a clean scan",
            "positional binding can be owned by a caller and requires call-site tracing",
        ],
    }


def print_text(results: Sequence[FunctionResult], files_scanned: int) -> None:
    print(f"FILES_SCANNED {files_scanned}")
    print(f"CANDIDATE_FUNCTIONS {len(results)}")
    for result in results:
        print(f"CANDIDATE {result.language} {result.path}:{result.start_line} {result.function}")
        for item in result.invariants:
            suffix = ""
            if item.evidence_line is not None:
                suffix = f" line={item.evidence_line} evidence={item.evidence!r}"
            print(f"  {item.invariant} {item.name} {item.status}{suffix}")
        print(f"  MISSING {','.join(result.missing) if result.missing else 'none'}")
    if not results:
        print("DISPOSITION no_candidates (not a clean scan)")
    elif any(result.missing for result in results):
        print("DISPOSITION review_hits (not findings)")
    else:
        print("DISPOSITION signals_complete (manual dominance and call-site review still required)")


def fixture_expectations(root: Path) -> list[tuple[str, str, Path, set[str]]]:
    controls: list[tuple[str, str, Path, set[str]]] = []
    for language, directory, extension in (
        ("solidity", "solidity", "sol"),
        ("rust", "rust_anchor", "rs"),
    ):
        for invariant in INVARIANTS:
            slug = INVARIANTS[invariant]
            controls.append((language, f"{invariant}-vulnerable", root / directory / f"{slug}_vulnerable.{extension}", {invariant}))
            controls.append((language, f"{invariant}-fixed", root / directory / f"{slug}_fixed.{extension}", set()))
    return controls


def run_self_test(fixtures: Path) -> int:
    failures = 0
    total = 0
    for language, label, path, expected in fixture_expectations(fixtures):
        total += 1
        results, files_scanned = analyze([path], language)
        observed = set(results[0].missing) if len(results) == 1 else {"NO_SINGLE_CANDIDATE"}
        passed = files_scanned == 1 and observed == expected
        if not passed:
            failures += 1
        print(
            f"CONTROL {language} {label} expected={','.join(sorted(expected)) or 'none'} "
            f"observed={','.join(sorted(observed)) or 'none'} {'PASS' if passed else 'FAIL'}"
        )
    print(f"CONTROL_SUMMARY total={total} passed={total - failures} failed={failures}")
    return 0 if failures == 0 else 1


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="source file(s) or directory tree(s)")
    parser.add_argument("--language", choices=("auto", "solidity", "rust"), default="auto")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--json-out", type=Path, help="write the full JSON result in addition to stdout")
    parser.add_argument("--entrypoint", help="optional regular expression restricting candidate function names")
    parser.add_argument("--self-test", action="store_true", help="run all vulnerable/fixed fixture controls")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path(__file__).resolve().parent / "fixtures",
        help="fixture root for --self-test",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        return run_self_test(args.fixtures)
    if not args.paths:
        print("error: provide at least one source path or use --self-test", file=sys.stderr)
        return 2
    missing_inputs = [str(path) for path in args.paths if not path.exists()]
    if missing_inputs:
        print(f"error: missing input(s): {', '.join(missing_inputs)}", file=sys.stderr)
        return 2

    try:
        results, files_scanned = analyze(args.paths, args.language, args.entrypoint)
    except re.error as error:
        print(f"error: invalid --entrypoint regular expression: {error}", file=sys.stderr)
        return 2
    payload = serializable(results, files_scanned)
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(results, files_scanned)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if not results:
        return 3
    return 1 if any(result.missing for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
