#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
overlay_dir="$repo_dir/uniswap-v3/chain-config"
destination=${1:-}
python_bin=${PYTHON:-python3}

fail() {
    echo "Uniswap V3 ChainConfig materialization failed: $*" >&2
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

"$repo_dir/scripts/verify-uniswap-v3-import.sh"
mkdir -p "$destination"
resolved_after_create=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "created destination failed the containment recheck"
[[ "$resolved_after_create" == "$destination" ]] \
    || fail "created destination resolved to a different path"
git -C "$repo_dir" archive --format=tar "HEAD:uniswap-v3/source" \
    | tar -C "$destination" -xf -
patch --directory "$destination" --strip 1 --forward --batch < "$overlay_dir/runtime.patch"
mkdir -p "$destination/configs"
[[ -d "$destination/configs" && ! -L "$destination/configs" ]] \
    || fail "materialized configs path must be a real directory"
cp "$overlay_dir/configs/"*.json "$destination/configs/"
cp "$overlay_dir/manifests/"substreams.*.yaml "$destination/"

echo "materialized configured Uniswap V3 runtime at $destination"
