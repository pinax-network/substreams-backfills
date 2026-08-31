# Uniswap V3 NPM Transfer semantics v2

This offline certificate closes the path-qualified static schema-API effect
surface of `NonfungiblePositionManager.handleTransfer` for all eight retained
mainnet and Base segment bindings. Six unique NPM mapping WASMs are regenerated
with WABT 1.0.35. The verifier binds every reachable function body, direct
call, memory write, generic or generated setter, constructor, unset, store
read/write/remove site, Ethereum call, and closed indirect-call target.

Every segment has exactly 299 schema outcomes:

- 38 classified stored targets: all 17 `Position` fields, all 16
  `PositionSnapshot` fields, and five `Transaction` fields;
- zero saved-target stored fields without a reachable setter path;
- 13 `@derivedFrom` query fields without a direct store transition; and
- 248 stored fields outside the Transfer store-target closure.

The required-absence overlay contains 33 outcomes per segment: all 11
`Collect`, 12 `Flash`, and 10 `TickHourData` fields. Across eight bindings that
is 2,392 outcomes: 304 classified stored, zero saved-no-setter, 104 derived,
1,984 outside, and 264 required-absence overlays. All 28 segment pairs contain
recursive semantic and provenance diffs.

## Physical and semantic denominators

Physical sites are not treated as semantic authority. The six-WASM physical
closure contains 454 reachable bodies, 2,006 direct calls, a 490 summed
distinct-target denominator, 1,270 Wasm memory writes, 166 physical generic
`TypedMap#set` sites, 116 named generated-setter invocations, 12 `store.get`
sites, 18 `store.set` sites, and two `call_indirect` instructions. Weighted by
the eight segment bindings, those counts are 628, 2,654, 676, 1,614, 210, 174,
16, 24, and two respectively.

Each mapping has 39 lexical semantic field invocations over 38 distinct fields.
The maximum new-position path expands to 44 invocations because
`loadTransaction` runs once during Position creation and again during snapshot
creation. Legacy code uses 29 named setter invocations and 22 physical generic
setter bodies/sites; current code uses zero named setters and 39 direct generic
set sites. Zero named setters therefore never means zero writes. Legacy IDs
are constructor-carried; current IDs are explicit generic field sets.

## Path contract

An accepted existing Position path performs no contract call. It writes
`Position.owner`, saves Position, constructs the 16-field snapshot, runs the
five-field Transaction helper, saves Transaction, and saves the snapshot. Its
store order is `Position`, `Transaction`, `PositionSnapshot`. The other 16
stored Position fields have no setter before the Position save. They are not
called preserved, unchanged, value-stable, or persisted.

An accepted new Position path first observes a missing Position, completes
`try_positions`, completes the non-try Factory `getPool`, classifies all 17
Position fields, invokes and saves Transaction, overwrites owner from the
Transfer event, saves Position, classifies all 16 snapshot fields, invokes and
saves Transaction again, then saves the snapshot. Its store order is
`Transaction`, `Position`, `Transaction`, `PositionSnapshot`.

A reverted `try_positions` returns normally without a schema field invocation
or `store.set`. A missing result from non-try Factory `getPool` is fatal before
any schema constructor, setter, or store write. Only that pre-fatal prefix is
bound; post-fatal execution and rollback remain unproved. Transfer contains no
excluded-pool or historical-block branch on the bound handler paths. This is a
path statement, not a claim that those literals are globally absent elsewhere
in the module.

The six relation-field authorities are also explicit: new-only
`Position.pool`, `token0`, `token1`, `tickLower`, and `tickUpper`, plus
accepted-path `PositionSnapshot.pool`. The contract binds the receiver, decoded
field key, source call/getter chain, and matching entity save. It does not
promote host-returned values, address conversion, number/string formatting,
store-read contents, or alias semantics.

API 0.0.4 structurally routes the event transaction gas-limit getter result to
`Transaction.gasUsed`; API 0.0.7 routes the result of `BigInt.fromI32` with a
literal zero. This is a call-shape distinction only, not a numeric-value claim.

## Boundary

Imported value, numeric, string, address, call, store, persistence, rollback,
post-fatal, VID, PoI, population, history, last-writer, runtime identity,
continuity, oracle, parity, package, checkpoint, backfill, deployment,
production, and readiness gates remain false. This static slice completes no
checkbox in issue #37 or #38.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-npm-transfer-v2.py
python3 -m unittest scripts.tests.test_uniswap_v3_npm_transfer_v2
```

Deterministic regeneration uses:

```bash
python3 scripts/verify-uniswap-v3-npm-transfer-v2.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for exact roots and identities.
