#!/usr/bin/env python3
"""Validate banked-primitive ledgers: witness provenance and closed predicate vocabulary.

Two campaigns recorded a bound on a HARNESS as if it were a bound on the TARGET. Both times the
bound was already wrong when it was banked and composition was merely its first consumer, so the
fix belongs at bank time, in the schema — not in a better composition algorithm.

The load-bearing check is `production-guard-cites-harness-path`. A lane that measured its own
fixture can only cite a `test/`, `mock/`, or `harness/` path, and no wording moves that path into
`src/`. The failure stops being discouraged and starts being structurally unable to hide.

Style follows scripts/python/validate_specialists.py: stdlib only, regex parsing, one Finding per
subject, JSON lines on stdout, summary on stderr, nonzero exit when anything failed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

WITNESS_KINDS = {"PRODUCTION_GUARD", "HARNESS_ARTIFACT", "ASSUMED", "EMPIRICAL"}

# Path segments and filename shapes that are, by construction, not production code. A bound whose
# only witness lives here is a bound on our own instrumentation.
HARNESS_SEGMENTS = {
    "test", "tests", "__tests__", "mock", "mocks", "fixture", "fixtures",
    "harness", "spec", "specs", "testdata", "e2e",
}
HARNESS_FILENAME_RE = re.compile(
    r"(\.t\.sol|\.test\.[jt]sx?|\.spec\.[jt]sx?|_test\.(go|rs|py|c|cc|cpp)|^test_.*\.py$|^Mock[A-Z])"
)

# A postcondition is a capability the attacker gains, not a label for how bad it is. Severities die
# with the campaign that assigned them; capabilities port to every future target.
SEVERITY_RE = re.compile(
    r"\b(critical|high|medium|low|informational|severity|cvss|sev[-_ ]?\d)\b", re.I
)

PREDICATE_RE = re.compile(r"\b((?:auth|state|capital|timing|cap)\.[a-z_]+)\b")
BLOCK_RE = re.compile(r"^```(primitive|bound)[ \t]*$(.*?)^```[ \t]*$", re.M | re.S)
WITNESS_RE = re.compile(r"^(?P<path>[^\s:]+):(?P<start>\d+)(?:-(?P<end>\d+))?$")

FAMILY_FIELD = {
    "pre.authority": "auth",
    "pre.state": "state",
    "pre.capital": "capital",
    "pre.timing": "timing",
    "post.capability": "cap",
}

REQUIRED_PRIMITIVE_FIELDS = ("id", "pin", "action.command", "post.capability")
REQUIRED_BOUND_FIELDS = ("of", "claim", "witness_kind")


@dataclass
class Finding:
    path: str
    status: str
    issues: list[str]


def json_line(finding: Finding) -> str:
    return json.dumps(
        {"subject": finding.path, "status": finding.status, "issues": finding.issues},
        sort_keys=True,
    )


def load_predicates(path: Path) -> dict[str, str]:
    """Return {predicate: family} from the reviewed TSV. The vocabulary is data, not code, so
    extending it is a reviewable diff rather than a validator change."""
    predicates: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("predicate"):
                predicates[row["predicate"].strip()] = row["family"].strip()
    return predicates


def parse_blocks(text: str) -> list[tuple[str, dict[str, str], int]]:
    """Fenced ```primitive / ```bound blocks of flat `key: value` lines.

    Flat and regex-parseable on purpose: PyYAML is not installed on the lanes that must run this,
    and a ledger a lane cannot parse is a ledger a lane will not write.
    """
    blocks: list[tuple[str, dict[str, str], int]] = []
    for match in BLOCK_RE.finditer(text):
        fields: dict[str, str] = {}
        for raw in match.group(2).splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
        line_no = text.count("\n", 0, match.start()) + 1
        blocks.append((match.group(1), fields, line_no))
    return blocks


class LedgerValidator:
    def __init__(self, predicates: dict[str, str], target: Path | None = None) -> None:
        self.predicates = predicates
        self.target = target
        self.findings: list[Finding] = []
        self.total = 0
        self.passed = 0

    def add(self, subject: str, status: str, *issues: str) -> None:
        self.findings.append(Finding(str(subject), status, list(issues)))

    def check(self, subject: str, issues: list[str]) -> None:
        self.total += 1
        if issues:
            self.add(subject, "fail", *issues)
        else:
            self.passed += 1
            self.add(subject, "pass")

    def is_harness_path(self, raw_path: str) -> bool:
        parts = [p.lower() for p in Path(raw_path).parts]
        if any(part in HARNESS_SEGMENTS for part in parts):
            return True
        return bool(HARNESS_FILENAME_RE.search(Path(raw_path).name))

    def quote_matches(self, witness: str, quote: str) -> bool | None:
        """True/False when the witness resolves under --target, None when it cannot be checked."""
        if self.target is None:
            return None
        parsed = WITNESS_RE.match(witness)
        if not parsed:
            return None
        source = self.target / parsed.group("path")
        if not source.is_file():
            return None
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        start = int(parsed.group("start"))
        end = int(parsed.group("end") or start)
        window = " ".join(lines[max(0, start - 1):end])
        normalize = lambda s: re.sub(r"\s+", " ", s).strip().strip('"').strip("'")
        return normalize(quote) in normalize(window)

    def validate_predicates(self, subject: str, fields: dict[str, str], issues: list[str]) -> None:
        for field, family in FAMILY_FIELD.items():
            value = fields.get(field, "")
            if not value:
                continue
            for token in PREDICATE_RE.findall(value):
                if token not in self.predicates:
                    issues.append(f"unknown-predicate:{field}:{token}")
                elif not token.startswith(family + "."):
                    issues.append(f"predicate-family-mismatch:{field}:{token}")
            if not PREDICATE_RE.search(value) and value.lower() not in {"none", "n/a"}:
                issues.append(f"prose-instead-of-predicate:{field}")

    def validate_primitive(self, subject: str, fields: dict[str, str]) -> None:
        issues: list[str] = []
        for field in REQUIRED_PRIMITIVE_FIELDS:
            if not fields.get(field):
                issues.append(f"primitive-missing-field:{field}")
        postcondition = fields.get("post.capability", "")
        if postcondition and SEVERITY_RE.search(postcondition):
            issues.append(f"postcondition-is-severity:{SEVERITY_RE.search(postcondition).group(0)}")
        self.validate_predicates(subject, fields, issues)
        self.check(subject, issues)

    def validate_bound(self, subject: str, fields: dict[str, str], known_ids: set[str]) -> None:
        issues: list[str] = []
        for field in REQUIRED_BOUND_FIELDS:
            if not fields.get(field):
                issues.append(f"bound-missing-field:{field}")
        owner = fields.get("of", "")
        if owner and owner not in known_ids:
            issues.append(f"bound-orphan:{owner}")

        kind = fields.get("witness_kind", "")
        witness = fields.get("witness", "")
        quote = fields.get("quote", "")
        if kind and kind not in WITNESS_KINDS:
            issues.append(f"unknown-witness-kind:{kind}")

        if kind == "PRODUCTION_GUARD":
            if not witness:
                issues.append("production-guard-missing-witness")
            elif not WITNESS_RE.match(witness):
                issues.append(f"production-guard-malformed-witness:{witness}")
            elif self.is_harness_path(witness.split(":")[0]):
                # The check the whole schema exists for.
                issues.append(f"production-guard-cites-harness-path:{witness.split(':')[0]}")
            if not quote:
                issues.append("production-guard-missing-quote")
            elif witness and self.quote_matches(witness, quote) is False:
                issues.append(f"production-guard-quote-mismatch:{witness}")
        elif kind == "HARNESS_ARTIFACT":
            if not witness:
                issues.append("harness-artifact-missing-witness")
            elif not self.is_harness_path(witness.split(":")[0]):
                issues.append(f"harness-artifact-cites-production-path:{witness.split(':')[0]}")
        elif kind == "ASSUMED":
            if not fields.get("assumption"):
                issues.append("assumed-missing-assumption")
        elif kind == "EMPIRICAL":
            if not fields.get("command"):
                issues.append("empirical-missing-command")
            # A tool that silently failed to run and a tool that found nothing print the same
            # empty output, so a null EMPIRICAL claim owes a reachable-set denominator.
            if not fields.get("covered"):
                issues.append("empirical-missing-covered")
        self.check(subject, issues)

    def validate_ledger(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        blocks = parse_blocks(text)
        if not blocks:
            self.check(str(path), ["ledger-has-no-primitive-blocks"])
            return
        known_ids = {
            f.get("id", "") for kind, f, _ in blocks if kind == "primitive" and f.get("id")
        }
        seen: set[str] = set()
        for kind, fields, line_no in blocks:
            if kind == "primitive":
                ident = fields.get("id") or f"line{line_no}"
                subject = f"{path}:{line_no}:{ident}"
                if ident in seen:
                    self.add(subject, "fail", f"duplicate-primitive-id:{ident}")
                    self.total += 1
                    continue
                seen.add(ident)
                self.validate_primitive(subject, fields)
            else:
                subject = f"{path}:{line_no}:bound-of-{fields.get('of', '?')}"
                self.validate_bound(subject, fields, known_ids)

    def run(self, ledgers: Iterable[Path]) -> tuple[list[Finding], str, int]:
        for path in sorted(set(ledgers), key=str):
            if path.is_file():
                self.validate_ledger(path)
            else:
                self.check(str(path), ["ledger-not-found"])
        failed = sum(item.status == "fail" for item in self.findings)
        summary = f"Total: {self.total}  Passed: {self.passed}  Failed: {failed}"
        return self.findings, summary, int(failed > 0)


def main(argv: Iterable[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledgers", nargs="+", type=Path, help="primitive ledger markdown files")
    parser.add_argument("--predicates", type=Path, default=here / "predicates.tsv")
    parser.add_argument("--target", type=Path, default=None,
                        help="target repo root; enables quote verification against real source")
    parser.add_argument("--quiet", action="store_true", help="accepted for shell compatibility")
    args = parser.parse_args(list(argv) if argv is not None else None)

    validator = LedgerValidator(load_predicates(args.predicates), args.target)
    findings, summary, code = validator.run(args.ledgers)
    for finding in findings:
        print(json_line(finding))
    print(file=sys.stderr)
    print(summary, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
