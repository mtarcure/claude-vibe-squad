#!/usr/bin/env python3
"""Forge-backed proxy/implementation storage-layout collision check."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Pair:
    deployment: str
    proxy: str
    implementation: str


@dataclass(frozen=True)
class Field:
    label: str
    slot: int
    offset: int
    size: int
    type_id: str

    @property
    def start(self) -> int:
        return self.slot * 32 + self.offset

    @property
    def end(self) -> int:
        return self.start + self.size


@dataclass(frozen=True)
class Row:
    deployment: str
    proxy: str
    implementation: str
    slot_offset: str
    proxy_field: str
    implementation_field: str
    init_sensitive: str
    status: str


def _parse_manifest(path: Path) -> list[Pair]:
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines or lines[0].split("\t") != ["deployment", "proxy", "implementation"]:
        raise ValueError("manifest header must be: deployment<TAB>proxy<TAB>implementation")
    pairs: list[Pair] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines[1:], 2):
        columns = line.split("\t")
        if len(columns) != 3 or not all(column.strip() for column in columns):
            raise ValueError(f"manifest line {line_number} must have three nonempty tab-separated fields")
        deployment, proxy, implementation = (column.strip() for column in columns)
        if deployment in seen:
            raise ValueError(f"duplicate deployment label: {deployment}")
        seen.add(deployment)
        pairs.append(Pair(deployment, proxy, implementation))
    if not pairs:
        raise ValueError("manifest has no deployment pairs")
    return pairs


def _next_run_dir(work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    for number in range(1, 10000):
        candidate = work_dir / f"run-{number:04d}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("work directory has no free run slot")


def _slug(contract: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", contract).strip("_") or "contract"


def _write_evidence(directory: Path, command: list[str], result: subprocess.CompletedProcess[str]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
    (directory / "stdout.json").write_text(result.stdout, encoding="utf-8")
    (directory / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    (directory / "exit-status.txt").write_text(f"{result.returncode}\n", encoding="utf-8")


def _json_object(stdout: str) -> dict[str, object]:
    stripped = stdout.strip()
    if not stripped:
        raise ValueError("forge inspect returned empty stdout")
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError("forge inspect stdout did not contain a JSON object") from None
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("forge inspect storage layout was not a JSON object")
    return value


def _number(value: object) -> int:
    text = str(value)
    return int(text, 16) if text.lower().startswith("0x") else int(text, 10)


def _fields(layout: dict[str, object]) -> list[Field]:
    raw_storage = layout.get("storage")
    raw_types = layout.get("types")
    if not isinstance(raw_storage, list) or not isinstance(raw_types, dict):
        raise ValueError("forge storage layout lacks storage/types")
    fields: list[Field] = []
    for item in raw_storage:
        if not isinstance(item, dict):
            raise ValueError("forge storage entry is not an object")
        type_id = str(item.get("type", ""))
        type_info = raw_types.get(type_id, {})
        if not isinstance(type_info, dict):
            type_info = {}
        size = _number(type_info.get("numberOfBytes", 32))
        fields.append(
            Field(
                label=str(item.get("label", "<unnamed>")),
                slot=_number(item.get("slot", 0)),
                offset=_number(item.get("offset", 0)),
                size=max(1, size),
                type_id=type_id,
            )
        )
    return fields


def _inspect(
    forge: str,
    project: Path,
    contract_spec: str,
    run_dir: Path,
) -> tuple[list[Field] | None, str | None]:
    if "::" in contract_spec:
        contracts_dir_text, contract = contract_spec.split("::", 1)
        contracts_dir = (project / contracts_dir_text).resolve()
        if not contracts_dir.is_dir():
            return None, f"contracts directory does not exist: {contracts_dir_text}"
    else:
        contract = contract_spec
        contracts_dir = None
    out_dir = run_dir / "out"
    cache_dir = run_dir / "cache"
    command = [
        forge,
        "inspect",
        contract,
        "storage-layout",
        "--json",
        "--root",
        str(project),
        "--out",
        str(out_dir),
        "--cache-path",
        str(cache_dir),
        "--offline",
        "--skip",
        "test",
        "script",
    ]
    if contracts_dir is not None:
        command.extend(["--contracts", str(contracts_dir)])
    result = subprocess.run(command, cwd=project, text=True, capture_output=True, check=False)
    evidence_dir = run_dir / "forge-evidence" / _slug(contract_spec)
    _write_evidence(evidence_dir, command, result)
    if result.returncode != 0:
        return None, f"forge exit {result.returncode}"
    try:
        return _fields(_json_object(result.stdout)), None
    except (ValueError, TypeError) as exc:
        return None, str(exc)


def _init_sensitive(proxy: Field, implementation: Field, overlap_start: int) -> bool:
    labels = f"{proxy.label} {implementation.label}".lower()
    overlap_slot = overlap_start // 32
    return overlap_slot in {0, 1} or bool(re.search(r"initializ|(?:^|_)init(?:_|$)|version", labels))


def _rows_for_pair(
    pair: Pair,
    proxy_fields: list[Field],
    implementation_fields: list[Field],
) -> list[Row]:
    rows: list[Row] = []
    for proxy in proxy_fields:
        for implementation in implementation_fields:
            overlap_start = max(proxy.start, implementation.start)
            overlap_end = min(proxy.end, implementation.end)
            if overlap_start >= overlap_end:
                continue
            start_slot, start_offset = divmod(overlap_start, 32)
            end_slot, end_offset = divmod(overlap_end - 1, 32)
            location = f"{start_slot}:{start_offset}"
            if (start_slot, start_offset) != (end_slot, end_offset):
                location += f"-{end_slot}:{end_offset}"
            sensitive = _init_sensitive(proxy, implementation, overlap_start)
            rows.append(
                Row(
                    deployment=pair.deployment,
                    proxy=pair.proxy,
                    implementation=pair.implementation,
                    slot_offset=location,
                    proxy_field=f"{proxy.label} ({proxy.type_id}, {proxy.size}B)",
                    implementation_field=(
                        f"{implementation.label} ({implementation.type_id}, {implementation.size}B)"
                    ),
                    init_sensitive="YES" if sensitive else "NO",
                    status="OVERLAP-SLOT0/1-OR-INIT" if sensitive else "OVERLAP",
                )
            )
    if not rows:
        rows.append(
            Row(
                deployment=pair.deployment,
                proxy=pair.proxy,
                implementation=pair.implementation,
                slot_offset="—",
                proxy_field="—",
                implementation_field="—",
                init_sensitive="NO",
                status="CLEAN",
            )
        )
    return rows


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _print_table(rows: list[Row], verdict: str) -> None:
    headers = [
        "Deployment",
        "Proxy",
        "Implementation",
        "Overlap slot:byte",
        "Proxy field",
        "Implementation field",
        "Init/slot0-1 sensitive",
        "Status",
    ]
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        print(
            "| "
            + " | ".join(
                _escape(value)
                for value in (
                    row.deployment,
                    row.proxy,
                    row.implementation,
                    row.slot_offset,
                    row.proxy_field,
                    row.implementation_field,
                    row.init_sensitive,
                    row.status,
                )
            )
            + " |"
        )
    print(f"VERDICT: {verdict}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diff Forge storage layouts for declared proxy/implementation deployment pairs."
    )
    parser.add_argument("project", type=Path, help="Foundry project root")
    parser.add_argument("--manifest", type=Path, required=True, help="tab-separated deployment pairs")
    parser.add_argument(
        "--work-dir",
        type=Path,
        required=True,
        help="write-only location for isolated Forge output and literal evidence",
    )
    parser.add_argument("--forge", default="forge")
    args = parser.parse_args()

    project = args.project.resolve()
    manifest = args.manifest.resolve()
    work_dir = args.work_dir.resolve()
    if not project.is_dir():
        parser.error(f"project is not a directory: {project}")
    if not manifest.is_file():
        parser.error(f"manifest is not a file: {manifest}")

    try:
        pairs = _parse_manifest(manifest)
        run_dir = _next_run_dir(work_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        print("| Engine | Error |")
        print("| --- | --- |")
        print(f"| forge-storage-layout-diff | {_escape(str(exc))} |")
        print("VERDICT: ERROR")
        return 2

    layouts: dict[str, list[Field] | None] = {}
    errors: dict[str, str] = {}
    for contract in dict.fromkeys(
        contract for pair in pairs for contract in (pair.proxy, pair.implementation)
    ):
        try:
            layout, error = _inspect(args.forge, project, contract, run_dir)
        except OSError as exc:
            layout, error = None, str(exc)
        layouts[contract] = layout
        if error is not None:
            errors[contract] = error

    rows: list[Row] = []
    for pair in pairs:
        pair_errors = [
            f"{contract}: {errors[contract]}"
            for contract in (pair.proxy, pair.implementation)
            if contract in errors
        ]
        if pair_errors:
            rows.append(
                Row(
                    deployment=pair.deployment,
                    proxy=pair.proxy,
                    implementation=pair.implementation,
                    slot_offset="—",
                    proxy_field="; ".join(pair_errors),
                    implementation_field="—",
                    init_sensitive="UNKNOWN",
                    status="ERROR",
                )
            )
            continue
        rows.extend(
            _rows_for_pair(
                pair,
                layouts[pair.proxy] or [],
                layouts[pair.implementation] or [],
            )
        )

    if any(row.status == "ERROR" for row in rows):
        verdict, exit_code = "ERROR", 2
    elif any(row.status.startswith("OVERLAP") for row in rows):
        verdict, exit_code = "FAIL", 1
    else:
        verdict, exit_code = "PASS", 0
    _print_table(rows, verdict)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
