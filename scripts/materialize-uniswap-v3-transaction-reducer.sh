#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
overlay_dir="$repo_dir/uniswap-v3/transaction-reducer"
destination=${1:-}
python_bin=${PYTHON:-python3}

fail() {
    echo "Uniswap V3 transaction-reducer materialization failed: $*" >&2
    exit 1
}

[[ -n "$destination" ]] || fail "pass an explicit destination directory"
destination=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "destination cannot be resolved safely"

if [[ -e "$destination" ]]; then
    [[ -d "$destination" ]] || fail "destination exists and is not a directory"
    [[ -z "$(find "$destination" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
        || fail "destination must be empty"
fi

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-transaction-reducer.py"
"$repo_dir/scripts/materialize-uniswap-v3-writer-runtime.sh" "$destination"
resolved_after_writer=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "materialized destination failed the containment recheck"
[[ "$resolved_after_writer" == "$destination" ]] \
    || fail "materialized destination resolved to a different path"

for overlay_destination in "$destination/src" "$destination/configs"; do
    [[ -d "$overlay_destination" && ! -L "$overlay_destination" ]] \
        || fail "overlay destination must be a real directory: $overlay_destination"
done
[[ ! -e "$destination/tests" ]] \
    || fail "transaction reducer test destination already exists"
mkdir "$destination/tests"
[[ -d "$destination/tests" && ! -L "$destination/tests" ]] \
    || fail "transaction reducer test destination must be a real directory"
[[ ! -e "$destination/src/transaction_reducer.rs" ]] \
    || fail "transaction reducer source target already exists"
[[ ! -e "$destination/configs/transaction-reducer-v1.json" ]] \
    || fail "transaction reducer config target already exists"
[[ ! -e "$destination/tests/transaction_reducer.rs" ]] \
    || fail "transaction reducer harness target already exists"
cp "$overlay_dir/src/transaction_reducer.rs" "$destination/src/transaction_reducer.rs"
cp "$overlay_dir/transaction-reducer-v1.json" \
    "$destination/configs/transaction-reducer-v1.json"
cp "$overlay_dir/tests/transaction_reducer.rs" \
    "$destination/tests/transaction_reducer.rs"

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-transaction-reducer.py" \
    --runtime "$destination"
"$repo_dir/scripts/verify-uniswap-v3-import.sh"

echo "materialized host-only Uniswap V3 NPM Transaction reducer at $destination"
