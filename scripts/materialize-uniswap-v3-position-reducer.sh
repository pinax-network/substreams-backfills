#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
overlay_dir="$repo_dir/uniswap-v3/position-reducer"
destination=${1:-}
python_bin=${PYTHON:-python3}

fail() {
    echo "Uniswap V3 position-reducer materialization failed: $*" >&2
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

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-position-reducer.py"
"$repo_dir/scripts/materialize-uniswap-v3-writer-runtime.sh" "$destination"
resolved_after_writer=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "materialized destination failed the containment recheck"
[[ "$resolved_after_writer" == "$destination" ]] \
    || fail "materialized destination resolved to a different path"

patch --directory "$destination" --strip 1 --forward --batch -F 0 \
    < "$overlay_dir/runtime.patch"
for overlay_destination in "$destination/src" "$destination/configs"; do
    [[ -d "$overlay_destination" && ! -L "$overlay_destination" ]] \
        || fail "overlay destination must be a real directory: $overlay_destination"
done
[[ ! -e "$destination/src/position_reducer.rs" ]] \
    || fail "position reducer source target already exists"
[[ ! -e "$destination/configs/position-reducer-v1.json" ]] \
    || fail "position reducer config target already exists"
cp "$overlay_dir/src/position_reducer.rs" "$destination/src/position_reducer.rs"
cp "$overlay_dir/position-reducer-v1.json" \
    "$destination/configs/position-reducer-v1.json"

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-position-reducer.py" \
    --runtime "$destination"
"$repo_dir/scripts/verify-uniswap-v3-import.sh"

echo "materialized host-only Uniswap V3 position reducer at $destination"
