# Uniswap V3 Pool Initialize semantics v2

This offline supplement closes the path-qualified static
`Pool.handleInitialize` writer contract for all eight retained mainnet and Base
segments. It is based directly on canonical Factory static v2 commit
`afaf3af9c25db029091d7699befe557276a442c7` and consumes both that exact
Factory contract and the exact Pool Initialize v1 contract without changing
either parent.

The verifier regenerates every mapping's WAT with checksum-pinned WABT 1.0.35
and binds every reachable function body, setter, save, fixed store target,
domain helper, remove path, direct-memory-write inventory, and indirect target.
It then classifies every one of the 299 schema fields in each of eight segments:
2,392 field outcomes and all 28 recursive semantic/provenance diffs.

## Complete static effect surface

The complete static reachable surface has 56 expanded field-write invocation
sites: five in the handler, 25 in `updatePoolDayData`, and 26 in
`updatePoolHourData`. These are potential lexical invocation sites, not one
execution trace. Each missing-row high/low setter is followed after the
create/existing join by a separate comparator-return-controlled setter, so the
create and later setter sites can both occur on the same normally completed
path.
The modern Token sites may all be skipped. For a normally completed path that
takes each corresponding effect branch, the exact call order is:

1. write in-memory `Pool.sqrtPrice` and `Pool.tick`;
2. save Pool in exactly three profiles and omit that save in five;
3. update and save `Bundle.ethPriceUSD`;
4. update and save Pool day and hour rows; and
5. when both Tokens are present, update both `Token.derivedETH` values and
   invoke Token save twice.

The three Pool-saving profiles are current mainnet, Base root, and current
Base. Their store closure contains Bundle, Pool, PoolDayData, PoolHourData, and
Token. The conservative writer matrix associates 95 entity fields, while 87
are directly stored; the remainder are `@derivedFrom` query fields with no
direct save transition. Missing interval-row creation can nevertheless add a
member to the derived `Pool.poolDayData` or `Pool.poolHourData` collection by
writing the child row's `pool` relation. The five historic mainnet profiles
omit Pool, leaving four targets, 59 conservative associations, and 58 directly
stored fields.

The no-Pool-save distinction is limited to call structure. In the three saving
profiles, the handler invokes `Pool.save` before invoking both interval helpers;
in the five historic profiles, no Pool save is reachable before those helpers.
Each helper subsequently reaches an exact `store.get` for Pool. The returned
Pool value's visibility or version is not proved: imported Graph store
read-after-write, persistence, and host semantics all remain false. Therefore
this certificate does not label which stored version a helper result represents.

For an existing day row, eight Pool-derived setter calls occur, including the
nullable tick setter. The result of
`BigInt#plus(existing-or-zero txCount, ONE_BI)` is written; imported BigInt
numeric meaning is unproved. Missing-row creation unconditionally writes both
high and low. After the create/existing join, separate comparator-return
branches may write high or low; when a branch does not select its setter, the
current entry is preserved. Imported BigDecimal comparator meaning is unproved,
so no ordering meaning is claimed. Nine create-only day fields are preserved
for existing rows. The hour row has the same classified effects plus an
unconditional close setter, leaving eight create-only fields preserved for
existing rows. Missing rows have classified constructor/setter effects for all
20 catalog fields: 19 are non-null in the schema and `tick: BigInt` is nullable,
with a generated non-null-write versus null/unset setter branch. The row ID is
`hex(event.address) + "-" + intervalIndex`,
where the interval index is the signed-i32 timestamp quotient by 86,400 or
3,600; the loaded `Pool.id` is used separately for the row's `pool` relation.
Modern mappings condition both Token updates and saves on both Token loads
being non-null and can normally return without either Token save; legacy
mappings certify only the successful non-null path.

## Boundary

“Complete” here means only the exact, normally completed, path-qualified
static Initialize contract. Stored transitions, preservation, conditional
child-create effects on derived interval collections, and the required absence
of direct writes for derived query fields are distinct outcomes.
Imported numeric and store-host behavior, Graph
rollback, actual historical branch outcomes and populations, complete entity
histories, integrated execution order, continuity, parity, writer consumption,
checkpoint authority, backfill, production, and readiness remain false. This
slice completes no checkbox in issue #37 or #38.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-pool-initialize-v2.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_initialize_v2
```

Intentional deterministic regeneration uses:

```bash
python3 scripts/verify-uniswap-v3-pool-initialize-v2.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for the exact input and mapping roots.
