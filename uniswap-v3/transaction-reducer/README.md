# Uniswap V3 host-only NPM Transaction reducer v1

This overlay models only the `Transaction` side effects reached from the four
NonfungiblePositionManager handlers. It is a pure, sequential, host-testable
diagnostic. It adds no Substreams handler, store, RPC or database access,
`EntityChanges`, consumer, or path into `graph_out`. The module is excluded from
the runtime library and is compiled only by a host integration-test harness, so
the shared diagnostic WASM and both packages remain byte-identical to writer
runtime v1.

## Exact input boundary

The reducer consumes the validated eight-segment `WriterEvents` envelope plus a
host-only block context, one transaction-metadata record per referenced hash,
and one hermetic event control per ordinal. Timestamp, transaction gas limit,
and gas price are deliberately added only to this diagnostic input model; the
pinned writer protobuf and package descriptors do not change. Receipt or actual
execution gas used is not an input to this reducer.

Transaction ids are exact lowercase `0x` plus 64 hexadecimal digits.
`loadTransaction` is modeled as an unconditional upsert: every call overwrites
`blockNumber`, `timestamp`, `gasUsed`, and `gasPrice`, even when the row already
exists. In Graph Node v0.44.0, API 0.0.4 selects
`AscEthereumTransaction_0_0_2`. Its mapping property
`event.transaction.gasUsed` occupies transaction-field offset 20, whose host
field is `gas_limit` and whose value comes from the transaction gas-limit
accessor. Legacy segments therefore store the transaction gas limit under the
entity field `gasUsed`; they do not store receipt gas used. API 0.0.7 mappings
hardcode zero. Both generations retain the supplied gas price. The adversarial
fixture supplies different transaction gas-limit and receipt/actual-gas values
and rejects both legacy receipt-gas use and legacy zero.

The gas-specific primary-source binding is Graph Node commit
`77823b5a7adc4eac4abf03202c8dd7cb00dea31d`, tree
`1f372b47e4de659ddbf503cdbc31ebe4d54df239`. It remains a reference model,
not proof of the target Graph Node runtime binary.

For a newly constructed Position identity, `getPosition` calls
`loadTransaction` once. Every accepted handler then calls it again while saving
the PositionSnapshot. An accepted new Position therefore makes two helper
calls, while an accepted existing Position makes one. The Position relation is
the first successful identity-creation transaction; the same-block snapshot is
overwritten by the last accepted event and relates to that event's transaction.

The first helper save precedes the ignored-pool return and modern
Increase/Decrease missing-token return. Those successful early returns can
therefore leave an orphan Transaction when the Position identity was new.
Deterministic errors are different at the entity-state boundary modeled here:
the failing handler's staged Transaction changes are discarded. Historical
mainnet segments fail the block; current mainnet and both Base segments discard
only the failing handler's entity-state scratch and continue. The
block-14,317,993 Base-root Increase/Decrease guard runs before identity
construction and therefore before any helper call.

That state discard is not a physical rollback. The shared
[`execution-order/v1`](../execution-order/README.md) supplement binds the exact
Graph Node ordering, VID, PoI, and failure evidence under raw SHA-256
`241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2`.
It proves that a failed handler can consume VIDs and remain represented in PoI
and error channels even though its entity-state scratch is discarded. This
reducer reports attempted helper calls but does not reproduce those physical
side effects.

## Explicit limits

The event controls are hermetic substitutes for already-audited Position
lookup, ignored-pool, Token availability, and host-failure outcomes; they do not
perform or claim live calls. This tranche does not reproduce complete Position,
PositionSnapshot, or NPM field semantics. Pool `handleSwap`, `handleMint`, and
`handleBurn` also write the shared Transaction entity; those writers remain
unaudited here. As the bound execution-order supplement records, a Pool data
source created by the Factory is processed in a later dynamic-data-source stage
after all initial static and existing-data-source triggers for that block.
Therefore raw global log order is not a complete NPM-versus-new-Pool execution
order. Final cross-component last-writer, physical VID, and PoI/error-stream
parity are all explicitly uncertified.

All runtime, parity, population, continuity, backfill, and production gates
remain false.

## Verification

```sh
python3 scripts/verify-uniswap-v3-transaction-reducer.py
python3 -m unittest scripts.tests.test_uniswap_v3_transaction_reducer
PYTHON=python3 ./scripts/materialize-uniswap-v3-transaction-reducer.sh /tmp/uniswap-v3-transaction-reducer
cargo +1.79.0 test --locked --manifest-path /tmp/uniswap-v3-transaction-reducer/Cargo.toml
```

Materialization is supported only into an empty directory outside this
repository, after the frozen import, ChainConfig, and exact writer runtime
contract SHA-256
`765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca`.
