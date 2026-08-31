# Uniswap V3 all-handlers v1 certificate

This directory contains the provisional complete, conservative static
schema-API normalization for all ten retained Uniswap V3 handlers:

- Factory `handlePoolCreated`;
- Pool `handleInitialize`, `handleFlash`, `handleBurn`, `handleMint`, and
  `handleSwap`;
- NonfungiblePositionManager `handleTransfer`, `handleCollect`,
  `handleIncreaseLiquidity`, and `handleDecreaseLiquidity`.

The matrix covers eight mainnet/Base ancestry segments and reconstructs the
299-field schema directly from all three retained GraphQL artifacts. Its exact
denominator is therefore `10 * 8 * 299 = 23,920` handler/segment/field cells.
This is a static certificate, not an integrated runtime or a backfill.

## Provisional publication status

The implementation base is local Liquidity candidate
`0b66c2403e9440ecce9f7f48d70e9eec85d6b382`, tree
`6e76693a346efa8a75bd49728866673391fd8b3e`. Every selected component is an
ancestor of that base and every selected predecessor edge matches. The
verifier loads exact pinned Git objects and fails closed when any object,
contract, verifier, test, tree, parent, ancestry edge, or digest is unavailable
or changed.

Burn, Mint, and Swap are canonical. This candidate is not the canonical
publication because corrected Transfer, Collect, and Liquidity remain local
provisional roots. They are linearly composed here and must land canonically
before the aggregate is regenerated one final time. The contract keeps
`all_component_roots_canonical_and_ancestral=false`,
`canonical_publication_root_complete=false`, and
`component_ci_validation_complete=false`.

## Exact normalized matrix

The four categories are mutually exclusive conservative normalization buckets.
They preserve each component's exact native category without asserting a
uniform matching Store path. “Outside certified effect scope” does not widen
Factory #77 into a complete store-closure claim.

| Handler | Setter/direct-write authority | Component nonsetter classification | Outside certified scope | Derived | Total |
|---|---:|---:|---:|---:|---:|
| Factory | 472 | 8 | 1,808 | 104 | 2,392 |
| Initialize | 342 | 209 | 1,737 | 104 | 2,392 |
| Flash | 16 | 216 | 2,056 | 104 | 2,392 |
| Burn | 992 | 504 | 792 | 104 | 2,392 |
| Mint | 1,136 | 368 | 784 | 104 | 2,392 |
| Swap | 1,152 | 360 | 776 | 104 | 2,392 |
| Transfer | 304 | 0 | 1,984 | 104 | 2,392 |
| Collect | 304 | 0 | 1,984 | 104 | 2,392 |
| Increase | 304 | 0 | 1,984 | 104 | 2,392 |
| Decrease | 304 | 0 | 1,984 | 104 | 2,392 |
| **Total** | **5,326** | **1,665** | **15,889** | **1,040** | **23,920** |

Five Initialize no-Pool-save segments produce aggregate vectors
`665/198/1997/130`. Three save segments produce
`667/225/1968/130`. A no-setter record never means preserved, unchanged,
value-stable, visible, or persisted.

For repaired Swap, the first bucket means exact setter receiver flow plus a
lexically later same-group store whose receiver has an overlapping finite-CFG
origin set. It does not prove a common execution path, branch correlation, or
receiver must-alias. The aggregate keeps those three gates false.

Factory is independently projected onto the direct catalog as 59 written
fields, handler-local required absence of `Pool.tick`, 226 stored fields
outside #77's exact 60-field contract, and 13 derived fields. The 226 fields
are not claimed to be outside Factory runtime store reachability.

## Overlays are not unions

Required-absence evidence has three different denominators:

- 1,424 handler-relative occurrences, or 178 per segment;
- 34 distinct handler-relative fields per segment, including Factory-local
  `Pool.tick`;
- 33 population-required-absence fields per segment: Collect 11, Flash 12,
  and TickHourData 10.

`Pool.tick` is not population-required-absent because Initialize can write it.
No required-nonempty output is certified and runtime population remains false.

There are 1,040 handler-relative derived cells. Of these, 136 carry a child
association across Initialize/Burn/Mint/Swap; their distinct union is nine
schema fields per segment. NPM stored-relation authority has 264
handler-relative occurrences but only nine distinct fields per segment.
Neither ledger proves query visibility, conversion values, aliases, history,
or last-writer behavior.

## Shared setter authority and order boundary

Burn, Mint, Swap, Transfer, Collect, Increase, and Decrease all have setter
authority for the five Transaction fields `id`, `blockNumber`, `timestamp`,
`gasUsed`, and `gasPrice`. Corrected Collect, Increase, and Decrease bind every
completed `loadTransaction` hit or miss to the four common setters and one
Transaction save; a miss additionally supplies `id`. A new Position path may
invoke the helper twice. Static WAT does not prove that an earlier `store.set`
is visible to the later `store.get`, so the two reads remain independently
classified and Transaction last-writer behavior remains unknown.

All eight raw manifests declare Factory handlers first, then NPM Increase,
Decrease, Collect, Transfer, then Pool-template Initialize, Swap, Mint, Burn,
Flash. This is declaration order, not a globally flattened category schedule.
The Graph Node v0.44 reference certificate binds stage-local sorting and
breadth-first dynamic-data-source stages that refetch the full creation block.
It does not prove target runtime identity, Store visibility, persistence,
rollback, or last writer.

The certificate retains 28 recursive segment-pair diffs for each handler
(280), 28 aggregate diffs, and eight within-segment Increase-versus-Decrease
diffs. Fifteen aggregate pairs cross the Initialize save split; thirteen differ
only through segment identity or provenance at the normalized count level.

## Verification

The default command regenerates every pinned component verifier in an isolated
temporary archive before checking the aggregate:

```bash
python3 scripts/verify-uniswap-v3-all-handlers-v1.py \
  --wasm2wat /path/to/wasm2wat
python3 -m unittest scripts.tests.test_uniswap_v3_all_handlers_v1
```

`--skip-component-regeneration` is only for focused mutation tests or a
post-full detached byte check. It still verifies every pinned Git object and
digest, but it is not the full publication gate.

No issue #37 or #38 checkbox is completed and neither issue is closed. See
[eligibility](docs/eligibility.md) for the fail-closed boundary and
[provenance](docs/provenance.md) for exact component and source roots.
