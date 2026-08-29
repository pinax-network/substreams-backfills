# Uniswap V3 provider-free NPM source blocks v1

This tranche adds a deterministic Substreams boundary for host-side Uniswap V3
NonfungiblePositionManager execution. It combines the exact existing
`map_writer_events` output with block identity and referenced transaction gas
metadata, without making provider calls or deciding Graph Node execution
success.

## Data flow

```text
params + sf.ethereum.type.v2.Block
  -> existing map_writer_events (existing writer WASM)

sf.ethereum.type.v2.Block + map_writer_events
  -> map_npm_source_block (separate source WASM)
  -> uniswap.npm.source.v1.NpmSourceBlock
  -> host-side integrated execution in a later tranche
```

The dedicated mainnet and Base manifests contain only those two modules. The
original writer manifests, 23-module graph, WASM, descriptors, and packages are
left byte-identical.

## Source message

Every requested block produces one message, including blocks with no NPM
events. `NpmSourceBlock` contains:

- the exact `WriterEvents` message emitted by the upstream module;
- block number, 32-byte hash, 32-byte parent hash, and positive whole-second
  timestamp in the protobuf `Timestamp` range;
- exactly the successful transaction traces referenced by writer events;
- transaction index, transaction gas limit, and canonical unsigned gas price;
- the pinned source semantic-contract digest.

Transactions are sorted by index and then hash. Gas price uses minimal unsigned
big-endian bytes, with an empty byte string for zero. Receipt `gas_used` and
transaction `gas_used` are not read.

The mapper rejects block/header drift, malformed identity widths, missing or
out-of-range timestamps, timestamp nanos, unsupported networks, writer segment
or contract drift, non-static NPM events, missing event oneofs, divergent
log/ordinal order, missing or non-successful transaction traces, duplicate
hashes or indexes, missing gas price, values above uint256, and noncanonical
protobuf bytes. A standalone decoder can revalidate the timestamp range and
canonical frame, but it cannot compare a decoded timestamp with the original
Firehose block after that input has left the projection boundary.

## Error and authority boundary

The source module has no provider. Position calls, factory calls, ordinal Token
entity reads, Graph Node error classification, handler fatal/nonfatal policy,
dynamic data-source execution, and state mutation remain host responsibilities.

Only resolved observations may cross a later reducer-input protobuf boundary.
`PossibleReorg` and `Unknown` outcomes must abort that later frame and checkpoint
creation; they must never be serialized as a returned-null call. Graph Node
`Ok(None)` remains distinct: recognized EVM reverts, empty responses, and output
decode failures are all resolved null outcomes in Graph Node v0.44.

An `NpmSourceBlock` is not checkpoint authority, Graph block-success authority,
or evidence that an integrated execution completed. A later host engine must
evaluate all observations, including those after a deterministic fatal handler.

## Package isolation

The source manifests use two WASM binaries:

- `writer`: the exact materialized writer-runtime WASM;
- `npm_source`: the standalone provider-free source mapper.

`map_npm_source_block` has only the Firehose block and `map_writer_events` as
inputs. There are no Stores, RPC clients, databases, checkpoints, `graph_out`,
or reducer modules in the source package.

The two-module source package has its own pinned 16-descriptor dependency
closure; it does not claim to inherit the complete descriptor set of either
original 23-module writer package. CI separately rebuilds the original writer
packages, checks them byte-for-byte, and validates their original descriptor
contract.

Materialization places the source manifests and this README in a dedicated
`npm-source-package` directory. Substreams v1.20.3 therefore embeds these
source-only limitations as package documentation without replacing the
unchanged writer runtime README used by the original writer packages.

## Verification

Materialize into an empty path outside this repository:

```sh
PYTHON=python3 ./scripts/materialize-uniswap-v3-npm-source-block.sh \
  /tmp/uniswap-v3-npm-source-block
```

Then build the unchanged writer and the standalone source WASM:

```sh
cargo +1.79.0 build --locked --target wasm32-unknown-unknown --release \
  --manifest-path /tmp/uniswap-v3-npm-source-block/Cargo.toml
cargo +1.79.0 build --locked --target wasm32-unknown-unknown --release \
  --manifest-path /tmp/uniswap-v3-npm-source-block/npm-source-block-runtime/Cargo.toml
```

Repository checks:

```sh
python3 scripts/verify-uniswap-v3-npm-source-block.py
python3 -m unittest scripts.tests.test_uniswap_v3_npm_source_block
```

This remains diagnostic source infrastructure. It does not make any V3 segment
backfill-ready or production-ready.
