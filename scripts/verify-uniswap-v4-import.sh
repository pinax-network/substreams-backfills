#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_dir"

source_commit=6812a4deaa5a520020e8d727e17f6d0b7113d0a9
source_tree=2d60d30242443adc2c021a5b609c27edcb75128a
import_path=uniswap-v4

fail() {
    echo "Uniswap V4 import verification failed: $*" >&2
    exit 1
}

actual_source_tree=$(git rev-parse "${source_commit}^{tree}")
[[ "$actual_source_tree" == "$source_tree" ]] || fail "source tree is $actual_source_tree"

git merge-base --is-ancestor "$source_commit" HEAD \
    || fail "source commit is not retained in destination history"

import_tree=$(git rev-parse "HEAD:${import_path}")
[[ "$import_tree" == "$source_tree" ]] || fail "import tree is $import_tree"

source_files=$(git ls-tree -r --name-only "$source_commit" | wc -l | tr -d ' ')
import_files=$(git ls-tree -r --name-only "HEAD:${import_path}" | wc -l | tr -d ' ')
[[ "$source_files" == 98 ]] || fail "source contains $source_files tracked files"
[[ "$import_files" == 98 ]] || fail "import contains $import_files tracked files"

source_executables=$(git ls-tree -r "$source_commit" | awk '$1 == "100755" { count++ } END { print count+0 }')
import_executables=$(git ls-tree -r "HEAD:${import_path}" | awk '$1 == "100755" { count++ } END { print count+0 }')
[[ "$source_executables" == 13 ]] || fail "source contains $source_executables executable files"
[[ "$import_executables" == 13 ]] || fail "import contains $import_executables executable files"

git diff --quiet -- "$import_path" || fail "working tree modifies the imported source"
git diff --cached --quiet -- "$import_path" || fail "index modifies the imported source"

python3 scripts/build-uniswap-v4-import-inventory.py \
    --check provenance/uniswap-v4-v0.4.1-files.json

verify_sha256() {
    expected=$1
    path=$2
    actual=$(sha256sum "$path" | awk '{ print $1 }')
    [[ "$actual" == "$expected" ]] || fail "$path has SHA-256 $actual"
}

verify_sha256 \
    ac3b295591e68949881509379aa99d8460134873f895187746a35ece003fa440 \
    "$import_path/release/v0.4.0/uniswap-v4-base-state-stores-v0.1.0.spkg"
verify_sha256 \
    7cf06bb4b73c1409c581a7f878fb832c3e15c1d82193103d8bc7609dce8b58f3 \
    "$import_path/release/v0.4.0/uniswap-v4-base-store-fed-reducer-v0.1.0.spkg"
verify_sha256 \
    bc8a841dbb74f9bbc7d90826251ab766ad350170a4832fc3e9b084664d22254a \
    "$import_path/release/v0.4.0/uniswap-v4-base-store-state-reducer-v0.4.0.spkg"

echo "verified Uniswap V4 source commit, tree, 98 files, 13 executable modes, and frozen v0.4.0 packages"
