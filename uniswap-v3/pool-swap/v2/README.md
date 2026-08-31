# Uniswap V3 Pool Swap schema-API matrix v2

This additive offline certificate publishes a conservative, complete,
lexical static schema-API effect matrix for `Pool.handleSwap` across all
eight retained Uniswap V3 Pool mappings. It directly recomputes Pool Swap core
v1, Pool Swap fee-growth v1, Pool runtime v1, segment-field semantics v2, and
the 299-field GraphQL schema. Pool Mint v2 and the other complete matrices are
ordering references, not semantic inputs.

The certificate proves setter and store flows separately. Each setter's exact
retained receiver operand is followed through a named setter parameter or
through a constructor's internal `TypedMap#set` receiver to the immediately
following terminal `local.get` on normal fallthrough; each store's target,
receiver, and stored-value operands are independently reconstructed. The
cross-ledger relation is deliberately weaker: a setter is related to a store
only by lexical order within one retained function group and overlap between
their branch-merged receiver value-origin sets. At invocation level, 1,089 of
1,576 classifications reference only equal-origin-set stores and 487 reference
overlap-only stores. Separately, the 1,720 setter-to-store edges comprise 1,233
equal-origin-set and 487 overlap-only edges. This is may-alias evidence. It does
not prove branch correlation, a common execution, or that the setter and store
receivers must alias.

Constructor evidence is also fallthrough-scoped: the internal map set must be
immediately followed by a direct terminal `local.get` with the same time-scoped
receiver origins. It does not prove that every successful constructor return or
control path returns that receiver.

## Complete outcome matrix

Every segment has exactly 299 mutually exclusive outcomes, for 2,392 total:

| Lexical static category | Per segment | Eight segments |
|---|---:|---:|
| stored field with an exact setter and lexically later same-group store receiver-origin overlap | 144 | 1,152 |
| stored field on a reachable entity store without an exact schema setter | 45 | 360 |
| derived field without a direct Graph store transition | 13 | 104 |
| stored field outside the Pool Swap Graph-store closure | 97 | 776 |

The three Pool Swap core fields and two fee-growth fields per segment are
overlays within the 144 stored outcomes, for 24 and 16 records respectively.
The core certificate binds `liquidity`, `tick`, and `sqrtPrice` before the first
of two same-Pool saves. The fee-growth certificate binds fee0 call/decode before
fee1 call/decode, both setters only after both successful decodes, and both
setters before the second same-Pool save. Numeric, contract-call host, alias,
persistence, and rollback meaning remain false.

Direct schema authority gives `Swap` fourteen required fields and one nullable
field, `logIndex`. All fifteen have retained setter flows, so the Swap
required-absence overlay is exactly zero.

All 13 derived fields lack a direct Graph store transition. Five have static
child-association setter paths: `Pool.swaps`, `Pool.poolDayData`,
`Pool.poolHourData`, `Token.tokenDayData`, and `Transaction.swaps`. This does
not prove Graph query visibility or relation materialization.

The 45 reachable-store/no-setter fields are never called preserved, unchanged,
value-exact, persisted, or last-writer stable.

## Closed physical and semantic ledgers

Every mapping has exactly 197 lexical schema-field invocations, 201
physical-site-to-invocation edges (including four nullable alternatives), 259
handler-expanded setter paths, and 144 unique stored setter-field identities.
There are zero unclassified reachable `TypedMap#set` sites.

Across all mappings, all 1,576 lexical setters have exact receiver-flow
bindings, all 1,608 physical receiver-flow edges are bound, and all 163 lexical
stores bind exact target, receiver, and stored-value operands. The separate
1,576 invocation classifications and their 1,720 setter-to-store edges prove
receiver-origin overlap only. Receiver origins are propagated by a finite CFG
worklist across structured branches, all branch-table targets, and loop
backedges to a fixed point, with terminating instructions excluded from
fallthrough. The contract
keeps each full store authority once under a stable ID; setter expansion and
overlap ledgers refer to IDs and digests instead of duplicating store operand
proofs. Its machine-readable authority flags are kind-specific: direct records
flag exact direct target/value operands, while `#save` records flag the
caller-to-save-parameter-to-store-value transit and never claim that transit
for a direct call.

The complete physical closure differs by retained profile:

| Profile | Functions | Calls | Direct writes | Physical map sets | Physical stores | Indirect |
|---|---:|---:|---:|---:|---:|---:|
| legacy Base | 197 | 1,183 | 185 | 60 | 13 | 0 |
| legacy mainnet root | 197 | 1,172 | 185 | 60 | 13 | 0 |
| legacy mainnet QmRv | 197 | 1,176 | 185 | 60 | 13 | 0 |
| legacy mainnet stable | 197 | 1,177 | 185 | 60 | 13 | 0 |
| legacy stable fee tier 1 / 100 | 197 each | 1,180 each | 185 each | 60 each | 13 each | 0 each |
| modern Base | 111 | 1,459 | 630 | 197 | 13 | 1 |
| modern mainnet | 111 | 1,441 | 628 | 197 | 13 | 1 |

Totals are 1,404 functions, 9,968 calls, 2,368 direct writes, 754 physical map
sets, 104 physical stores, and two indirect calls. Across all mappings the
semantic ledgers contain 1,576 lexical field invocations, 1,608 site edges,
2,072 expanded setter paths, 163 lexical stores, and 211 expanded store paths.
The five legacy-mainnet mappings additionally contribute 60 overlap
invocation classifications through helper returns (12 each). They reference 15 stable-ID exact
helper-internal-store → terminal-get → handler-local authority records (three
per mapping), for which the internal-store and terminal-get receiver origin
sets and local names must be equal and the two instructions must be adjacent on
immediate normal fallthrough. These records do not prove that every helper invocation or
control path returns the stored receiver, and they do not strengthen the
cross-ledger relation beyond receiver-origin overlap. Physical and semantic
ledgers must not be conflated.

## Profile-dependent stores and ordering

The five legacy-mainnet bindings each have 19 lexical and 25 expanded stores.
Legacy Base has 22 and 28. Each modern mapping has 23 and 29. All profiles close
the same 13 physical store targets: `Bundle`, `Factory`, `Pool`, `PoolDayData`,
`PoolHourData`, `Swap`, `Tick`, `TickDayData`, `Token`, `TokenDayData`,
`TokenHourData`, `Transaction`, and `UniswapDayData`.

Modern mappings contain two lexically ordered `PoolHourData` saves whose exact
receiver operands use the same local name, with no intervening `PoolHourData`
setter. This local-name evidence does not prove a common execution or receiver
must-alias, nor store visibility, persistence, version, or last-writer behavior.

In the five legacy-mainnet profiles, twelve handler setters for
`PoolHourData`/`TokenHourData` occur after their helper's only earlier store and
have no lexically later handler overlap store. Those field identities are
classified only because another exact setter invocation has a lexically later
same-group receiver-origin-overlap store. This does not prove that either pair
shares a feasible execution; no preservation or value claim is made.

Imported numeric/comparator and contract-call semantics, payload/heap alias
safety, later-overwrite exclusion, preservation, Graph store visibility,
persistence, rollback, post-fatal execution, historical outcomes, and complete
histories remain false. Scheduler, runtime population, output, Store, package,
source-package identity, continuity, oracle, logical/physical/PoI parity,
checkpoint, backfill, deployment, production, and readiness also remain false.
This is a bounded issue #38 slice; no issue checkbox is complete.

```console
python3 scripts/verify-uniswap-v3-pool-swap-v2.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_swap_v2
```

Byte-identical regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-swap-v2.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for the authority chain.
