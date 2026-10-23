# Aerodrome Slipstream Base extractor

This is the S-X1 foundation and initial S-X2 candidate/registry implementation for
`QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`. It is an independent Cargo
workspace pinned to Rust 1.90.0, Substreams 0.7.6, Ethereum 0.11.1 and prost 0.13.5.

The development manifest exposes `map_pools_created`, `store_pools`, and
`map_candidates`. The latter produces the shared `ExtractorBlock` shape, with
`calls` absent. **It is not the completed extractor.** The final output module
will be `map_extractor_block`, after storage derivation and all call-answer stages
are implemented. No release, full noop or backfill may use this candidate output.

The generated ABI decoder selects the exact locked deployment events. Candidates
retain malformed payloads for the reducer's Graph Node decoder. Receipt
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
than truncated. Block-level storage aggregation and answer generation are not
implemented yet.

From the repository root:

```console
cargo xtask aerodrome-substreams protogen --check
cargo xtask aerodrome-substreams check
cargo xtask aerodrome-substreams build
cargo xtask aerodrome-substreams build --twice
```

`protoc` must be installed. `protogen` without `--check` updates checked-in output.
All builds/tests use the locked workspace. `build --twice` compares the two WASM
hashes from independent source and target roots with source/toolchain paths
remapped. Only the two implemented WASM crates are built, not the native generator.
CI also packs the development graph with checksum-pinned Substreams CLI v1.20.3.

The checked-in `fixtures/candidates-13899663.json` is a **field projection** from the
October 20 Firehose capture, with original capture hash and projection provenance.
It retains all 209 receipt logs, transaction identity/gas fields, and creation
code needed for candidate extraction. It proves the real first-pool sequence
`[(0,172),(0,177),(0,178),(1,171),(1,176)]`; it is not a full storage/oracle fixture.
Start-boundary and failure cases use explicitly synthetic mutations of that input.

Still required: complete S-X2 family block-fixture lock and X-START/X-NPM-START/
X-GUARD real goldens; S-X3 storage deltas/carry stores; S-X4 storage answers and
ERC20-only RPC module; final aggregation; root-oracle differential and seeded
archive audits; measured store sizes; frozen package bytes and release locks.
No `packages/` or `release/` artifact is created until those gates pass. Changes
after any future noop require a new module-hash/cache identity.
