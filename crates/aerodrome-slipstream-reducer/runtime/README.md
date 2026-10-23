# Development producer packaging

This path builds and inspects `pinax.backfill.producer/v1` bundles. Every bundle,
smoke receipt and discovery document remains `production_selectable: false`.
It does not publish an image, create a release, authorize a database write or
complete production qualification. The physical profile belongs to the target
configuration and is deliberately absent from this image (integrated K9).

The closed runtime consists of `bin/producer`, `source.json`, the exact descriptor
and raw-digest sidecar, family requirements, and the extractor SPKG, lock and
identity. `runtime.json` hashes all eight files. Descriptor, package, module,
source commit and executable links are verified again by the running producer.
The extractor lock digest is its own raw SHA-256, distinct from the runtime
manifest digest. Deployment family `aerodrome-slipstream-base` retains the
historical checkpoint family `aerodrome-slipstream` without rewriting old state.

## Source and bundle construction

The Rust xtask exports **all regular blobs from an exact Git commit**, preserving
paths and executable modes. It refuses submodules and symlinks, ignores dirty
checkout and untracked contents, and seals every source byte in `source.json`.
This intentionally includes workspace metadata, build scripts, ABI/schema files,
and every compile-time include. The verifier checks the complete source file
inventory before and after building; only `target/` may be generated. A claimed
source digest is identity evidence, not reproducible-build or compiler evidence.

```sh
cargo xtask producer-runtime context --root . --revision COMMIT --output /tmp/producer-context
cargo xtask producer-runtime verify-source --root /tmp/producer-context
cargo xtask producer-runtime build-bundle --root /tmp/producer-context \
  --spkg /path/to/extractor.spkg --extractor-lock /path/to/extractor-lock.json \
  --output /tmp/producer-bundle
cargo xtask producer-runtime smoke --root /tmp/producer-bundle --output /tmp/producer-smoke
cargo xtask producer-runtime archive --root /tmp/producer-bundle \
  --smoke /tmp/producer-smoke/smoke.json --output /tmp/producer-archive
cargo xtask producer-runtime verify-discovery --root /tmp/producer-archive
```

`build-bundle` invokes the real release build of `producer` inside that verified
context. It never accepts an arbitrary binary as proof of that source. The
extractor is an independent input: the canonical lock must pin its source commit,
SPKG digest, module hash, output type and initial block. The loader recomputes the
supported map/store module graph signature from package contents using the
Substreams v1.18.4 algorithm. Unsupported executable fields, network overrides,
filters, missing modules and cycles refuse. Runtime params cannot override the
SPKG. All output directories must be fresh; publication uses atomic no-replace
promotion after verification and filesystem sync.

## Smoke and archive boundaries

The host smoke executes the bundled binary for exact version identity, staging,
no-clobber refusal, non-final execution refusal and an empty root seed. Public
CLI integration tests separately exercise a bounded synthetic stream with a real
inherited completion pipe, failure rollback and exact rewind. These are offline
checks, not evidence that Substreams ran, nor a receipt for an engine segment.
The development tar and discovery JSON record exact bytes without inventing an
OCI digest. Discovery validates file hashes and the unpacked closed bundle.

`producer-runtime.yml` runs contract tests on PRs. Its manual candidate job
requires an existing explicitly pinned extractor release, builds a native Linux
image, records its real image inspection, checks `version` offline, and smokes
the extracted same-host Linux binary. It uploads evidence only, with no registry
push or release. The image's no-network container check is limited to `version`;
state and stream checks must not be described as container execution. An OCI
attachment publication/independent registry retrieval gate remains future work
until a real candidate image and release are authorized and available.

## Retained local validation

`host-smoke-v1.json` pins the actual Darwin arm64 bundle built from producer
commit `bd9a88d120e9c846e583a81a257d988e6988aadf`, using the independently retained
M2 extractor from `5e65aa2226dbcb42ae25e8784af989327967e1e6`. Packaging tool commit
`911653033a38dab8ab9d78437a997165d9954616` verified the 1,048 committed source blobs,
ran the real version/stage/seed subprocesses, and round-tripped the closed archive.
`host-smoke-steps-v1.json` retains their actual exit codes. Full artifacts remain
under `/private/tmp/aerodrome-producer-runtime-proof-v1`; they have not been
published as release assets. No OCI digest is claimed for this host executable.

Validation passed 480 other workspace tests, all 334 xtask tests, and one doctest.
The fresh worktree initially lacked two ignored legacy Uniswap V3 fixtures;
only their exact `evidence-assets.lock.json` hashes were restored before the
334-test rerun. Public producer tests independently passed all three process
scenarios. The six packaging tests cover source closure, path/symlink refusal,
no-clobber publication, deterministic archive tampering and workflow scope.

Strict reducer Clippy passed. Strict xtask Clippy encounters two pre-existing
`clippy::nonminimal_bool` warnings in `xtask/src/logical_oracle.rs` at lines 697
and 848. Those unrelated expressions remain unchanged. A separate xtask check
passed with all other warnings denied and only that named lint allowed; this is
not reported as a full strict xtask Clippy pass. No Linux image was built or
smoked locally because the available Docker daemon was unavailable.
