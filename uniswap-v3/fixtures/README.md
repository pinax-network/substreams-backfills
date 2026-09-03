# Uniswap V3 block fixtures

Executable evidence for issue #113: real Firehose blocks at the points where
the deployed Uniswap V3 mapping first exercises each handler, plus the module
outputs the frozen Substreams source produced for those blocks.

## Blocks (`blocks.lock.json`, release `block-fixtures-v2`)

| Network | Block | Why |
|---|---:|---|
| mainnet | 12369621 | Factory deployment and module `initialBlock` |
| mainnet | 12369739 | First `PoolCreated` (UNI/WETH `0x1d42064f…`), first `Mint`, first NPM `IncreaseLiquidity` and `Transfer` |
| mainnet | 12369879 | First `Swap` and fee-growth update |
| mainnet | 12370523 | First `Burn`, NPM `DecreaseLiquidity` and `Collect` |
| mainnet | 13605860, 13605861 | Graft boundary of the current deployment's first ancestor and its successor |
| mainnet | 19470000, 19470001 | Graft boundary of the current deployment (`QmTZ8ejX…`) and its successor |

No `Flash` event occurs in the first 2,500 blocks after the factory; the Flash
fixture is still to be located. Base fixtures follow once the chain-config
package runs for Base.

The event blocks were found by streaming `map_extract_data_types` from the
factory block over 2,500 blocks against `eth.substreams.pinax.network:443`
with the frozen source built at Rust 1.79 (`substreams_uniswap_v3.wasm`,
1,012,707 bytes). Each fixture is the `sf.ethereum.type.v2.Block` protobuf as
served by `eth.firehose.pinax.network:443` (`firecore tools firehose-client
… -o bytes`, final blocks only), 0.3 to 1.2 MB each, 6.2 MB total, so they are
content-addressed release assets like the large contracts
(`docs/evidence-assets.md`). Hydrate with:

```sh
cargo xtask evidence fetch --lock uniswap-v3/fixtures/blocks.lock.json
cargo xtask fixtures check          # offline: lock, block identity, goldens
```

### One block per file (`block-fixtures-v2`)

`firecore tools firehose-client … B:B+1` treats the range as inclusive and
returns two blocks, and the original capture appended both to one file. Every
asset on the superseded `block-fixtures-v1` therefore held two concatenated
`sf.ethereum.type.v2.Block` messages, block `B` followed by block `B+1`.
`prost` does not reject that: it merges the two messages, so a decoded "block
12369621" also carried block 12369622's transaction traces, logs and balance
changes, with the scalar header fields overwritten by the second block. The
goldens are unaffected — they came from `substreams run`, not from this
capture.

`block-fixtures-v2` is, for every path, exactly the first message of the
corresponding v1 asset: the same bytes truncated at the boundary, never
re-fetched or re-encoded. `block-fixtures-v1` stays published and unmodified;
the lock simply no longer points at it.

| Block | v1 bytes | v2 bytes | v1 held |
|---|---:|---:|---|
| 12369621 | 1133655 | 500916 | 12369621 then 12369622 |
| 12369739 | 1597522 | 567133 | 12369739 then 12369740 |
| 12369879 | 1481115 | 627205 | 12369879 then 12369880 |
| 12370523 | 2180070 | 993546 | 12370523 then 12370524 |
| 13605860 | 1486461 | 1208197 | 13605860 then 13605861 |
| 13605861 | 2044607 | 278264 | 13605861 then 13605862 |
| 19470000 | 2041903 | 1031733 | 19470000 then 19470001 |
| 19470001 | 1672567 | 1010170 | 19470001 then 19470002 |

The boundary is found by `cargo xtask fixtures normalize`. It walks the
top-level protobuf fields of a fixture, reading each tag's field number, wire
type and length. Protobuf writes a message's fields in ascending field-number
order, and consecutive entries of a repeated field keep the same number, so
the first field whose number is **lower** than its predecessor's begins the
next message. The command refuses to write unless the first message is the
block the path names, the second is that block's successor, the second runs
exactly to the end of the buffer, and the truncated bytes stand alone as a
single block with a 32-byte hash. `--write` truncates; without it the command
only prints the old and new lengths and SHA-256s. Two of the pairs check each
other: the second message of `13605860.pb` is byte-identical to the whole of
the normalized `13605861.pb`, and likewise for `19470000`/`19470001`.

`cargo xtask fixtures check` now rejects any fixture that is not exactly one
`Block` message, so a two-message capture cannot return unnoticed.

## Goldens (`goldens/mainnet/<block>/<module>.jsonl`)

`substreams run … <module> -s <block> -t +1 -o jsonl` output for
`map_pools_created`, `map_extract_data_types`, and `graph_out` at the four
early blocks, captured 2026-09-02 from the same endpoint and WASM. Blocks
where a module emitted nothing have no file (the CLI omits empty outputs). The
graft-boundary blocks have `map_pools_created` goldens only: their store
modules would need every block since 12369621 backprocessed, which the
endpoint does not cache for this package.

Goldens are recorded observations of the frozen source, not parity evidence
against the deployed subgraph (#114) and not BlockChanges (#116).

## What can and cannot run hermetically today

The frozen source's module functions are native Rust and could be called from
a test crate the way `uniswap-v3/contract-tests` calls `db.rs`, but two host
boundaries make that unfaithful outside the Substreams runtime:

- `substreams` 0.5 store reads (`state::get_at` and friends) compile to
  `None` on non-wasm targets, so every store-fed module silently sees empty
  stores;
- `substreams-ethereum` 0.9 `eth_call` is `unimplemented!()` on non-wasm
  targets, and `map_pools_created` performs ERC-20 metadata calls for every
  pool.

`cargo xtask fixtures check` therefore verifies the fixtures themselves
(hydration digests, exactly one `Block` message per file, block number and
hash length inside each protobuf, golden shape and block/module identity).
Running the mapping WASM against these blocks hermetically needs a host that
supplies stores and recorded RPC responses; that is the next #113 step (a
small `wasmtime` host with an in-memory store and an RPC cassette recorded
from the same capture), and it is also the foundation #116 needs to emit
BlockChanges from the same execution.
