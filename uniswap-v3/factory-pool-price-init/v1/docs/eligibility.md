# Eligibility boundary

This certificate adds conditional legacy Factory initialization call-flow
evidence for two fields only:

```text
Pool.token0Price
Pool.token1Price
```

For each of four unique legacy mappings, it proves the inherited event-pool
origin of `$l1`; the decoded direct field keys; `$g4` as the pointer returned
by imported `bigDecimal.fromString` when given the decoded AssemblyScript
string `"0"`; the unique internal write of that pointer to `$g4`; exact
`Value.fromBigDecimal` kind/payload/return identity; exact outer
`TypedMap#set` operands; and the uninterrupted same-receiver path to
`Pool.save`. The path is conditional on normal continuation past the
excluded-pool return, both token-decimals returns, and every helper or import
trap.

The import's numeric semantics are not rederived. The evidence does not claim
that `$g4` is a proven numeric zero, that BigDecimal parsing is correct, or that
numeric meaning survives host and lifecycle behavior. Legacy selected field
mutation also remains false: the proof binds outer operands but does not
rederive `TypedMap#getEntry`, traversal, entry construction, entry-array
push/reallocation, Entity construction or backing arrays, allocator behavior,
or fresh `Value` allocation.

## Projection

| Generation | Unique mappings | Segments | Selected field records |
|---|---:|---:|---:|
| legacy | 4 | 6 | 12 |
| modern parent | 2 | 2 | 4 |
| **total** | **6** | **8** | **16** |

All 28 unordered segment pairs receive deterministic scoped semantic and
provenance diffs. They compare only this initialization surface, not complete
writer semantics, boundary state, or a Graph oracle.

## Static-site and expanded-invocation accounting

The retained legacy reachability inventory has 44 static `TypedMap#set` sites
and 78 expanded handler-level map-write invocations.

After composing the fee-growth parent, BigInt parent, and this price slice:

- direct static-site classification is **8/44**, with 36 sites residual;
- expanded-invocation classification is **9/78**, with 69 invocations
  residual; and
- the shared `txCount` static site remains among the 36 residual sites.

The price slice adds direct relative handler sites and invocations 355 and
360. The cumulative direct sites are 327, 335, 340, 345, 350, 355, 360, and
365. The cumulative expanded invocations additionally include the selected
shared-helper call at line 330. Selecting that one invocation still does not
fully classify its static helper site or the three other receiver invocations.

Nine of 60 legacy Factory field initializers now have bounded call-flow
capsules. Fifty-one lack such capsules. All 60 complete legacy field contracts
nevertheless remain unproved because legacy mutation, persistence, and
complete history remain false.

The formal cumulative field ledger remains **36 selected / 230 residual**.
Factory closure remains **14/18**, with the same four legacy
`complete_static_handler_contract` paths unresolved. No tracking issue gains a
completed acceptance criterion from this certificate.

## Strict false gates

The following remain strict JSON `false` values:

- numeric semantics of imported `bigDecimal.fromString` and any claim that the
  `$g4` pointer is a proven numeric zero;
- all four legacy complete-static Factory contracts and all 60 complete legacy
  stored-field contracts;
- actual legacy price-field mutation and all inner `TypedMap`, entry, array,
  Entity backing, allocation, and general heap-alias semantics;
- safety of the legacy static arrays and correct ERC20 `totalSupply` result
  decoding;
- imported host, reset/lifecycle, bytes-to-hex, numeric, and Graph store
  semantics;
- fresh `Value` allocation, selected persistence, later semantic overwrite
  exclusion, Graph rollback, runtime population, historic outcomes, and
  complete Factory, Pool, or price history;
- integrated scheduling, package consumption, configured package identity,
  post-fatal execution, boundary continuity, checkpoint, and oracle/parity;
- logical, physical, and proof-of-indexing parity; and
- issue #37 or #38 acceptance, backfill, deployment, production, or readiness.
