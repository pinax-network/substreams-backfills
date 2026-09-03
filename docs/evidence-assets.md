# Evidence assets

Large generated contract blobs no longer live in the working tree. They are
immutable, content-addressed GitHub release assets, bound to the tree by one
small lock file, `evidence-assets.lock.json`, and retrieved by one Rust
command. Nothing else in the repository changes: every retained verifier still
opens the same path and still fails closed if the bytes are absent or altered.

## Moratorium on new static certificates

No new `*/v1` or `*/v2` static certificate directory may be added under
`uniswap-v3/` (issue #108, tracker #118). New evidence for issues #37 and #38
comes from executed fixtures and differential runs (#113, #114, #116). The
rare exception, a static certificate that a reviewer judges necessary, goes
through a pull request that states why executed evidence is impossible for
that claim, adds the blob to the lock and to a new immutable release, and is
approved by the operator before merge.

## What is externalized

Every tracked `contract.json` or `contract-v1.json` of at least 512 KiB. The
first lock (release `evidence-assets-v1`) holds 16 files, 94,262,624 bytes,
from 39 tracked contract files totalling 97,388,376 bytes. The threshold is
what brings a plain checkout of `uniswap-v3/` under 10 MiB; the 11 files over
1 MiB alone left it at 11 MiB. The `uniswap-v3/graft-ancestry/v1/artifacts/`
IPFS objects stay in the tree: they are inputs, not outputs.

## Additional locks

The same format and commands serve other content-addressed sets through
`--lock PATH`: `uniswap-v3/fixtures/blocks.lock.json` (release
`block-fixtures-v2`, one Firehose block protobuf per asset for #113, asset
names keep the `.pb` extension). Each lock maps to exactly one immutable
release tag.

## Tracked in-tree pins

Besides the externalized `assets`, the lock may carry a `tracked` list: in-tree
contract files pinned by byte length and SHA-256 but not moved to a release.
`cargo xtask evidence check` verifies both lists; `cargo xtask evidence lock
--track PATH` adds entries. The first tracked set (#110) pins the twelve
smaller `contract.json` outputs of the retired static-certificate verifiers, so
their identity stays checked in CI after the verifiers themselves are gone (see
`docs/provenance/README.md`, "Retired static-certificate verifiers").

## Lock format

```json
{
  "schema": "pinax.substreams-backfills.evidence-assets/v1",
  "repository": "pinax-network/substreams-backfills",
  "release_tag": "evidence-assets-v1",
  "assets": [
    { "path": "uniswap-v3/all-handlers/v1/contract.json",
      "asset": "sha256-<64 hex>.json", "bytes": 14769915, "sha256": "<64 hex>" }
  ]
}
```

Rules enforced by `xtask/src/evidence.rs`: exact schema string; `owner/name`
repository; a tag made of `[A-Za-z0-9._-]`; assets sorted by path with no
duplicate path or asset name; relative forward-slash paths with no `..`;
positive byte length; lowercase 64-hex SHA-256; and the asset name must equal
`sha256-<digest>.json`, so a name can never point at different bytes.

## Release and tag ownership

Each lock version maps to one release tag that is never reused, edited, or
re-uploaded. Adding or changing a blob means a new tag (`evidence-assets-v2`)
and a lock change in the same pull request. The tag points at the `main`
commit that was current when the assets were published; that commit is
provenance only, the digests are the identity. The fetcher never reads
"latest": it resolves the exact tag, checks that the release reports the
locked byte length, downloads to a temporary file, verifies length and digest,
and only then promotes the file. `cargo xtask evidence audit-release`
additionally requires the published asset set to equal the lock exactly, so a
missing, extra, or resized asset fails.

## Commands

```sh
cargo xtask evidence check                  # offline; verifies every locked path in the tree
cargo xtask evidence fetch                  # cache, then release; needs GITHUB_TOKEN, GH_TOKEN, or `gh auth login`
cargo xtask evidence fetch --offline        # cache only; fails on anything not already present
cargo xtask evidence fetch --mirror DIR     # local directory of content-addressed assets
cargo xtask evidence audit-release          # published asset set must equal the lock
cargo xtask evidence lock --release-tag T --write PATH...   # regenerate the lock (review, then publish)
```

`check` prints one row per locked path: `ok`, `MISSING` ("evidence blob not
fetched: <path> (run `cargo xtask evidence fetch`)"), or `MISMATCH` with the
expected and observed length or digest. Retained Python verifiers that open a
missing blob report their own fail-closed `cannot load <path>` error; after
`fetch` they run unchanged.

## Cache

Fetched bytes are cached at `$XDG_CACHE_HOME/substreams-backfills/evidence-assets/sha256/<digest>`
(or `~/.cache/...`). The cache is keyed by digest, so a stale or poisoned
entry can only ever fail verification, in which case it is deleted and the
asset is downloaded again. CI restores that directory with `actions/cache`
keyed by the SHA-256 of the lock file and runs `cargo xtask evidence fetch`
before any verifier; a restored cache never bypasses verification.

## Round trip proof

The publication procedure for a lock version is: generate the lock from the
tree, copy each file to its content-addressed asset name, create the release
with `gh release create <tag> --target <main commit>`, upload the assets, run
`cargo xtask evidence audit-release`, then fetch into an empty directory and
run `cargo xtask evidence check` there. Only after both pass are the tracked
blobs removed from the tree. The pull request that introduces a lock version
records the full inventory and the two command outputs.
