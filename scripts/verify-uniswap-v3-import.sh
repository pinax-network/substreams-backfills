#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_dir"

source_commit=42c7b15345e6df80561b694e52a0eb622b374b96
source_tree=a00e882e92d07b46550b74dea279c114d57631ac
source_ref=refs/remotes/origin/upstream/uniswap-v3-qma8a81t-parity
import_path=uniswap-v3/source

fail() {
    echo "Uniswap V3 import verification failed: $*" >&2
    exit 1
}

actual_source_commit=$(git rev-parse --verify "${source_ref}^{commit}")
[[ "$actual_source_commit" == "$source_commit" ]] \
    || fail "$source_ref points to $actual_source_commit"

actual_source_tree=$(git rev-parse "${source_ref}^{tree}")
[[ "$actual_source_tree" == "$source_tree" ]] || fail "source tree is $actual_source_tree"

if git merge-base --is-ancestor "$source_commit" HEAD; then
    fail "upstream history entered the default-branch lineage instead of its isolated mirror"
fi

import_tree=$(git rev-parse "HEAD:${import_path}")
[[ "$import_tree" == "$source_tree" ]] || fail "import tree is $import_tree"

source_files=$(git ls-tree -r --name-only "$source_ref" | wc -l | tr -d ' ')
import_files=$(git ls-tree -r --name-only "HEAD:${import_path}" | wc -l | tr -d ' ')
[[ "$source_files" == 75 ]] || fail "source contains $source_files tracked files"
[[ "$import_files" == 75 ]] || fail "import contains $import_files tracked files"

source_executables=$(git ls-tree -r "$source_ref" | awk '$1 == "100755" { count++ } END { print count+0 }')
import_executables=$(git ls-tree -r "HEAD:${import_path}" | awk '$1 == "100755" { count++ } END { print count+0 }')
[[ "$source_executables" == 1 ]] || fail "source contains $source_executables executable files"
[[ "$import_executables" == 1 ]] || fail "import contains $import_executables executable files"

git diff --quiet -- "$import_path" || fail "working tree modifies the imported source"
git diff --cached --quiet -- "$import_path" || fail "index modifies the imported source"

python3 scripts/verify-uniswap-v3-logical-contract.py

echo "verified mirrored Uniswap V3 history, exact imported tree, 75 files, one executable mode, and the 20-entity logical contract"
