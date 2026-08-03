#!/usr/bin/env bash
set -u

check_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
check_py="$check_root/check.py"
solc_bin=$(command -v solc)
control_tmp=$(mktemp -d -t proof-verifier-bounds-controls)

echo "COMMAND python3 $check_py --self-test"
python3 "$check_py" --self-test
self_test_status=$?
echo "EXIT $self_test_status"
if [[ $self_test_status -ne 0 ]]; then
  exit "$self_test_status"
fi

echo "COMMAND python3 $check_root/semgrep-controls.py"
python3 "$check_root/semgrep-controls.py"
semgrep_status=$?
echo "EXIT $semgrep_status"
if [[ $semgrep_status -ne 0 ]]; then
  exit "$semgrep_status"
fi

solidity_count=0
for fixture in "$check_root"/fixtures/solidity/*.sol; do
  echo "COMMAND $solc_bin --bin $fixture"
  "$solc_bin" --bin "$fixture" >/dev/null
  compile_status=$?
  echo "EXIT $compile_status"
  if [[ $compile_status -ne 0 ]]; then
    exit "$compile_status"
  fi
  solidity_count=$((solidity_count + 1))
done
echo "SOLIDITY_COMPILE_SUMMARY compiled=$solidity_count failed=0"

rust_count=0
for fixture in "$check_root"/fixtures/rust_anchor/*.rs; do
  metadata_name=$(basename "$fixture" .rs)
  echo "COMMAND rustc --edition 2021 --crate-type lib --emit metadata -o $control_tmp/$metadata_name.rmeta $fixture"
  rustc --edition 2021 --crate-type lib --emit metadata -o "$control_tmp/$metadata_name.rmeta" "$fixture"
  compile_status=$?
  echo "EXIT $compile_status"
  if [[ $compile_status -ne 0 ]]; then
    exit "$compile_status"
  fi
  rust_count=$((rust_count + 1))
done
echo "RUST_COMPILE_SUMMARY compiled=$rust_count failed=0"

echo "COMMAND FOUNDRY_CACHE_PATH=$control_tmp/cache FOUNDRY_OUT=$control_tmp/out forge test --offline --use $solc_bin --root $check_root --match-contract CalculateRootRegressionTest -vv"
FOUNDRY_CACHE_PATH="$control_tmp/cache" FOUNDRY_OUT="$control_tmp/out" \
  forge test --offline --use "$solc_bin" --root "$check_root" --match-contract CalculateRootRegressionTest -vv
forge_status=$?
echo "EXIT $forge_status"
if [[ $forge_status -ne 0 ]]; then
  exit "$forge_status"
fi

echo "CONTROL_ARTIFACTS $control_tmp"
echo "ALL_CONTROLS_PASS"
