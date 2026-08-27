#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_dir="$repo_dir/uniswap-v3/source"
overlay_dir="$repo_dir/uniswap-v3/chain-config"
destination=${1:-}

fail() {
    echo "Uniswap V3 ChainConfig materialization failed: $*" >&2
    exit 1
}

[[ -n "$destination" ]] || fail "pass an explicit destination directory"
[[ "$destination" != "$repo_dir" ]] || fail "destination cannot be the repository root"
[[ "$destination" != "$source_dir" ]] || fail "destination cannot be the frozen source"

if [[ -e "$destination" ]]; then
    [[ -d "$destination" ]] || fail "destination exists and is not a directory"
    [[ -z "$(find "$destination" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
        || fail "destination must be empty"
else
    mkdir -p "$destination"
fi

"$repo_dir/scripts/verify-uniswap-v3-import.sh"
cp -a "$source_dir/." "$destination/"
patch --directory "$destination" --strip 1 --forward --batch < "$overlay_dir/runtime.patch"
mkdir -p "$destination/configs"
cp "$overlay_dir/configs/"*.json "$destination/configs/"
cp "$overlay_dir/manifests/"substreams.*.yaml "$destination/"

echo "materialized configured Uniswap V3 runtime at $destination"
