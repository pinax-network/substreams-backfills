#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_url="https://github.com/NgoKimPhu/infinity-cl-subgraph.git"
source_commit="40b0021be04cda3e32dde8e3cf0c3397863fc0c0"
source_tree="b7a7778bc5c7f316cc46913b7b1d54ffcfa07c22"
source_parent="e53351269ab0bb9a265ab04d71189156f3fa03a8"

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
  # Include the direct parent so Git does not hide `%P` behind a shallow boundary.
  git -C "$source_repository" fetch --no-tags --depth=2 "$source_url" "$source_commit"
fi

actual_commit=$(git -C "$source_repository" rev-parse "$source_commit^{commit}")
actual_tree=$(git -C "$source_repository" show -s --format=%T "$source_commit")
actual_parent=$(git -C "$source_repository" show -s --format=%P "$source_commit")
tracked_file_count=$(git -C "$source_repository" ls-tree -r --name-only "$source_commit" | wc -l | tr -d ' ')
[[ "$actual_commit" == "$source_commit" ]] || {
  echo "exact Pancake source commit drift: $actual_commit" >&2
  exit 1
}
[[ "$actual_tree" == "$source_tree" ]] || {
  echo "exact Pancake source tree drift: $actual_tree" >&2
  exit 1
}
[[ "$actual_parent" == "$source_parent" ]] || {
  echo "exact Pancake source parent drift: $actual_parent" >&2
  exit 1
}
[[ "$tracked_file_count" == "58" ]] || {
  echo "exact Pancake source inventory drift: $tracked_file_count tracked files" >&2
  exit 1
}

node_version=$(node --version | sed 's/^v//')
npm_version=$(npm --version)
[[ "$node_version" == "24.13.1" ]] || {
  echo "exact Pancake reproduction requires Node 24.13.1, found $node_version" >&2
  exit 1
}
[[ "$npm_version" == "11.11.0" ]] || {
  echo "exact Pancake reproduction requires npm 11.11.0, found $npm_version" >&2
  exit 1
}

source_snapshot="$temporary_root/source-snapshot"
source_work="$temporary_root/build-work"
mkdir -p "$source_snapshot" "$source_work"
git -C "$source_repository" archive "$source_commit" | tar -x -C "$source_snapshot"
cp -R "$source_snapshot/." "$source_work/"

(
  cd "$source_work"
  npm ci --legacy-peer-deps --ignore-scripts
  npm run build
)

# Graph's build tooling may normalize the otherwise unused Yarn lock while running
# under npm. Keep the source snapshot immutable and attach only the build outputs.
cp -R "$source_work/build" "$source_snapshot/build"

cargo +stable run --quiet --manifest-path "$repository_root/Cargo.toml" --package xtask -- \
  verify-target pancakeswap-infinity-cl-bsc \
  --root "$repository_root" \
  --exact-source-root "$source_snapshot"

echo "verified exact Pancake commit/tree/parent, 58-file source lock, independently pinned reproduction toolchain, and byte-identical deployed build"
