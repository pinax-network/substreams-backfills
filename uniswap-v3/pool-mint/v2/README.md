# Uniswap V3 Pool Mint schema-API matrix v2

This additive offline certificate publishes a conservative, complete,
path-qualified static schema-API effect matrix for `Pool.handleMint` across all
eight retained Uniswap V3 Pool mappings. It directly recomputes Pool Mint v1,
Pool runtime v1, segment-field semantics v2, and the 299-field GraphQL schema.
Burn v2, Flash v2, Factory static v2, and Initialize v2 are not semantic inputs.

The certificate associates retained setter paths with later matching entity
stores only on a branch that continues normally. It does not prove field
values, preservation, imported numeric meaning, aliases, Graph persistence,
history, runtime behavior, or one concrete execution trace.

## Complete outcome matrix

Every segment has exactly 299 mutually exclusive outcomes, for 2,392 total:

| Path-qualified category | Per segment | Eight segments |
|---|---:|---:|
| stored field with a reachable setter path before its matching entity store | 142 | 1,136 |
| stored field on a reachable entity store without a reachable schema setter path | 46 | 368 |
| derived field without a direct Graph store transition | 13 | 104 |
| stored field outside the Mint Graph-store closure | 98 | 784 |

The two selected Pool TVL fields per segment are included in the 142 stored
setter outcomes. Pool Mint v1 binds their structural old-plus-converted-Mint-
amount flow and the same loaded Pool save after both setters; numeric meaning
remains false.

Direct schema authority gives `Mint` 13 required fields and three nullable
fields: `sender`, `amountUSD`, and `logIndex`. All 16 have retained setter paths,
so the Mint required-absence overlay is exactly zero.

All 13 derived fields lack a direct Graph store transition. Five have matching
child-association setter paths: `Pool.mints`, `Pool.poolDayData`,
`Pool.poolHourData`, `Token.tokenDayData`, and `Transaction.mints`. This does not
prove Graph query visibility or relation materialization.

The 46 reachable-store/no-setter fields are described only by that static
absence. They are never called preserved, unchanged, value-exact, or persisted.

## Closed ledgers

For every mapping, the verifier independently closes:

- 172 lexical schema-field invocations;
- 176 physical-site-to-invocation edges, including four nullable setter branch
  alternatives;
- 244 handler-expanded setter paths after exact helper multiplicity;
- 142 unique stored setter-field identities;
- 13 lexical Graph-store invocations, 12 physical host store sites/targets, and
  17 handler-expanded store paths; and
- zero unclassified reachable `TypedMap#set` sites.

Across eight mappings those are 1,376 lexical invocations, 1,408 site edges,
1,952 setter paths, 104 lexical stores, 96 physical stores, and 136 expanded
store paths. The 12 targets are `Factory`, `Mint`, `Pool`, `PoolDayData`,
`PoolHourData`, `Tick`, `TickDayData`, `Token`, `TokenDayData`,
`TokenHourData`, `Transaction`, and `UniswapDayData`.

Physical and semantic ledgers must not be conflated. Each legacy mapping has
182 reachable functions, 914 direct calls, 166 direct memory writes, and 65
physical `TypedMap#set` sites. Each modern mapping has 96 / 1,094 / 584 / 174.
The totals are 1,284 functions, 7,672 calls, 2,164 writes, and 738 physical map
sets. These are not the 172 lexical invocation or 244 path denominators.

## Ordering and guards

The two selected Pool setters precede the same loaded Pool's sole save on the
selected normal-continuation path. Every other stored-setter outcome claims
only retained setter-before-matching-store call order.

For the two modern mappings, all effect callsites are inside the two-Token
presence guard. Each `createTick` call is inside its corresponding tick-missing
branch at control depth two; the two Tick update helpers follow conditional
creation at depth one inside the outer guard. Legacy `createTick` calls remain
inside their tick-missing branches, while legacy effect paths are limited to
potential normal continuation.

Imported numeric/comparator and contract-call semantics, payload/heap alias
safety, later-overwrite exclusion, preservation, Graph store visibility,
persistence, rollback, post-fatal execution, historical branch outcomes, and
complete histories remain false. Scheduler, runtime population, output, Store,
package, source-package identity, continuity, oracle, logical/physical/PoI
parity, checkpoint, backfill, deployment, production, and readiness also remain
false. This is a bounded issue #38 slice; no issue checkbox is complete.

```console
python3 scripts/verify-uniswap-v3-pool-mint-v2.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_mint_v2
```

Byte-identical regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-mint-v2.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for the authority chain.
