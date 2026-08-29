# Uniswap V3 host-only Position reducer v1

This overlay adds a pure, sequential `Position`/`PositionSnapshot` reducer on
top of the diagnostic writer runtime. It is a host-testable semantics tranche,
not a Substreams handler: it adds no store, RPC, database access, entity output,
manifest module, consumer, or path into `graph_out`.
The module is excluded when targeting `wasm32`, so the release WASM and both
packages remain byte-identical to the pinned diagnostic writer runtime.

## Supported construction

The only supported materialization order is:

1. the frozen `uniswap-v3/source/` import;
2. the versioned ChainConfig overlay;
3. the exact diagnostic writer-runtime overlay bound by SHA-256
   `765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca`;
4. `runtime.patch`, `src/position_reducer.rs`, and
   `position-reducer-v1.json` from this directory.

Materialize only into an empty directory outside the repository:

```sh
PYTHON=python3 ./scripts/materialize-uniswap-v3-position-reducer.sh /tmp/uniswap-v3-position-reducer
```

The reducer consumes a validated `WriterEvents` envelope plus an immutable
`BlockContext` containing the block number, timestamp, and optional hash. The
number must match the envelope. Every snapshot uses the exact context timestamp.
Its `ReducerInputs` trait supplies hermetic post-block `positions`/`getPool`
results and ordinal-visible Token entity reads; it does not perform those calls.

## State-transition boundary

Events are processed in strictly increasing global ordinal and block-log-index
order. Each event mutates a clone of the ordinal-current state. Accepted events
commit both Position and Snapshot. Drops and nonfatal errors discard only their
event scratch. On the first fatal legacy error, the reducer returns the exact
input Position/Snapshot state as a shortcut for the final persisted user-entity
projection. Its outcomes cover only the consumed event prefix and report how
many later writer events were omitted.

That shortcut is not a Graph execution stop or a complete Graph trace. The
exact execution-order contract at `../execution-order/v1/contract.json` (raw
SHA-256 `241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2`)
records that Graph continues remaining runnable triggers and breadth-first
dynamic stages after the first fatal handler error. A later retryable failure
may still abort before the block transaction; otherwise user modifications are
filtered from PoI while persisted data sources and deterministic errors pass,
the failed block pointer advances, and the deployment stops. Consequently this
reducer cannot authorize Graph block or checkpoint success.

Graph-call results are cached only inside one reducer invocation. The cache key
contains the target address and exact decoded calldata, and the provider receives
the exact block pointer. Token reads are never cached across ordinals. A newly
constructed identity stays provisional until its handler commits, so an excluded
pool, missing token, or reverted identity lookup cannot leak a Position.

All four NPM event types save a snapshot. Its id is `tokenId#block`; the last
accepted event for a position in a block overwrites that snapshot. A Position's
`transaction` remains its first persisted identity-creation transaction, while
the shared Snapshot records the last accepted event transaction. On-chain
liquidity and owed-token fields returned by `positions` are deliberately ignored,
matching `getPosition`; only identity and fee-growth fields are represented.

`getPosition` and snapshot creation in the deployed mappings also call
`loadTransaction`. This tranche carries transaction ids but intentionally does
not reproduce Transaction entity side effects. Consequently, early-return cases
are assertions about Position/Snapshot scratch only, not claims that a future
full handler has zero Transaction writes. This tranche does not complete the
full NPM-handler or issue #37 runtime checkbox.

## Exact profile behavior

- Mainnet root adds amount0/amount1 to their own fee fields and loads both Tokens.
- QmRv/Qmebr overwrites fee0 with ordinal-current fee1 plus amount1, leaves fee1
  unchanged, and still loads/converts both Tokens.
- The three middle mainnet profiles accumulate no Collect amounts and load no
  Tokens.
- Base root adds amount0 to both prior fee fields and loads only token0. Missing
  token1 does not fail Collect.
- Current mainnet/Base add amount0 to both fields when token0 exists. Missing
  token0 preserves amounts but still refreshes/saves/snapshots; Increase and
  Decrease drop when either Token is missing.

Increase and Decrease add/subtract liquidity and convert both token amounts.
Decrease may make liquidity negative. Increase, Decrease, and Collect refresh
fee growth with block-scoped `try_positions`; reversion preserves prior fee
growth. The excluded pool applies to those three handlers, never Transfer. The
14,317,993 guard runs before all calls only where the profile says it is
effective: Base root is guarded and mainnet QmZe is not.

The model rejects malformed writer envelopes before applying a segment's
nonfatal policy. ABI uint strings must be canonical decimal uint256 values, so
no floating-point conversion occurs. Decimal construction and each arithmetic
operation reproduce graph-node v0.44's 34-significant-digit normalization.

## Verification

```sh
python3 scripts/verify-uniswap-v3-position-reducer.py
python3 -m unittest scripts.tests.test_uniswap_v3_position_reducer
```

The materialized crate remains on Rust 1.79.0 and the writer runtime's exact
dependency pins. Its manifests retain the same 23 modules, consumerless writer,
unchanged `graph_out`, protobuf descriptors, and package graph. Every readiness,
parity, population, backfill, and production gate remains false.
