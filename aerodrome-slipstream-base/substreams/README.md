# Aerodrome Slipstream Base extractor

This contains the S-X1 foundation, S-X2 candidate/registry implementation, and
initial S-X3 storage-delta/carry and S-X4 call-answer implementations for
`QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`. It is an independent Cargo
workspace pinned to Rust 1.90.0, Substreams 0.7.6, Ethereum 0.11.1 and prost 0.13.5.

The development manifest exposes `map_pools_created`, `store_pools`,
`map_candidates`, `map_storage_deltas`, and the pool, tick, and position carry
stores. `map_candidates` is an internal stage with `calls` absent.
`map_extractor_block` assembles candidates, storage-derived call answers, raw
ERC20 metadata, and combined anomaly counts into the public output. **This is
still an unqualified development package.** No release, full noop or backfill
may use it before the remaining gates below pass.

Generated ABI signatures select the exact locked deployment events, with an
Abigen decode flag retained for diagnostics. Registration, last-tick carry and
answer selection use Graph Node's exact alloy decoder, including accepted trailing
ABI words. Candidates retain malformed payloads for the reducer's decoder. Receipt
`block_index` determines trigger order, while logs for newly created pools enter
wave 1 even when emitted before their `PoolCreated`. The registry reads
end-of-block state. `store_pools` takes the Substreams clock as a second input to
record the creation block; the canonical `PoolsCreated` protobuf has no block field.

`crates/pb` owns the public/internal schemas and checked-in prost output. It also
vendors Ethereum bindings from `substreams-ethereum-core` 0.11.1, pinned by source
commit and SHA-256 in `ethereum-bindings.json`. These Apache-2.0 upstream bindings
are unchanged. `protogen --check` regenerates our schemas and separately checks
those vendored bytes. The native `core` depends on neither Substreams runtime nor
Ethereum runtime; reducers can path-depend on `pb` and `core` with prost 0.13.5.

The pure core includes exact configuration, storage-layout hashing and decoding,
validated preimage classification, checked Graph Node/alloy gas pricing, canonical
call keys, shard keys, zero/burn carry deletion, and the signed-remainder swap-walk
superset. uint80 pool IDs that exceed the wire schema's uint64 are refused rather
than truncated.

Storage aggregation accepts extended v4/v5 blocks, uses each storage change's
address (including delegate calls), and chooses the last successful write by
ordinal. It excludes reverted frames and failed transactions while retaining
their counts. Pool lookup uses end-of-block registry state, so writes preceding
`PoolCreated` remain visible. Carry stores retain pool fee growth, tick markers
and fee growth, position fragments and fee growth, and NPM pool keys. Zero words
are deleted; tick initialization markers survive later clearing. Ambiguous or
unclassified pool storage refuses carry writes. System-call writes to a target
also refuse; they are not silently treated as ordinary transaction writes.

Last-tick carry decodes Initialize/Swap using Graph Node's exact alloy 1.7.2
decoder and the locked Pool ABI. The candidate `abi_decoded` flag is diagnostic
and cannot suppress a Graph Node-accepted tick. Graph Node accepts some values
outside the ABI's int24 domain; this implementation explicitly refuses those
values because the storage layout and tick walk require int24. It does not
silently truncate them.

Pool fee growth, tick boundary and swap-walk answers, position fragments and fee
growth, and factory getPool answers read end-of-block carry values. Swap walks
start from the previous block's tick using `get_first`, then follow this block's
Initialize/Swap order. Missing prior ticks and missing NPM pool keys are explicit
anomalies; absent position fragments are explicit reverts. Every emitted slot
answer distinguishes in-block, carried, and absent/zero provenance.

Factory answers also include the deployed Swap version-upgrade helper: for each
registered pool token other than USDC, `getPool(USDC, token, 100/500/3000/10000)`
uses literal third arguments in mapping order. The extractor supplies this
conservative superset on every Swap because entity version lives in the reducer.
C9 and C10 keys are deduplicated together and read the end-of-block registry.
The helper's discarded array-copy mutations do not make its host calls optional.
`fixtures/swap-upgrade-calls.json` retains all 44 missing independent cassette
calls from the original full live attempt and 13 actual PoolCreated candidates
used to reconstruct registry state for the regression (including a nonzero result).
The old attempt remains failed call-completeness evidence; new source, package
identity, live capture and complete cassette verification are required.

`map_token_metadata` is the only module whose WASM imports `rpc.eth_call`. It
batches the four raw ERC20 selectors for the deduplicated tokens of every
PoolCreated. Failed or empty returns remain explicit reverts; string, bytes32,
numeric, and unknown-value fallbacks belong to the reducer. This module has not
yet passed the independent live archive audit required before release.

From the repository root:

```console
cargo xtask evidence fetch --lock aerodrome-slipstream-base/fixtures/blocks.lock.json
cargo xtask aerodrome-substreams protogen --check
cargo xtask aerodrome-substreams check
cargo xtask aerodrome-substreams build
cargo xtask aerodrome-substreams build --twice
cargo xtask aerodrome-substreams cache-boundary
```

`protoc` must be installed. `cache-boundary` also requires `substreams` and
`wasm-objdump` from WABT, with WASMs built first.
`protogen` without `--check` updates checked-in output.
All builds/tests use the locked workspace. `build --twice` compares the two WASM
hashes from independent source and target roots with source/toolchain paths
remapped. All four WASM crates are built, excluding the native generator.
CI packs the development graph with checksum-pinned Substreams CLI v1.20.3.
The cache-boundary check inspects actual WASM imports and mutates valid custom
sections in a temporary package. An RPC binary change must affect only metadata
and final-output hashes; an answers binary change must affect only the three
answer modules. It also verifies the 34-module inventory, initial blocks and
final protobuf output type.

The checked-in `fixtures/candidates-13899663.json` is a **field projection** from the
October 20 Firehose capture, with original capture hash and projection provenance.
It retains all 209 receipt logs, transaction identity/gas fields, and creation
code needed for candidate extraction. It proves the real first-pool sequence
`[(0,172),(0,177),(0,178),(1,171),(1,176)]`; it is not a full storage/oracle fixture.
Start-boundary and failure cases use explicitly synthetic mutations of that input.

The family block lock additionally binds the full raw Firehose block 13,899,663
and a later block. The storage regression verifies the first block's digest,
classifies all target writes without anomalies, applies its carry operations,
and checks positions(1), ticks(-1), ticks(1), and getPool against four exact
answers retained by the deployed mapping-host oracle. The small answer fixture
records its source cassette digest. The tick-decoder fixture projects 30 cases
from the independently generated Graph Node ABI corpus, with source commit,
path, and digest. Synthetic tests cover rollback, ordinal ties, delegate calls,
zero/burn deletion, fragment changes, and all carry shards. These are bounded
regressions, not the complete G2 storage qualification. A second raw-block test
compares those same four independent returns with the assembled public call
answers. Synthetic answer tests cover mixed provenance, swap marker windows,
in-block initialization, missing history, zero/reverted positions, missing pool
keys, corrupt/future carry, and the raw ERC20 batch boundary.

Still required: S-X2 X-START/X-NPM-START/X-GUARD real goldens; the S-X3 capture
utility and dense v5, reverted-write, Flash, and seeded-carry oracle fixtures;
the broader S-X4 answer goldens and live metadata audit;
root-oracle differential and seeded
archive audits; measured store sizes; frozen package bytes and release locks.
No `packages/` or `release/` artifact is created until those gates pass. Changes
after any future noop require a new module-hash/cache identity.

## Archive call audits

The native `aerodrome-extractor-audit` tool checks supplied answers against an
independent Base archive at the exact block hash. Configure
`BASE_ARCHIVE_RPC_URL` locally, then run:

```console
cargo xtask aerodrome-substreams audit-calls --input extractor.pb --output new-audit-directory
cargo xtask aerodrome-substreams audit-erc20 --input extractor.pb --output new-metadata-audit-directory
```

Inputs are canonical single-message `ExtractorBlock` protobufs. The tool checks
chain ID, block identity, duplicate answers and raw ERC20 masks; each call uses
EIP-1898 `blockHash` with `requireCanonical: true` and the frozen oracle's
50,000,000 gas limit. Storage answers compare every
field consumed by the deployed mapping. Only explicit execution-revert errors
(code 3 and an `execution reverted` message) or empty successful returns count
as reverts. Timeouts, missing archive state, generic errors and HTTP failures
abort. URLs and provider error details are excluded from receipts.

An audit creates a new output directory, retains normalized observations, and
emits a digest-bound success receipt only after all comparisons pass. Failed
attempts remain separate and exit 4; existing output directories are refused.
An empty answer set is explicitly marked `nonempty: false`. This verifies the
answers supplied, not missing-answer detection, extraction completeness,
provenance, full handler behavior or production readiness.

The `first_pool_input` example creates a bounded native fixture for block
13,899,663 using raw Firehose storage and eight retained ERC20 calls. It does
not capture a live WASM output or general seeded block. Its twelve calls are
checked against the independent retained cassette in normal tests. A fresh
archive audit also matched all twelve at block hash
`d83042b6a32dc9b18d4c7c9819b914bc04470f77458e7276cb72f3d8fde5eb3d`;
the input SHA-256 was
`e4cd95b41894ac5a84bb3fd36da75791d58686612fa9b9a4e9efeb1d04e3adb4`.
Dense, seeded, reverted-write and full-window metadata audits remain required.
