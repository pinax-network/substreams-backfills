#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
overlay_dir="$repo_dir/uniswap-v3/npm-source-block"
destination=${1:-}
python_bin=${PYTHON:-python3}

fail() {
    echo "Uniswap V3 NPM source-block materialization failed: $*" >&2
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

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-npm-source-block.py"
"$repo_dir/scripts/materialize-uniswap-v3-writer-runtime.sh" "$destination"
resolved_after_writer=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "materialized destination failed the containment recheck"
[[ "$resolved_after_writer" == "$destination" ]] \
    || fail "materialized destination resolved to a different path"

runtime="$destination/npm-source-block-runtime"
[[ ! -e "$runtime" ]] || fail "NPM source runtime target already exists"
mkdir -p "$runtime/src/pb" "$runtime/configs"
for target in "$runtime" "$runtime/src" "$runtime/src/pb" "$runtime/configs" "$destination/proto"; do
    [[ -d "$target" && ! -L "$target" ]] || fail "materialization target must be a real directory: $target"
done

cp "$overlay_dir/runtime/Cargo.toml" "$runtime/Cargo.toml"
cp "$overlay_dir/runtime/Cargo.lock" "$runtime/Cargo.lock"
cp "$destination/rust-toolchain.toml" "$runtime/rust-toolchain.toml"
cp "$destination/rustfmt.toml" "$runtime/rustfmt.toml"
cp "$overlay_dir/runtime/src/lib.rs" "$runtime/src/lib.rs"
cp "$overlay_dir/runtime/src/npm_source_block.rs" "$runtime/src/npm_source_block.rs"
cp "$overlay_dir/runtime/src/pb/mod.rs" "$runtime/src/pb/mod.rs"
cp "$overlay_dir/runtime/src/pb/uniswap.npm.source.v1.rs" "$runtime/src/pb/uniswap.npm.source.v1.rs"
cp "$destination/src/pb/uniswap.writer.v1.rs" "$runtime/src/pb/uniswap.writer.v1.rs"
cp "$overlay_dir/npm-source-block-v1.json" "$runtime/configs/npm-source-block-v1.json"
cp "$repo_dir/uniswap-v3/writer-runtime/segment-profiles-v1.json" "$runtime/configs/segment-profiles-v1.json"

proto_target="$destination/proto/uniswap/npm/source/v1"
[[ ! -e "$proto_target" ]] || fail "NPM source protobuf target already exists"
mkdir -p "$proto_target"
cp "$overlay_dir/proto/uniswap/npm/source/v1/npm_source_block.proto" "$proto_target/npm_source_block.proto"

package_dir="$destination/npm-source-package"
[[ ! -e "$package_dir" ]] || fail "NPM source package target already exists"
mkdir "$package_dir"
[[ -d "$package_dir" && ! -L "$package_dir" ]] \
    || fail "NPM source package target must be a real directory"
cp "$overlay_dir/README.md" "$package_dir/README.md"
for manifest in substreams.npm-source.mainnet.yaml substreams.npm-source.base.yaml; do
    cp "$overlay_dir/manifests/$manifest" "$package_dir/$manifest"
done

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-npm-source-block.py" \
    --runtime "$destination"
"$repo_dir/scripts/verify-uniswap-v3-import.sh"

echo "materialized provider-free Uniswap V3 NPM source-block package at $destination"
