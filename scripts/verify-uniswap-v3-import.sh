#!/usr/bin/env bash
# Transitional wrapper: the materialize-uniswap-v3-*.sh scripts (#111) and the
# mainnet parity runner still call this path. The verification itself is
# `cargo xtask verify-import uniswap-v3` (xtask/src/import_verify.rs, #110).
# `+stable` is required because the callers run with the pinned Rust 1.79
# toolchain selected as default, and xtask needs a current stable compiler.
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
exec cargo +stable run --quiet --manifest-path "$repo_dir/Cargo.toml" --package xtask -- \
    verify-import uniswap-v3 --root "$repo_dir"
