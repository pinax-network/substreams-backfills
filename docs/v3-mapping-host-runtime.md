# Deployed-mapping execution image

The mapping host now has its own Linux/amd64 image build and publication path.
This packages the existing tested producer; it does not certify full Mainnet
ancestry, a graft transition, production loading, or memory-bounded operation.
`production_selectable` remains `false`. No V4 image or default alias changes.

## Exact build and verification boundary

`mapping-host/runtime/package.py context` exports an allowlist of **committed Git
objects**, not the working directory: root workspace declarations, `common`, the
mapping-host sources/lockfile/toolchain/vendored Graph Node patch, every
deployed bundle under `mapping-host/segments/` (the eight Uniswap V3 deployments
and the Aerodrome Slipstream Base oracle segment), and the runtime packaging
implementation. Untracked files, dirty edits, `.git`, local build caches,
credentials and recorded cassettes cannot enter that build. Only this exported
directory is a supported Docker context. The builder verifies the complete input
inventory before compiling with the pinned Rust 1.98.0 toolchain and locked
dependency graph.

The Rust builder and Debian runtime bases are pinned to their Linux/amd64
manifest digests. OS packages are installed from Debian repositories at build
time; rebuilds are not claimed bit-for-bit reproducible. The final OCI digest
pins the resulting OS dependencies, as well as the executable and bundles.

Inside the image:

- `/usr/local/bin/graph-mapping-host`: the execution binary.
- `/opt/mapping-host/segments/<deployment>/`: nine original bundles (eight
  Uniswap V3 deployments and Aerodrome Slipstream Base), descriptors and
  checksum sidecars; every byte matches the exact build commit.
- `/opt/mapping-host/source.json`: committed source input inventory.
- `/opt/mapping-host/runtime.json`: source commit, source-input set hash, binary
  digest, and complete application-payload inventory. This deliberately contains
  no self-referential image digest.

The image runs as UID/GID 10001. Callers should use a read-only root filesystem,
no added capabilities, writable `/tmp`, and a separate run-specific artifact
volume. Live mode reads `FIREHOSE_ENDPOINT` and `FIREHOSE_API_KEY`; recorded
historical `eth_call` misses additionally require `ETHEREUM_RPC_URL`. Inject
credentials from existing Secrets, never in manifests, arguments or receipts.
There is no production entrypoint that submits workflows or opens a database.
Only `run` and `verify-bundle` are covered by this packaged-runtime interface;
source-tree maintenance commands are not certified runtime tools.

## CI and release identity

The native Linux image must verify every bundle and replay the four locked
sampled root blocks with networking disabled, read-only inputs/root filesystem,
and UID 10001. BCF1 payloads and the complete report must match committed goldens.
These four blocks are **not contiguous**, and this smoke test does not replace
the separately retained 1,053-block root lifecycle proof.

Only a successful main push publishes `mapping-host-sha-<full-commit>` under
`ghcr.io/pinax-network/substreams-backfills`. PR builds do not publish. The exact
tested image is pushed, then the application payload is extracted from its
immutable digest to create an archive. An external publication JSON binds that
archive, runtime identity, source commit and image digest. Both attach to the
image through an OCI referrer; CI downloads that referrer and compares both
payloads byte-for-byte. The Actions artifact contains the same published pair
and attachment reference. No `latest` or production alias is updated.

The discovery verifier is pinned to the [ORAS 1.2.3 JSON model](https://github.com/oras-project/oras/blob/v1.2.3/cmd/oras/internal/display/metadata/model/discover.go):
its top-level array is `manifests`, not `referrers`, and each descriptor carries
its own repository reference. `package.py verify-discovery` requires one exact
attachment digest, reference, artifact/media type, source revision and byte size.
It hashes the fetched manifest and checks its subject and revision independently;
discovery output alone has no subject field. Missing, malformed or duplicate
records fail closed. The existing subject gate and downloaded archive/publication
byte comparisons remain mandatory. The fetched manifest and discovery JSON are
retained with the successful publication artifact.

Canonical [run 33949642564](https://github.com/pinax-network/substreams-backfills/actions/runs/33949642564)
published the first runtime and attachment, but failed because its discovery check
read `.referrers[]`. That failed run remains historical evidence, not a successful
release certificate. The repaired workflow must pass on its own reviewed candidate
and canonical source; neither the parser repair nor sampled smoke proves the
complete Kubernetes root lifecycle or full Mainnet readiness.

The archive contains application files, **not** a portable copy of every OS
library. Execute the digest-pinned image. Before using a new canonical build,
verify its exact commit/tree, successful CI, attachment subject, archive hashes,
and all runtime files independently. A receipt from another commit is not a
substitute. This is an execution runtime, never an evidence-only overlay.

## Remaining production work

Immutable resumable metadata chunks and engine checkpoints are separate work;
the v1 root-only refusals are unchanged by packaging. The current in-memory
entity/cache/checkpoint representation still grows with deployment state. Full
ancestry requires bounded-state and sustained-throughput evidence, all graft
transitions, current eligibility, and the current Mainnet deployment's own
differential/oracle checks before activating a serving indexer.
