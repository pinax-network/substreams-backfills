# Uniswap V3 host-only joint NPM reducer v1

This overlay models the `Transaction`, `Position`, and `PositionSnapshot`
entity-state effects of the four NonfungiblePositionManager handlers in one
ordered event loop. It is a pure host diagnostic: it adds no Substreams
handler, Store, live call, RPC or database access, `EntityChanges`, consumer,
or path into `graph_out`. The source is compiled only by an integration-test
harness, so the diagnostic writer WASM, protobuf descriptors, 23-module graph,
and both packages remain byte-identical to writer runtime v1.

## Supported construction

The materializer starts from the exact writer runtime contract SHA-256
`765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca`
and then copies only this reducer's semantic contract, host source, and test
harness. It also binds these already reviewed contracts:

- Position reducer runtime
  `3099c3f08208cf46ce68df3433dd5b757436a3a7e315daec3f0d96bf242185c1`;
- Transaction reducer runtime
  `c9f355d141720dfda4347b4ef6cb5350a96803db31cf4770f035b5efca9def7f`;
- eight-segment matrix
  `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161`;
- Graph Node execution-order supplement
  `241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2`.

Materialize only into an empty directory outside the repository:

```sh
PYTHON=python3 ./scripts/materialize-uniswap-v3-npm-handler-reducer.sh \
  /tmp/uniswap-v3-npm-handler-reducer
```

## Joint transition boundary

The reducer validates the writer envelope, exact transaction-metadata set, and
one failure-injection control per ordinal before it touches the hermetic call
provider. Position lookup, pool exclusion, Token visibility, and fee refresh
are all derived from that same provider and event scratch. It never runs the
standalone Position and Transaction reducers and unions their results.

Each event starts with one clone of the ordinal-current Transaction, Position,
and Snapshot state. The successful attempted-save order is:

- new Position: identity `Transaction`, `Position`, snapshot `Transaction`,
  `PositionSnapshot`;
- existing Position: `Position`, snapshot `Transaction`, `PositionSnapshot`.

The diagnostic outcome retains every attempted save in its modeled event prefix,
including two identical Transaction upserts, through the first fatal error. The
fatal disposition reports the exact number of later WriterEvents this reducer
did not consume; that count does not cover later Graph triggers or dynamic
stages. It is not a complete Graph execution trace after that boundary. The
final map still has normal entity-store last-write behavior. A Position keeps its first
successfully persisted identity-creation transaction. The `tokenId#block`
Snapshot relates to the current accepted event, and the last accepted
same-position event in the modeled prefix overwrites it.

A new provisional Position is not inserted before its handler reaches
`Position.save`, but its identity helper has already called `loadTransaction`.
Consequently, an excluded-pool return or current Increase/Decrease missing-token
return commits only that Transaction. The same return for an existing Position
writes nothing. A reverted `try_positions` identity call is a normal no-write
return; a non-try identity dependency failure is deterministic.

Nonfatal deterministic errors discard the complete failing handler scratch and
continue. At the first fatal legacy error, this reducer stops consuming its
WriterEvents envelope and returns the exact block-baseline joint state as a
shortcut for the final persisted NPM user-entity projection. That is not a Graph
execution stop: Graph continues remaining runnable triggers and breadth-first
dynamic stages and may encounter a later retryable failure. Otherwise the fatal
block transaction filters user modifications to the PoI entity, passes persisted
data sources and deterministic errors, advances the failed block pointer, and
then stops the deployment.

The reducer therefore omits post-fatal handlers, dynamic stages, retryable
failures, calls, attempted saves, persisted data sources, VID allocation, PoI,
and error-stream effects. Its prefix outcomes cannot be used as a complete Graph
trace. A successful Rust `Result` means only that the diagnostic projection was
computed: neither `ModeledNpmUserEntityProjectionComplete` nor
`FatalNpmUserEntityProjection` authorizes Graph block or checkpoint success.
Only the final persisted NPM `Transaction`, `Position`, and `PositionSnapshot`
projection is asserted at this boundary.

## Exact retained behavior

The eight deployment segments execute the five NPM profiles, including all
Collect generations and the QmRv fee0-from-current-fee1 overwrite on every
event. Graph-compatible decimal128 normalization is applied after every
construction and arithmetic operation. The Base-root block `14,317,993`
Increase/Decrease guard runs before calls and writes; mainnet QmZe is
intentionally unguarded at the same height.

API 0.0.4 segments store the transaction gas limit exposed to the mapping as
`event.transaction.gasUsed`; receipt/actual gas is not an input. API 0.0.7
segments store zero. Both retain gas price. Transaction metadata remains a
host-only diagnostic input and does not alter `writer.proto` or a descriptor.

## Explicit limits

Flash, Factory/Pool cross-component scheduling, dynamic-data-source stages,
post-fatal execution, Pool Transaction writers, shared last-writer semantics,
Stores, Substreams handlers, and `graph_out` are outside this tranche. The
target Graph Node runtime identity is not bound. Runtime population,
continuity, logical, physical and PoI parity, production, backfill, and complete
NPM-handler gates all remain false.

## Verification

```sh
python3 scripts/verify-uniswap-v3-npm-handler-reducer.py
python3 -m unittest scripts.tests.test_uniswap_v3_npm_handler_reducer
```

The static verifier runs the pinned Position and Transaction verifiers and
independently checks the pinned writer-runtime, segment-matrix, and
execution-order bindings. The CI verification workflow materializes the
overlay, runs the 21 adversarial Rust tests, and proves writer WASM, packages,
descriptors, manifests, and the 23-module graph are byte-identical.
