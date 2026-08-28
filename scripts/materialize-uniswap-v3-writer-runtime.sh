#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
overlay_dir="$repo_dir/uniswap-v3/writer-runtime"
destination=${1:-}
python_bin=${PYTHON:-python3}

fail() {
    echo "Uniswap V3 writer-runtime materialization failed: $*" >&2
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

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-writer-runtime.py"
"$repo_dir/scripts/verify-uniswap-v3-import.sh"
"$repo_dir/scripts/materialize-uniswap-v3-chain-config.sh" "$destination"
resolved_after_chain_config=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "materialized destination failed the containment recheck"
[[ "$resolved_after_chain_config" == "$destination" ]] \
    || fail "materialized destination resolved to a different path"

patch --directory "$destination" --strip 1 --forward --batch \
    < "$overlay_dir/runtime.patch"
mkdir -p "$destination/configs" "$destination/fixtures"
for overlay_destination in "$destination/configs" "$destination/fixtures"; do
    [[ -d "$overlay_destination" && ! -L "$overlay_destination" ]] \
        || fail "overlay destination must be a real directory: $overlay_destination"
done
cp "$overlay_dir/configs/"*.json "$destination/configs/"
cp "$overlay_dir/segment-profiles-v1.json" \
    "$destination/configs/segment-profiles-v1.json"
cp "$overlay_dir/fixtures/events-v1.json" "$destination/fixtures/events-v1.json"
cp "$overlay_dir/manifests/"substreams.*.yaml "$destination/"

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-writer-runtime.py" \
    --runtime "$destination"
"$repo_dir/scripts/verify-uniswap-v3-import.sh"

echo "materialized diagnostic Uniswap V3 writer runtime at $destination"
