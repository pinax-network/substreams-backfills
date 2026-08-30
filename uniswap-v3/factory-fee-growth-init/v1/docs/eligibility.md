# Eligibility boundary

This certificate adds conditional initialization call-flow evidence for two
fields only:

```text
Pool.feeGrowthGlobal0X128
Pool.feeGrowthGlobal1X128
```

For each of four unique legacy mappings, it proves the event-pool origin of
the same generic-constructor result used as the `Pool` receiver, both decoded
field keys, `$g2` as the pointer returned
by `ByteArray.fromI32(0)`, the kind-7 `Value.fromBigInt` wrapper's exact
same-pointer operands, the exact two `TypedMap#set` call operands, the
uninterrupted same-receiver path, and the eventual `Pool.save` call operands.
The selected path is conditional on normal continuation
past the excluded-pool return, both token-decimals returns, and any helper or
import trap.

Legacy selected field mutation remains false. The proof binds the outer
`TypedMap#set` dispatcher instructions and their update-store,
entry-constructor, and push-call operands, but it does not rederive inner
`getEntry`, string/index traversal, entry construction, array
push/reallocation, Entity construction/backing, or allocator semantics. Likewise, it
binds the Value wrapper's constructor result, kind, payload, and return
identity without claiming that `Value#constructor` allocated fresh storage.

Projection is exact and closed over the current segment matrix:

| Generation | Unique mappings | Segments | Selected field records |
|---|---:|---:|---:|
| legacy | 4 | 6 | 12 |
| modern parent | 2 | 2 | 4 |
| **total** | **6** | **8** | **16** |

The 28 unordered segment pairs receive deterministic scoped semantic and
provenance diffs. These diffs compare only the declared initialization
surface; they do not compare complete writer semantics, boundary state, or a
Graph oracle.

The cumulative field ledger remains **36 selected / 230 residual**. The
Factory closure remains **14/18**, with the same four legacy
`complete_static_handler_contract` paths unresolved. This supplement closes
none of those paths and does not claim the other 58 legacy stored fields.

The verifier positively binds:

- four immutable legacy WASM/WAT artifacts and Factory handlers;
- four complete module export/import/global-definition surfaces;
- native start, the complete mutable-global writer inventory, and the unique
  `start:src/utils/constants` write to `$g2` from `ByteArray.fromI32(0)`;
- four receiver-origin flows and four two-setter-through-`Pool.save` flows;
- exact `Value.fromBigInt`, outer `TypedMap#set`, and `Pool.save` call-operand
  capsules, with their inner semantic dependencies explicitly false;
- all six legacy and both modern segment projections, all 16 records, and all
  28 pairwise scoped diffs; and
- the recomputed Factory-effects, modern Factory static, Pool Swap fee-growth,
  field-semantics v2, and segment-writer-matrix parents.

The following remain strict JSON `false` values:

- all four legacy complete-static Factory contracts and all 60-field legacy
  coverage;
- safety of the legacy static arrays and correct ERC20 `totalSupply` result
  decoding;
- imported host, numeric, memory-reset, bytes-to-hex, and Graph store
  semantics;
- fresh Value allocation; `TypedMap#getEntry`/`get`, entry-constructor,
  entry-array push/reallocation, Entity construction/backing, and `Value#toString`
  semantics; and actual legacy selected-field mutation;
- numeric-zero preservation across reset/lifecycle behavior and cross-handler
  allocator freshness;
- selected persistence, later-overwrite exclusion, Graph rollback, runtime
  population, and complete Factory, Pool, or fee-growth histories;
- complete writer comparison, integrated scheduling, package consumption,
  post-fatal execution, target continuity, checkpoint, and oracle/parity;
- logical, physical, and proof-of-indexing parity; and
- issue #37 or #38 acceptance, backfill, deployment, production, or readiness.

The proof inventories all reachable residual effects without promoting their
semantics. Each legacy mapping has 44 reachable `TypedMap#set` sites: two
selected and 42 unclassified. Base retains 146 direct-memory-write sites
without selected-payload alias proof; each mainnet profile retains 154. The
reachable Graph store targets remain exactly `Bundle`, `Factory`, `Pool`, and
`Token`.
