# Uniswap V3 NPM observation plan

This repository-only host layer builds a canonical, conservative request
closure before the joint NPM reducer can run. It starts from the complete
validated `NpmSourceBlock`, a payload-free gated block call scope, and an
immutable projection of block-start Position state. `PossibleReorg` and
`Unknown` call scopes fail before a planning phase is created.

Planning is deliberately staged. The first phase deduplicates every
`positions(manager, tokenId)` key across the full WriterEvents envelope. Only
after every Position result is resolved does the second phase derive
`getPool(factory, token0, token1, fee)` and ordinal-scoped Token keys using the
bound segment profile. Both phases scan events after a would-be fatal reducer
prefix. Keys are sorted, reasons and contributing ordinals are canonical.
Position and Pool multiplicity is exactly one per unique block-scoped cache
key; Token multiplicity is the maximum role count for each ordinal/address
key. Reducer consumption is audited against those exact maxima.

The final preflight accepts a resolved frame only when its Position, Pool, and
Token key sets exactly equal the plan. The call scope and every observation
must pass the transient resolution gate. Resolution status and provider error
payloads remain transient and never enter either protobuf. The certified
reducer entrypoint accepts only a private-field `PreflightedResolvedFrame`,
rechecks the source and planning-state commitments, and proves consumed keys
are a bounded subset of the plan.

This is not an integrated executor. It adds no provider, RPC, database,
Substreams handler, Store, manifest module, `graph_out`, checkpoint, or Graph
block authority. It does not model post-fatal Graph execution, Factory/Pool
combined scheduling, dynamic data-source stages, EntityChanges/BlockChanges,
continuity, physical parity, PoI, backfill, or production readiness. All of
those gates remain false.

Run:

```bash
python3 scripts/verify-uniswap-v3-npm-observation-plan.py
python3 -m unittest scripts.tests.test_uniswap_v3_npm_observation_plan
./scripts/materialize-uniswap-v3-npm-observation-plan.sh /tmp/uniswap-v3-npm-observation-plan
```

The materializer starts from the pinned resolved-input runtime, removes only
its superseded integration harness, and adds the plan semantic file, checked-in
protobuf binding, planner, and combined adversarial harness. It leaves
`src/lib.rs`, writer source, runtime descriptors, manifests, WASM, and packages
unchanged.
