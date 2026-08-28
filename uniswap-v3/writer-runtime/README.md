# Uniswap V3 diagnostic writer runtime v1

This overlay adds one isolated `map_writer_events` diagnostic to the frozen
Uniswap V3 source after the existing ChainConfig overlay. It does not replace
`graph_out`, add a store or RPC call, populate subgraph entities, or authorize a
backfill or production package.

## Materialization order

The only supported construction is:

1. the exact frozen `uniswap-v3/source/` tree;
2. `uniswap-v3/chain-config/runtime.patch`;
3. `uniswap-v3/writer-runtime/runtime.patch`;
4. the versioned configs, profiles, fixture, and manifests in this directory.

`contract-v1.json` binds the two patch digests and every materialized runtime,
protobuf, generated-binding, ABI, profile, config, manifest, fixture, and lint
contract digest. The verifier rejects the writer patch when applied before the
ChainConfig patch and rejects missing, extra, reordered, rehashed, overlapping,
or gapped segment profiles.

Materialize only into an empty directory outside this repository:

```sh
PYTHON=python3 ./scripts/materialize-uniswap-v3-writer-runtime.sh /tmp/uniswap-v3-writer-runtime
```

The script canonically resolves the destination before its first write. The
repository, every repository descendant, the frozen source, `..` aliases, and
symlinks or case aliases resolving into the repository are refused. Before
materialization, the live source is checked against the exact 75-file
provenance inventory (path, regular-file type, mode, size, and digest), with
only a real top-level build `target/` directory ignored. The actual copy is
then produced from the pinned Git tree, not from the live filesystem.

## Diagnostic event contract

`map_writer_events` receives only its digest-bound ChainConfig selector and an
Ethereum `Block`. It selects one of exactly eight embedded profiles from the
configured network plus the block number; callers cannot supply a profile. It
then scans `Block::logs()`, which exposes successful transaction-receipt logs,
and decodes logs at that network's NonfungiblePositionManager address.

The repeated `uniswap.writer.v1.WriterEvent` oneof retains every recognized
`IncreaseLiquidity`, `DecreaseLiquidity`, `Collect`, and `Transfer` occurrence.
It preserves the transaction hash, block number, transaction and block log
indices, contract address, global ordinal, and unscaled ABI integer values as
base-10 strings. Foreign-address and unknown-signature logs continue. A
recognized malformed event or duplicate retained ordinal is a deterministic
error, as is an accepted event whose transaction hash is not exactly 32 bytes.
Failed transactions are ignored by the successful-receipt log view.

The mainnet and Base manifests each contain the same exact 23-module set and
one shared WASM reference. The diagnostic map has no consumer and no direct or
transitive path to the unchanged legacy `graph_out` inputs and EntityChanges
output.

## Base boundary

The Base runtime, Factory handler, and Factory creation boundary are
`1,371,679`; the direct NonfungiblePositionManager event gate is `1,371,713`.
Tests cover `1,371,678`, `1,371,679`, `1,371,712`, and `1,371,713` separately.
This correction is supported by the QmPW root manifest and graft ancestry v2.
It is not represented as independent Factory bytecode-creation proof.

## Toolchain and lint boundary

The runtime pins Rust `1.79.0`, `prost`, `prost-types`, and `prost-build`
`0.13.3`, `substreams` `0.6.4`, `substreams-ethereum` `0.10.6`,
`substreams-entity-change` `2.0.0`, and the Pest family `2.7.14`. The older
`prost` `0.11.9` line remains only as a transitive requirement of
`substreams-ethereum-core` `0.10.6`.

The frozen upstream corpus has a pinned 1,068-diagnostic Clippy baseline over
the lib and lib-test targets. New runtime files have zero diagnostics. The
Substreams handler macro adds the acknowledged
`clippy::not_unsafe_ptr_arg_deref` diagnostic for `map_writer_events` once per
target, producing 1,070 total; the exact `(file, lint, count)` inventory is
bound in `clippy-baseline-v1.json`. No crate-wide lint allowance is added.

## Verification

```sh
python3 scripts/verify-uniswap-v3-writer-runtime.py
python3 -m unittest scripts.tests.test_uniswap_v3_writer_runtime
```

After materialization, the verifier can additionally bind the exact runtime
change set. After one WASM build and two `substreams pack` calls, passing both
packages proves each contains exactly one byte-identical copy of that WASM,
the exact ordered 23-module graph (inputs, modes, policies, starts, types, and
entrypoints), independently recomputes every Substreams v1.20.3 module hash
from the embedded WASM, and binds the protobuf descriptor set. The stable graph
digest deliberately excludes the derived module hashes: Rust 1.79 can emit
different diagnostic WASM bytes on different build hosts. The later controlled
release gate, not this diagnostic tranche, pins the authoritative build-host
WASM and package identities.

Every runtime, parity, PoI, boundary-continuity, backfill, and production gate
remains false.
