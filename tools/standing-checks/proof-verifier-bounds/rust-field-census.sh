#!/usr/bin/env bash
set -u

if [[ $# -ne 1 ]]; then
  echo "usage: bash rust-field-census.sh <rust-source-root>" >&2
  exit 2
fi

scan_root=$1
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
positive_control="$script_dir/fixtures/rust_anchor/strict_index_bounds_fixed.rs"
pattern='\b(proofs?|leaves?|merkle|mmr|multiproof|witness|siblings?)\b|\.(index|position)\b|\b(proof|leaf)_(pos|index|cursor|offset)\b'

if [[ ! -d "$scan_root" ]]; then
  echo "error: Rust source root does not exist: $scan_root" >&2
  exit 2
fi

echo "FALLBACK rust-positive-control"
echo "COMMAND rg -n -i --glob '*.rs' --glob '!target/**' -e '$pattern' $positive_control"
set +e
control_output=$(rg -n -i --glob '*.rs' --glob '!target/**' -e "$pattern" "$positive_control" 2>&1)
control_status=$?
set -e
printf '%s\n' "$control_output"
echo "EXIT $control_status"
if [[ $control_status -ne 0 ]]; then
  echo "CONTROL_FAIL ripgrep did not detect known Rust field/proof surface" >&2
  exit 1
fi
echo "CONTROL_PASS ripgrep detected known Rust field/proof surface"

echo "FALLBACK rust-corpus-census"
echo "COMMAND rg -n -i --glob '*.rs' --glob '!target/**' -e '$pattern' $scan_root"
set +e
scan_output=$(rg -n -i --glob '*.rs' --glob '!target/**' -e "$pattern" "$scan_root" 2>&1)
scan_status=$?
set -e
printf '%s\n' "$scan_output"
echo "EXIT $scan_status"

if [[ $scan_status -eq 0 ]]; then
  echo "CENSUS_RESULT matches_require_manual_classification"
  exit 0
fi
if [[ $scan_status -eq 1 ]]; then
  echo "CENSUS_RESULT bounded_empty_not_clean"
  exit 0
fi
echo "CENSUS_ERROR ripgrep failed" >&2
exit "$scan_status"
