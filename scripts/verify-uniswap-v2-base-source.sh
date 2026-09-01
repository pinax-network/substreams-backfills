#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_url="https://github.com/Uniswap/v2-subgraph.git"
source_commit="6fba1a6f7304df83c08c3555bc90a38028f1435c"
schema_history_commits=(
  "cc2937655d30b2018aea1b3be926d66ff1063904"
  "2fe2b1cc2f904a76418ca816e355dabf7e4e8d78"
  "84f2b0e2ad00b33af9c64695be842c744d86ff04"
  "fd314244a7e98e41ad6dbe6ddc60e507b310209c"
  "5b4d53d0e421586e3bb0ad8d97df3254e1e046d5"
  "c157bd3e6186499268875010836b34be066875e8"
  "ec90ef8f86a6a9075c3dd48bc63698347d50651a"
)
generic_url="https://github.com/pinax-network/substreams-evm.git"
generic_commit="970a665e15619de8ad7f686bd89412a1030d46dc"
python_executable="${UNISWAP_V2_BASE_SOURCE_PYTHON:-python3}"

temporary_root=$(mktemp -d)
cleanup() {
  rm -rf "${temporary_root:?}"
}
trap cleanup EXIT

if [[ $# -ne 0 && $# -ne 2 ]]; then
  echo "usage: $0 [behavioral-source-repository generic-extractor-repository]" >&2
  exit 2
fi

if [[ $# -eq 2 ]]; then
  source_repository=$(cd "$1" && pwd)
  generic_repository=$(cd "$2" && pwd)
else
  source_repository="$temporary_root/v2-subgraph"
  generic_repository="$temporary_root/substreams-evm"
  git init -q "$source_repository"
  git -C "$source_repository" fetch --no-tags --depth=1 "$source_url" \
    "$source_commit" "${schema_history_commits[@]}"
  git -C "$source_repository" checkout -q --detach "$source_commit"
  git init -q "$generic_repository"
  git -C "$generic_repository" fetch --no-tags --depth=1 "$generic_url" "$generic_commit"
  git -C "$generic_repository" checkout -q --detach FETCH_HEAD
fi

"$python_executable" "$repository_root/scripts/verify-uniswap-v2-base-target.py" \
  --root "$repository_root" \
  --source-root "$source_repository" \
  --generic-source-root "$generic_repository"

echo "verified pinned behavioral-source and generic-extractor commits, trees, Git blobs, target config, and explicit non-reproduction gaps"
