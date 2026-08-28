# Uniswap V3 host-only Pool Flash reducer v1

This overlay adds a pure, sequential Pool Flash reducer on top of the
diagnostic writer runtime. It is a host-testable semantics tranche, not a
Substreams handler: it adds no store, RPC implementation, database access,
entity encoder, manifest module, consumer, or path into `graph_out`. The module
is excluded when targeting `wasm32`, so the writer WASM and both packages remain
byte-identical to the pinned diagnostic writer runtime.

Its execution boundary is pinned to the Graph Node v0.44 reference supplement
at `uniswap-v3/execution-order/v1/contract.json` (raw SHA-256
`241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2`).
That binding prevents this diagnostic reducer from being mistaken for an
implementation of the supplement.

## Supported construction

The only supported materialization order is:

1. the frozen `uniswap-v3/source/` import;
2. the versioned ChainConfig overlay;
3. the exact diagnostic writer-runtime overlay bound by SHA-256
   `765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca`;
4. `runtime.patch`, `src/flash_reducer.rs`, and `flash-reducer-v1.json`
   from this directory.

Materialize only into an empty directory outside the repository:

```sh
PYTHON=python3 ./scripts/materialize-uniswap-v3-flash-reducer.sh /tmp/uniswap-v3-flash-reducer
```

## State-transition boundary

The reducer consumes an immutable block context and a digest-bound diagnostic
envelope of PoolCreated/Flash observations. Within that supplied envelope it
requires increasing ordinals and block log indexes. Its creation-ordinal
membership rule—an earlier supplied PoolCreated marks membership for a later
supplied Flash—is only an input convention for this host reducer.

This convention does **not** model Graph Node's breadth-first dynamic-datasource
stages, whole-block replay, or block-scoped activation. In particular, it must
not be interpreted as a global cross-stage ordering, a creation-log ordinal
gate, a same-path proof, or a cross-component ordering claim. The
Factory-rejected pool `0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248`
never enters the diagnostic membership set.

For each Flash marked active by that diagnostic membership convention, the
reducer loads the Pool by the event address and calls that same address at the
exact post-block pointer. It sends selector `f3058399` first and, only after a
successful exact 32-byte uint256 decode, selector `46141319`. Both returned
fee-growth values are committed together as one Pool update. A missing Pool or
first-call failure attempts no call2; a call2 failure discards call1 scratch.
Zero is a valid decoded value but is never substituted for failure. Calls are
not batched, deduplicated, or cached, including repeated Flash events for the
same Pool.

The first five mainnet segments treat a reducer error as fatal for this
diagnostic block: only its Pool and membership state rolls back. Current
mainnet and both Base segments discard the failing Flash scratch and continue
through the supplied diagnostic envelope. These rules do not represent Graph
Node VID allocation, PoI events, persisted dynamic data sources, deterministic
error streams, transaction acceptance, or physical database rollback. The
Flash event fields are deliberately ignored. The NPM block/pool guards and the
swap-only pool guard do not apply to Flash.

The output API can represent only Pool updates. It has no Flash, Transaction,
or aggregate-row type, and it never synthesizes such rows. PoolCreated is
modeled only for the diagnostic membership convention; complete Factory/Pool
construction is outside this tranche.

## Verification

```sh
python3 scripts/verify-uniswap-v3-flash-reducer.py
python3 -m unittest scripts.tests.test_uniswap_v3_flash_reducer
```

The materialized crate stays on Rust 1.79.0 and the writer runtime's exact
dependency pins. Its manifests retain the consumerless 23-module writer graph,
unchanged `graph_out`, protobuf descriptors, and single shared WASM. Trigger/RPC
binding, Graph Node dynamic-datasource stage order, combined handler order,
runtime consumption of the execution-order contract, same-path/cross-component
order proof, complete Pool semantics, runtime population, boundary continuity,
logical/physical/PoI parity, production, and backfill gates all remain false.
