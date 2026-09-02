#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_url="https://github.com/pancakeswap/pancake-subgraph.git"
source_commit="1da7ba61abb26633ff819ce8cdfe945be8770a92"
source_tree="a2a113c9eedd7ed0e6fdcaea275153233223c95d"
source_parent="e2019f716f4310f4ce28addc4439980804d9e413"

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
[[ "$actual_commit" == "$source_commit" ]] || {
  echo "exact Exchange V3 source commit drift: $actual_commit" >&2
  exit 1
}
[[ "$actual_tree" == "$source_tree" ]] || {
  echo "exact Exchange V3 source tree drift: $actual_tree" >&2
  exit 1
}
[[ "$actual_parent" == "$source_parent" ]] || {
  echo "exact Exchange V3 source parent drift: $actual_parent" >&2
  exit 1
}

[[ "$(node --version)" == "v14.21.3" ]] || {
  echo "Exchange V3 reproduction requires Node v14.21.3" >&2
  exit 1
}
[[ "$(yarn --version)" == "1.22.22" ]] || {
  echo "Exchange V3 reproduction requires Yarn 1.22.22" >&2
  exit 1
}

source_work="$temporary_root/source"
mkdir -p "$source_work"
git -C "$source_repository" archive "$source_commit" | tar -x -C "$source_work"

original_lock="$temporary_root/original-yarn.lock"
cp "$source_work/yarn.lock" "$original_lock"

# The source lock points at a deleted GitHub fork tarball used by Graph CLI's IPFS client.
# Replace exactly that unavailable transport artifact for installation only. The historical
# lock is restored before source validation, and the compiler packages plus all three output
# byte strings remain strict gates.
concat_stream_old="$temporary_root/concat-stream.old"
concat_stream_new="$temporary_root/concat-stream.new"
cat >"$concat_stream_old" <<'LOCK'
"concat-stream@github:hugomrdias/concat-stream#feat/smaller":
  version "2.0.0"
  resolved "https://codeload.github.com/hugomrdias/concat-stream/tar.gz/057bc7b5d6d8df26c8cf00a3f151b6721a0a8034"
  dependencies:
    inherits "^2.0.3"
    readable-stream "^3.0.2"
LOCK
cat >"$concat_stream_new" <<'LOCK'
"concat-stream@github:hugomrdias/concat-stream#feat/smaller":
  version "2.0.0"
  resolved "https://registry.yarnpkg.com/concat-stream/-/concat-stream-2.0.0.tgz#414cf5af790a48c60ab9be4527d56d5e41133cb1"
  integrity sha512-MWufYdFw53ccGjCA+Ol7XJYpAlW6/prSMzuPOTRnJGcGzuhLn4Scrz7qf6o8bROZ514ltazcIFJZevcfbo0x7A==
  dependencies:
    buffer-from "^1.0.0"
    inherits "^2.0.3"
    readable-stream "^3.0.2"
    typedarray "^0.0.6"
LOCK
# Exact single-occurrence replacement of the dead transport block (no scripting runtime needed).
old_count=$(grep -c -F -x -- '  resolved "https://codeload.github.com/hugomrdias/concat-stream/tar.gz/057bc7b5d6d8df26c8cf00a3f151b6721a0a8034"' "$source_work/yarn.lock" || true)
if [[ "$old_count" -ne 1 ]]; then
  echo "dead concat-stream transport lock did not match exactly once" >&2
  exit 1
fi
perl -0pi -e '
  BEGIN { local $/; open(my $o, "<", $ARGV[0]) or die; $old = <$o>; open(my $n, "<", $ARGV[1]) or die; $new = <$n>; shift @ARGV; shift @ARGV; }
  my $count = () = $_ =~ /\Q$old\E/g;
  die "dead concat-stream transport lock did not match exactly once\n" unless $count == 1;
  s/\Q$old\E/$new/;
' "$concat_stream_old" "$concat_stream_new" "$source_work/yarn.lock"

(
  cd "$source_work"
  export YARN_CACHE_FOLDER="$temporary_root/yarn-cache"
  yarn install --frozen-lockfile --ignore-scripts
)

cp "$original_lock" "$source_work/yarn.lock"
cmp "$original_lock" "$source_work/yarn.lock"

(
  cd "$source_work"
  NETWORK=bsc yarn workspace exchange-v3-template template
  yarn workspace exchange-v3-template codegen
  yarn workspace exchange-v3-template build
)

cargo +stable run --quiet --manifest-path "$repository_root/Cargo.toml" --package xtask -- \
  verify-target exchange-v3-bsc \
  --root "$repository_root" \
  --exact-source-root "$source_work"

echo "verified exact Exchange V3 BSC source commit/tree/parent, locked compiler toolchain, manifest, schema, ABIs, and all three mapping binaries"
