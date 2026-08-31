# Uniswap V3 Pool Burn schema-API matrix v2

This additive certificate publishes a conservative, complete, path-qualified
static schema-API effect matrix for `Pool.handleBurn` across all eight retained
Uniswap V3 Pool mappings. It recomputes Pool Burn v1, the shared Pool runtime,
segment-field semantics v2, and the direct 299-field GraphQL schema. It does
not use Factory static v2, Pool Initialize v2, or Pool Flash v2 as semantic
inputs.

The matrix is deliberately narrower than complete Burn semantics. It says
which retained schema setter paths can be followed by which matching entity
store on normal continuation. It does not assign numeric meaning to imported
operations, prove field values or preservation, model Graph store behavior, or
describe one concrete execution trace.

## Complete outcome matrix

Every segment has exactly 299 mutually exclusive field outcomes, for 2,392
total outcomes:

| Path-qualified category | Per segment | Eight segments |
|---|---:|---:|
| selected Pool old-minus-converted-Burn-amount setter before the same Pool save | 2 | 16 |
| other stored field with a reachable setter path before its matching entity store | 122 | 976 |
| stored field on a reachable entity store without a reachable schema setter path | 63 | 504 |
| derived field with a reachable child-association setter path | 5 | 40 |
| other derived field without a direct or child-association setter path | 8 | 64 |
| stored field outside the Burn Graph-store closure | 99 | 792 |

The independent required-absence overlay covers 33 fields per segment, or 264
outcomes: all 11 `Collect`, 12 `Flash`, and 10 `TickHourData` fields. An overlay
does not replace the mutually exclusive path category.

The five derived child associations are `Pool.burns`, `Pool.poolDayData`,
`Pool.poolHourData`, `Token.tokenDayData`, and `Transaction.burns`. Actual Graph
query visibility and relation materialization semantics remain unproved.

The 63 stored fields with a reachable matching entity store but no reachable
schema setter are described only by that static absence. The contract never
calls those fields preserved, unchanged, value-exact, or persisted.

## Closed ledgers

For each mapping, the verifier closes four distinct setter ledgers:

- 147 lexical schema-field invocations;
- 151 physical-site-to-invocation edges, including four nullable branch
  alternatives;
- 195 handler-expanded setter paths after exact helper multiplicity; and
- 124 unique stored setter fields.

It also closes 12 physical Graph-store targets and 17 handler-expanded store
paths per mapping. Across all mappings this is 1,176 lexical invocations, 1,208
site edges, 1,560 expanded setter paths, 96 physical stores, and 136 expanded
store paths. The exact store targets are `Burn`, `Factory`, `Pool`,
`PoolDayData`, `PoolHourData`, `Tick`, `TickDayData`, `Token`, `TokenDayData`,
`TokenHourData`, `Transaction`, and `UniswapDayData`.

Physical and semantic ledgers must not be conflated. Each modern mapping has
149 physical `TypedMap#set` sites and each legacy mapping has 54, for 622 total.
The Pool Burn v1 residual counts happen to be 147 for modern and 52 for legacy;
the modern number `147` is not the 147 lexical schema-field invocations. A
deduplicated WAT symbol such as `Mint#set` is not entity authority.

The full reachable inventory is 1,240 function bodies, 7,084 direct calls,
2,048 direct memory writes, and two modern indirect calls. Every physical
setter site, lexical invocation, site edge, expanded path, receiver context,
field key, store target, helper multiplicity, and modern guard boundary is
classified; the unclassified site count is zero.

## Ordering and guards

The two selected fields retain Pool Burn v1's structural
old-minus-converted-amount flow and both selected setters precede the same
loaded Pool's save. All other categories claim only setter-before-matching-store
call order on a retained branch that continues normally.

For the two modern mappings, all handler effect paths are inside the two-Token
presence guard. Tick and TickDay effects additionally require the nested
two-Tick path. The six legacy mappings are limited to potential normal-
continuation paths; missing-entity behavior is not generalized from the modern
shape.

Imported numeric and comparator meaning, contract-call values and errors,
payload or heap aliases, later overwrites, Graph store visibility, persistence,
rollback, post-fatal execution, historical branch outcomes, and complete
entity history all remain false. So do scheduler, runtime population, output,
Store, package, source-package identity, continuity, logical/physical/PoI
parity, checkpoint, backfill, deployment, production, and readiness gates.
This contributes a bounded static Burn slice to issue #38 but completes no
issue checkbox.

```console
python3 scripts/verify-uniswap-v3-pool-burn-v2.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_burn_v2
```

Intentional byte-identical regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-burn-v2.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for the exact authority chain.
