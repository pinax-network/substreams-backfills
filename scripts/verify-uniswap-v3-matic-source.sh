#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_url="https://github.com/Uniswap/v3-subgraph.git"
source_commit="d07374a05719e68a10a339f79cdfbc048807cfdc"
source_tree="8f5cefd138068952bee909522a0f1d88fdc87b42"
python_executable="${MATIC_SOURCE_PYTHON:-python3}"

temporary_root=$(mktemp -d)
cleanup() {
  rm -rf "${temporary_root:?}"
}
trap cleanup EXIT

if [[ $# -gt 1 ]]; then
  echo "usage: $0 [source-repository]" >&2
  exit 2
fi

if [[ $# -eq 1 ]]; then
  source_repository=$(cd "$1" && pwd)
else
  source_repository="$temporary_root/repository"
  git init -q "$source_repository"
  git -C "$source_repository" fetch --no-tags --depth=1 "$source_url" "$source_commit"
fi

actual_commit=$(git -C "$source_repository" rev-parse "$source_commit^{commit}")
actual_tree=$(git -C "$source_repository" show -s --format=%T "$source_commit")
[[ "$actual_commit" == "$source_commit" ]] || {
  echo "exact Matic source commit drift: $actual_commit" >&2
  exit 1
}
[[ "$actual_tree" == "$source_tree" ]] || {
  echo "exact Matic source tree drift: $actual_tree" >&2
  exit 1
}

source_work="$temporary_root/source"
mkdir -p "$source_work"
git -C "$source_repository" archive "$source_commit" | tar -x -C "$source_work"

(
  cd "$source_work"
  export COREPACK_HOME="$temporary_root/corepack"
  corepack yarn@1.22.22 install --frozen-lockfile --ignore-scripts
  corepack yarn@1.22.22 exec -- ts-node ./script/build.ts --network matic --subgraph-type v3
  ./node_modules/.bin/graph build v3-subgraph.yaml
)

"$python_executable" "$repository_root/scripts/verify-uniswap-v3-matic-target.py" \
  --root "$repository_root" \
  --exact-source-root "$source_work"

echo "verified exact Uniswap V3 Matic source commit/tree, locked toolchain, manifest, schema, ABIs, and mapping bytes"
