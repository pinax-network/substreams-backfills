#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
overlay_dir="$repo_dir/uniswap-v3/npm-resolved-inputs"
source_overlay="$repo_dir/uniswap-v3/npm-source-block"
destination=${1:-}
python_bin=${PYTHON:-python3}

fail() {
    echo "Uniswap V3 resolved NPM input materialization failed: $*" >&2
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

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-npm-resolved-inputs.py"
"$repo_dir/scripts/materialize-uniswap-v3-npm-handler-reducer.sh" "$destination"
resolved_after_joint=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "materialized destination failed the containment recheck"
[[ "$resolved_after_joint" == "$destination" ]] \
    || fail "materialized destination resolved to a different path"

for overlay_destination in "$destination/src" "$destination/configs" "$destination/tests"; do
    [[ -d "$overlay_destination" && ! -L "$overlay_destination" ]] \
        || fail "overlay destination must be a real directory: $overlay_destination"
done

[[ -f "$destination/tests/npm_handler_reducer.rs" && ! -L "$destination/tests/npm_handler_reducer.rs" ]] \
    || fail "inherited joint reducer harness is missing or unsafe"
rm "$destination/tests/npm_handler_reducer.rs"

for target in \
    "$destination/src/npm_source_block.rs" \
    "$destination/src/uniswap.npm.source.v1.rs" \
    "$destination/configs/npm-source-block-v1.json" \
    "$destination/src/npm_resolved_inputs.rs" \
    "$destination/src/uniswap.npm.inputs.v1.rs" \
    "$destination/configs/npm-resolved-inputs-v1.json" \
    "$destination/tests/npm_resolved_inputs.rs"; do
    [[ ! -e "$target" ]] || fail "resolved-input target already exists: $target"
done

cp "$source_overlay/runtime/src/npm_source_block.rs" "$destination/src/npm_source_block.rs"
cp "$source_overlay/runtime/src/pb/uniswap.npm.source.v1.rs" \
    "$destination/src/uniswap.npm.source.v1.rs"
cp "$source_overlay/npm-source-block-v1.json" "$destination/configs/npm-source-block-v1.json"
cp "$overlay_dir/src/npm_resolved_inputs.rs" "$destination/src/npm_resolved_inputs.rs"
cp "$overlay_dir/src/uniswap.npm.inputs.v1.rs" "$destination/src/uniswap.npm.inputs.v1.rs"
cp "$overlay_dir/npm-resolved-inputs-v1.json" "$destination/configs/npm-resolved-inputs-v1.json"
cp "$overlay_dir/tests/npm_resolved_inputs.rs" "$destination/tests/npm_resolved_inputs.rs"

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-npm-resolved-inputs.py" \
    --runtime "$destination"
"$repo_dir/scripts/verify-uniswap-v3-import.sh"

echo "materialized host-only Uniswap V3 resolved NPM input adapter at $destination"
