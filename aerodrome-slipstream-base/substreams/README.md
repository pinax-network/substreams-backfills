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
